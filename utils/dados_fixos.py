"""Regra fixa de indicadores (BR + EUA) - Issue #29.

Lista SOB DEMANDA: nenhum ticker é pré-cadastrado. Quando o usuário digita um ticker:
1. Já existe em `utils/dados_fixos.json` -> usa o salvo (ações, lucro, dividendo, fonte, data do
   balanço) e só recalcula com a cotação do dia.
2. Não existe -> busca 1x na fonte oficial (nunca no Yahoo): BRASIL = release/ITR/DFP entregue à
   CVM (hoje só esse passo; B3 como 2º passo é uma limitação conhecida, ver PR); EUA = SEC EDGAR,
   XBRL companyfacts (os mesmos fatos dos 10-Q/10-K, estruturados). Achou -> grava uma única vez
   e calcula. Não achou -> NÃO cria a entrada; devolve "Ticker não encontrado na fonte oficial.".

`acoes_total`, `lucro_12m` e `dividendo_12m` só mudam com balanço novo, split ou grupamento -
nunca recalculados todo dia. Ao buscar de novo um ticker já salvo, uma checagem leve (só a data
do balanço mais recente na fonte oficial, sem reler tudo) compara com `data_ultimo_balanco`
salvo; se a fonte tiver algo mais novo, a tela mostra o aviso "Balanço novo detectado, atualizar
dados fixos de [TICKER]?" - nunca sobrescreve sozinho.

Fórmulas fixas (não mude):
    LPA = lucro_12m / acoes_total
    P/L = cotacao / LPA
    DY  = dividendo_12m / cotacao
    P/L Médio 12m = média do P/L dos últimos 4 trimestres (cotação de fechamento do trimestre
                    ÷ LPA daquele trimestre)
ADR: LPA_ADR = LPA x fator_adr; Dividendo_ADR = Dividendo x fator_adr (fator_adr = quantas ações
compõem 1 ADR; default 1 quando o ticker não é um ADR). Lucro e cotação nunca se misturam entre
moedas: `moeda_resultado` diz em que moeda o lucro/dividendo foram divulgados.

Issue #35 (P/VP, Payout, ROE) - usam `patrimonio_liquido`, o valor de BALANÇO (estoque) do mesmo
documento/balanço mais recente que já deu `lucro_12m`/`acoes_total` - NUNCA somado como lucro/
dividendo (ver `extrair_patrimonio_liquido_br` e `_patrimonio_sec`):
    VPA    = patrimonio_liquido / acoes_total
    P/VP   = cotacao / VPA
    ROE    = lucro_12m / patrimonio_liquido
    Payout = dividendo_12m / LPA   (ver nota abaixo)

Nota sobre Payout: `dividendo_12m` já é por ação (Issue #31), e `lucro_12m` é o total da empresa -
dividir um pelo outro direto misturaria as duas bases (R$/ação ÷ R$ total) e daria uma % sem
sentido. Por isso o Payout usa LPA (lucro_12m / acoes_total) no denominador, não lucro_12m puro -
matematicamente é a MESMA razão que dividendo total / lucro total (os dois ÷ acoes_total se
cancelam), só que com os dados já calculados. Documentado com mais detalhe no CLAUDE.md.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
from pathlib import Path

from utils.fetch_guidance import (
    CONTABIL_IDADE_MAX,
    SEC_DADOS,
    _data,
    _data_br,
    _get_sec,
    cabecalho_sec,
    cik_do_ticker,
    cnpj_do_ticker,
    colunas_do_cabecalho,
    documentos_cvm,
    documentos_dividendo_cvm,
    fim_do_trimestre,
    ler_lucro_trimestre,
    multiplicador,
    normalizar,
    numero_br,
    sem_acento,
    texto_do_pdf,
    tri_anterior,
    trimestre_do_documento,
)

log = logging.getLogger("dados_fixos")

ARQ = Path(__file__).with_name("dados_fixos.json")
MENSAGEM_NAO_ENCONTRADO = "Ticker não encontrado na fonte oficial."
RE_B3 = re.compile(r"(?=.*[A-Z])[A-Z0-9]{4}\d{1,2}")


def eh_br(ticker: str) -> bool:
    """B3: 4 letras + 1-2 dígitos (ex.: PETR4, BBAS3) ou terminado em ".SA"."""
    t = ticker.strip().upper()
    return t.endswith(".SA") or bool(RE_B3.fullmatch(t))


def chave(ticker: str) -> str:
    """Ticker como chave do cadastro: maiúsculo, sem o sufixo ".SA"."""
    t = ticker.strip().upper()
    return t[:-3] if t.endswith(".SA") else t


def _ler() -> dict:
    try:
        d = json.loads(ARQ.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _gravar(dados: dict) -> None:
    ARQ.write_text(json.dumps(dict(sorted(dados.items())), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ------------------------------------------------------------ reuso de utils/contabil_br.json (27/11/2026)
# BUG REAL CORRIGIDO: este módulo reimplementava sua própria extração de ações/lucro da CVM, que
# divergia de utils/contabil_br.json pra BBAS3 - a linha genérica "Lucro Líquido" batia num valor
# errado no 4T25 (1,08 bi em vez de 4,97 bi) e extrair_acoes_br pegava o free float (2,84 bi) em
# vez do total emitido (5,71 bi). Em vez de corrigir as 2 extrações em paralelo (e arriscar
# divergir nas 2 de novo no futuro), quando o ticker já está configurado em
# utils/contabil_br_config.json (linha de lucro específica + travas de coluna do Issue #26, já
# testado), REUSA o resultado já calculado em utils/contabil_br.json pra ações e lucro - só
# dividendo e patrimônio líquido (que contabil_br.json não guarda) continuam extraídos aqui. Sem
# configuração (ticker novo), cai pra extração própria, corrigida pros mesmos 2 bugs (ver
# `extrair_acoes_br` acima e `linha_lucro` em `buscar_fixos_br` abaixo). Ver CLAUDE.md.
ARQ_CONTABIL_BR = Path(__file__).with_name("contabil_br.json")
ARQ_CONTABIL_BR_CFG = Path(__file__).with_name("contabil_br_config.json")


def _ler_json(caminho: Path) -> dict:
    try:
        d = json.loads(caminho.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _contabil_br_configurado(ticker: str, *, tabela_cfg: dict | None = None,
                             tabela_contabil: dict | None = None) -> dict | None:
    """Registro de utils/contabil_br.json pra `ticker`, só se ele estiver em
    utils/contabil_br_config.json e com status "ok", lucro e ações já calculados - None quando o
    ticker não está configurado (extração própria assume) ou o contábil ainda está pendente."""
    cfg = tabela_cfg if tabela_cfg is not None else _ler_json(ARQ_CONTABIL_BR_CFG)
    if ticker.upper() not in cfg:
        return None
    tab = tabela_contabil if tabela_contabil is not None else _ler_json(ARQ_CONTABIL_BR)
    c = tab.get(ticker.upper())
    if not c or c.get("status") != "ok" or c.get("lucro_12m") is None or not c.get("acoes") or not c.get("trimestres"):
        return None
    return c


# ------------------------------------------------------------ Brasil: PDF RI (release/ITR/DFP) na CVM
# Capa do ITR/DFP traz "Composição do Capital Social" com ações Ordinárias, Preferenciais e, quando
# há (ex.: units/BDRs - mais raro, mas existe na B3, ex. SANB11), Units, cada uma com a quantidade
# em circulação. acoes_total = soma de todas as classes achadas, NUNCA só ON.
RE_ON = re.compile(r"(?:a[çc][õo]es?\s+)?ordin[áa]rias?[^\d\n]{0,60}?(\d{1,3}(?:\.\d{3}){2,5})", re.I)
RE_PN = re.compile(r"(?:a[çc][õo]es?\s+)?preferenciais?[^\d\n]{0,60}?(\d{1,3}(?:\.\d{3}){2,5})", re.I)
RE_UNITS = re.compile(r"\bunits?\b[^\d\n]{0,60}?(\d{1,3}(?:\.\d{3}){2,5})", re.I)
RE_PRIORIDADE_DOC = re.compile(r"resultado|desempenho|release|press", re.I)
RE_RELATORIO_DOC = re.compile(r"an[áa]lise\s+gerencial|relat[óo]rio|release|press|"
                              r"divulga[çc][ãa]o\s+de\s+resultados|resultado", re.I)


def _inteiro_br(s: str) -> float:
    return float(s.replace(".", ""))


# BUG CORRIGIDO (27/11/2026, achado com BBAS3): o 1º número batido perto de "ordinárias" podia ser
# o de "Ações em circulação (free float)" (49,6% do total) em vez do TOTAL emitido (ex.: BBAS3,
# 2,84 bi de free float vs 5,71 bi de total emitido) - LPA/indicadores por ação precisam sempre do
# TOTAL, nunca de um subconjunto (free float, tesouraria, em poder de terceiros). Documentado com
# mais detalhe no CLAUDE.md.
RE_QUALIFICADOR_SUBCONJUNTO = re.compile(r"circula[çc][ãa]o|free\s*float|tesouraria|em\s+poder\s+d[oe]", re.I)


def _primeiro_total(regex: re.Pattern, texto: str, janela: int = 120) -> str | None:
    """1º número batido por `regex` cujo contexto - ANTES do match E dentro dele (ex.: "ordinárias
    em circulação (free float) ... 2.843.025.842", onde o qualificador fica ENTRE a palavra-chave e
    o número capturado) - não indica um subconjunto do total (circulação/free float/tesouraria).
    Pula esses e segue procurando um match melhor."""
    for m in regex.finditer(texto):
        # só a MESMA linha antes do match - uma linha de free float/tesouraria ANTERIOR (ex.: uma
        # seção inteira sobre movimentação de free float, várias linhas antes da linha certa) não
        # pode desqualificar uma linha diferente, sem relação, mais abaixo no documento.
        antes = texto[max(0, m.start() - janela):m.start()].rsplit("\n", 1)[-1]
        if RE_QUALIFICADOR_SUBCONJUNTO.search(antes) or RE_QUALIFICADOR_SUBCONJUNTO.search(m.group(0)):
            continue
        return m.group(1)
    return None


def extrair_acoes_br(texto: str) -> tuple[float | None, str]:
    """ON + PN + Units TOTAIS emitidos achados no texto (capa do ITR/DFP, "Composição do Capital
    Social") - nunca um subconjunto como free float ou tesouraria (ver `_primeiro_total`). None se
    nenhuma classe for encontrada. `detalhe` lista as classes achadas, para a conta aparecer na tela."""
    partes = []
    for nome, regex in (("ON", RE_ON), ("PN", RE_PN), ("Units", RE_UNITS)):
        valor = _primeiro_total(regex, texto)
        if valor:
            partes.append((nome, _inteiro_br(valor)))
    if not partes:
        return None, ""
    total = sum(v for _, v in partes)
    return total, " + ".join(f"{n} {v:,.0f}".replace(",", ".") for n, v in partes)


# ------------------------------------------------------------ Brasil: dividendo/JCP por ação (Issue #31)
# Dois jeitos possíveis de achar o dividendo+JCP DECLARADO de um trimestre num documento da CVM:
# (a) tabela do próprio release/relatório de resultados, mesma estrutura de colunas trimestrais já
#     usada para o Lucro Líquido (ex. BBAS3: "JCP/Dividendos por Ação - R$ 0,07 0,16 0,04 ...") - já
#     vem em R$ por ação, sem multiplicador de milhões/bilhões;
# (b) um documento separado (Fato Relevante/Aviso aos Acionistas) anunciando a distribuição daquele
#     trimestre em texto corrido (ex. PETR4: "Valor a ser pago: R$ 1,18732774 por ação ... declarada
#     com base no balanço de 30 de setembro de 2026" ou, no anúncio anual, "... relativa ao quarto
#     trimestre de 2025"). Tentamos (a) primeiro (documento já lido, sem chamada de rede extra); só
#     buscamos os documentos de (b), um por um, para os trimestres que (a) não achou.
RE_LINHA_DIVIDENDO_ACAO = re.compile(
    r"(?:JCP(?:\s*/\s*Dividendos?)?|Dividendos?(?:\s*/\s*(?:e/ou\s+)?JCP)?|Proventos?)\s+por\s+A[çc][ãa]o",
    re.I,
)
RE_VALOR_PAGO_ACAO = re.compile(r"valor\s+a\s+ser\s+pago:?\s*R\$\s*(\d+(?:,\d+)?)\s*por\s+a[çc][ãa]o", re.I)
RE_EQUIVALENTE_ACAO = re.compile(r"equivalente\s+a\s+R\$\s*(\d+(?:,\d+)?)\s*por\s+a[çc][ãa]o", re.I)
RE_BALANCO_DE = re.compile(r"balan[çc]o\s+de\s+\d{1,2}\s+de\s+(\w+)\s+de\s+(\d{4})", re.I)
RE_TRIMESTRE_ORDINAL = re.compile(r"(primeiro|segundo|terceiro|quarto)\s+trimestre\s+de\s+(\d{4})", re.I)
MESES_PT = {sem_acento(nome): i for i, nome in enumerate(
    ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro",
     "outubro", "novembro", "dezembro"), 1)}
TRI_DO_MES_FIM = {3: 1, 6: 2, 9: 3, 12: 4}             # mês de fim de trimestre -> número do trimestre
ORDINAL_TRI = {"primeiro": 1, "segundo": 2, "terceiro": 3, "quarto": 4}


def extrair_dividendo_tabela(texto: str, tri: str) -> float | None:
    """Dividendo/JCP por ação do trimestre `tri`, pela tabela de destaques do release/relatório de
    resultados (mesma técnica de `ler_lucro_trimestre`/`colunas_do_cabecalho`, mas já em R$ por ação
    - sem multiplicador de milhões/bilhões). None sem a linha, ou sem o trimestre no cabeçalho."""
    t = normalizar(texto)
    padrao = rf"{RE_LINHA_DIVIDENDO_ACAO.pattern}[^\n\d]{{0,25}}((?:\(?-?\d{{1,3}}(?:\.\d{{3}})*(?:,\d+)?\)?%?\s+){{1,12}})"
    for m in re.finditer(padrao, t, re.I):
        antes = t[max(0, m.start() - 2500): m.start()]
        grupos = [g for g in re.finditer(r"((?:\b[1-4]T\d{2}\b[\s/]*){1,10})", antes)
                  if tri in re.findall(r"\b[1-4]T\d{2}\b", g.group(1))]
        if not grupos:
            continue
        candidatos = [colunas_do_cabecalho(re.findall(r"\b[1-4]T\d{2}\b", g.group(1)), tri) for g in grupos]
        colunas = max(reversed(candidatos), key=len)
        valores = [v for v in m.group(1).split() if not v.endswith("%")]
        if len(valores) < len(colunas):
            continue
        bruto = valores[colunas.index(tri)]
        if bruto.startswith("("):
            continue                          # dividendo nunca é negativo - linha errada
        return numero_br(bruto)
    return None


def _tri_do_anuncio_dividendo(texto: str) -> str | None:
    """Trimestre a que se refere um Fato Relevante/Aviso aos Acionistas de dividendo: pela data do
    balanço ("declarada com base no balanço de 30 de setembro de 2026" -> 3T26) ou, no anúncio do
    4º trimestre/exercício, pelo ordinal ("relativa ao quarto trimestre de 2025" -> 4T25)."""
    m = RE_BALANCO_DE.search(texto)
    if m:
        mes, ano = m.groups()
        q = TRI_DO_MES_FIM.get(MESES_PT.get(sem_acento(mes)))
        if q:
            return f"{q}T{int(ano) % 100:02d}"
    m = RE_TRIMESTRE_ORDINAL.search(texto)
    if m:
        ordinal, ano = m.groups()
        q = ORDINAL_TRI.get(sem_acento(ordinal))
        if q:
            return f"{q}T{int(ano) % 100:02d}"
    return None


def extrair_dividendo_fato_relevante(texto: str) -> tuple[float, str] | None:
    """Dividendo/JCP por ação declarado num Fato Relevante/Aviso aos Acionistas de remuneração ao
    acionista (texto corrido, não tabela). Devolve (valor, trimestre) ou None sem achar os dois."""
    t = normalizar(texto)
    m = RE_VALOR_PAGO_ACAO.search(t) or RE_EQUIVALENTE_ACAO.search(t)
    if not m:
        return None
    tri = _tri_do_anuncio_dividendo(t)
    if not tri:
        return None
    return numero_br(m.group(1)), tri


def _dividendo_por_tri(tris_faltando: set[str], hoje: dt.date, empresa: tuple[str, str], *,
                       buscar_docs_dividendo, ler_pdf) -> dict[str, float]:
    """Busca, só para os trimestres de `tris_faltando`, o dividendo/JCP por ação num Fato
    Relevante/Aviso aos Acionistas (2º passo - a tabela do release já foi tentada antes)."""
    achados: dict[str, float] = {}
    if not tris_faltando:
        return achados
    try:
        docs = buscar_docs_dividendo(empresa[0], hoje)
    except Exception as e:  # noqa: BLE001 - busca best-effort; sem ela, só fica "Sem dado"
        log.info("documentos de dividendo indisponíveis (%s)", e.__class__.__name__)
        return achados
    for doc in docs:
        if len(achados) >= len(tris_faltando):
            break
        try:
            _, texto = ler_pdf(doc["link"])
        except Exception as e:  # noqa: BLE001
            log.info("não abriu %s (%s)", doc["link"], e.__class__.__name__)
            continue
        r = extrair_dividendo_fato_relevante(texto)
        if r and r[1] in tris_faltando and r[1] not in achados:
            achados[r[1]] = r[0]
    return achados


# ------------------------------------------------------------ Brasil: patrimônio líquido (Issue #35)
# Patrimônio líquido é um valor de BALANÇO (estoque, "quanto a empresa tem agora"), NUNCA um fluxo
# trimestral somado como lucro/dividendo - é sempre o valor do balanço MAIS RECENTE, igual a como
# acoes_total já pega o valor mais recente (não uma soma). Vem do MESMO documento mais recente que já
# deu acoes_total/o último trimestre de lucro (nunca abre documento adicional). Duas formas vistas nos
# documentos da CVM: (a) tabela de destaques com colunas por trimestre (ex. BBAS3, "3T25 2T26 3T26 ..."),
# mesma técnica de `ler_lucro_trimestre`/`colunas_do_cabecalho` já usada para o lucro; (b) Balanço
# Patrimonial com 2 colunas de DATA, mais recente primeiro (ex. PETR4/Petrobras, "30.09.2026 31.12.2025") -
# usa a 1ª coluna, confirmando que a data bate com o trimestre `tri` já identificado para o lucro/ações, e
# a unidade (milhões/bilhões) do próprio cabeçalho da tabela.
RE_CABECALHO_DATAS_PL = re.compile(
    r"R\$\s*(milh[õo]es|bilh[õo]es)[^\n]{0,20}?(\d{2}\.\d{2}\.\d{4})\s+(\d{2}\.\d{2}\.\d{4})", re.I)
RE_PATRIMONIO_LINHA = re.compile(
    r"patrim[ôo]nio\s+l[íi]quido(?:\s+consolidado)?\s*"
    r"((?:\(?-?\d{1,3}(?:\.\d{3})*(?:,\d+)?\)?\s+){1,6})", re.I)
RE_EXCLUIR_PATRIMONIO = re.compile(r"(retorno|rentabilidade|rspl)\s+sobre|sobre\s+o?\s*patrim", re.I)


def extrair_patrimonio_liquido_br(texto: str, tri: str) -> tuple[float | None, str]:
    """Patrimônio líquido do balanço mais recente (trimestre `tri`), nunca somado. None sem achar
    em nenhuma das 2 formas vistas nos documentos da CVM (ver comentário acima)."""
    t = normalizar(texto)
    r = ler_lucro_trimestre(t, tri, "Patrimônio Líquido", tabela_vence=True)
    if r["valor"] is not None:
        return r["valor"], "tabela de destaques do release/relatório (coluna do trimestre)"
    data_esperada = f"{fim_do_trimestre(tri):%d.%m.%Y}"
    for h in RE_CABECALHO_DATAS_PL.finditer(t):
        unidade, data1, data2 = h.groups()
        if data1 != data_esperada:
            continue
        mult = multiplicador(unidade)
        if not mult:
            continue
        resto = t[h.end(): h.end() + 4000]
        for m in RE_PATRIMONIO_LINHA.finditer(resto):
            antes = resto[max(0, m.start() - 40): m.start()]
            if RE_EXCLUIR_PATRIMONIO.search(antes):
                continue
            valores = m.group(1).split()
            if not valores or valores[0].startswith("("):
                continue                      # patrimônio líquido negativo - leitura suspeita, ignora
            return numero_br(valores[0]) * mult, f"Balanço Patrimonial ({unidade}, coluna {data1})"
    return None, ""


def buscar_fixos_br(ticker: str, hoje: dt.date, *, buscar_cnpj=cnpj_do_ticker, buscar_docs=documentos_cvm,
                    ler_pdf=texto_do_pdf, buscar_docs_dividendo=documentos_dividendo_cvm,
                    contabil_cfg: dict | None = None, contabil_tabela: dict | None = None) -> dict:
    """Fonte oficial do Brasil: 1º PDF RI (release/ITR/DFP), documentos entregues à CVM (IPE).

    Ações e lucro: REUSA utils/contabil_br.json quando o ticker já está configurado em
    utils/contabil_br_config.json (ver `_contabil_br_configurado`) - nunca reimplementa essa
    extração aqui (bug real corrigido 27/11/2026: a extração própria divergia do contabil_br.json
    pra BBAS3, ver CLAUDE.md). Sem configuração (ticker novo), cai pra extração própria
    (`extrair_acoes_br` + a linha de lucro do config, se existir, senão "Lucro Líquido" genérico).

    2º passo (B3) não está implementado: hoje só a CVM, que já é a fonte primária (release/ITR/DFP
    é o próprio documento entregue pela empresa) - ver limitação no PR."""
    empresa = buscar_cnpj(ticker, hoje)
    if not empresa:
        return {"status": "nao_encontrado", "motivo": "CNPJ não encontrado na CVM"}
    docs = buscar_docs(empresa[0], hoje)
    if not docs:
        return {"status": "nao_encontrado", "motivo": "nenhum documento de resultado na CVM"}
    docs = sorted(docs, key=lambda d: (d["data"], bool(RE_PRIORIDADE_DOC.search(
        f"{d.get('categoria', '')} {d.get('tipo', '')} {d.get('assunto', '')}"))), reverse=True)

    contabil = _contabil_br_configurado(ticker, tabela_cfg=contabil_cfg, tabela_contabil=contabil_tabela)
    dividendos: dict[str, float] = {}         # tri -> dividendo/JCP por ação (abordagem (a), tabela)
    patrimonios: dict[str, float] = {}        # tri -> patrimônio líquido (valor do balanço, nunca somado)
    fontes_patrimonio: dict[str, str] = {}

    if contabil:
        lidos: dict[str, dict] = {x["tri"]: {"tri": x["tri"], "fim": x["fim"], "lucro": x["lucro"],
                                             "data": x.get("data", ""), "url": x.get("url", "")}
                                  for x in contabil["trimestres"][-4:]}
        acoes = contabil["acoes"]
        acoes_detalhe = "mesmo total usado no LPA contábil"
        fonte_acoes = f"{contabil.get('fonte') or 'release de resultados'} (reusado de contabil_br.json, Issue #26)"
        linha_lucro = None   # lucro já veio pronto de contabil_br.json, não precisa extrair de novo
    else:
        lidos, acoes, acoes_detalhe, fonte_acoes = {}, None, "", ""
        cfg = contabil_cfg if contabil_cfg is not None else _ler_json(ARQ_CONTABIL_BR_CFG)
        linha_lucro = (cfg.get(ticker.upper()) or {}).get("linha") or "Lucro Líquido"

    for doc in docs:
        data_doc = _data(doc["data"])
        if not data_doc:
            continue
        tri = trimestre_do_documento(data_doc)
        falta_lucro = linha_lucro is not None and tri not in lidos
        falta_div = tri in lidos and tri not in dividendos
        falta_pl = tri in lidos and tri not in patrimonios
        if not (falta_lucro or falta_div or falta_pl) and acoes:
            continue
        try:
            _, texto = ler_pdf(doc["link"])
        except Exception as e:  # noqa: BLE001
            log.info("%s: não abriu %s (%s)", ticker, doc["link"], e.__class__.__name__)
            continue
        if acoes is None:
            a, det = extrair_acoes_br(texto)
            if a:
                acoes, acoes_detalhe = a, det
                fonte_acoes = f"{doc.get('categoria') or doc.get('tipo') or 'documento CVM'} de {_data_br(doc['data'])}"
        if falta_lucro:
            relatorio = bool(RE_RELATORIO_DOC.search(f"{doc.get('categoria', '')} {doc.get('tipo', '')} {doc.get('assunto', '')}"))
            r = ler_lucro_trimestre(texto, tri, linha_lucro, tabela_vence=relatorio)
            if r["valor"] is not None:
                lidos[tri] = {"tri": tri, "fim": f"{fim_do_trimestre(tri):%d/%m/%Y}", "lucro": r["valor"],
                             "data": _data_br(doc["data"]), "url": doc["link"]}
        if tri in lidos and tri not in dividendos:
            valor_div = extrair_dividendo_tabela(texto, tri)
            if valor_div is not None:
                dividendos[tri] = valor_div
        if tri in lidos and tri not in patrimonios:
            valor_pl, fonte_pl = extrair_patrimonio_liquido_br(texto, tri)
            if valor_pl is not None:
                patrimonios[tri], fontes_patrimonio[tri] = valor_pl, fonte_pl
        ordem = sorted(lidos, key=fim_do_trimestre)
        completo_lucro = acoes and len(ordem) >= 4 and all(tri_anterior(b) == a for a, b in zip(ordem[-4:], ordem[-3:]))
        if completo_lucro and set(ordem[-4:]) <= set(dividendos) and ordem[-1] in patrimonios:
            break
    if not acoes:
        return {"status": "nao_encontrado", "motivo": "número de ações (ON/PN/Units) não encontrado nos documentos da CVM"}
    ult = sorted(lidos.values(), key=lambda x: fim_do_trimestre(x["tri"]))[-4:]
    if len(ult) < 4 or any(tri_anterior(b["tri"]) != a["tri"] for a, b in zip(ult, ult[1:])):
        return {"status": "nao_encontrado", "motivo": "4 trimestres consecutivos de lucro líquido não encontrados na CVM"}
    # dividendo/JCP: 4 trimestres de ult, mesma lógica trimestral do lucro (Issue #31). (a) tabela do
    # release/relatório já lido (acima); (b) Fato Relevante/Aviso aos Acionistas, só para quem faltou.
    tris_ult = [x["tri"] for x in ult]
    faltando = {t for t in tris_ult if t not in dividendos}
    if faltando:
        dividendos.update(_dividendo_por_tri(faltando, hoje, empresa,
                                             buscar_docs_dividendo=buscar_docs_dividendo, ler_pdf=ler_pdf))
    for x in ult:
        if x["tri"] in dividendos:
            x["dividendo"] = dividendos[x["tri"]]
    if all(t in dividendos for t in tris_ult):
        dividendo_12m, dividendo_motivo = sum(dividendos[t] for t in tris_ult), None
        fonte_dividendo = "tabela do release/relatório de resultados (por ação)" if not faltando else \
            "tabela do release/relatório de resultados + Fato Relevante/Aviso aos Acionistas (por ação)"
    else:
        ainda_faltando = sorted((t for t in tris_ult if t not in dividendos), key=fim_do_trimestre)
        dividendo_12m, dividendo_motivo = None, (
            f"dividendo/JCP por ação não encontrado para {', '.join(ainda_faltando)} "
            "nos documentos lidos (release/relatório de resultados e Fato Relevante/Aviso aos Acionistas)")
        fonte_dividendo = None
    # patrimônio líquido (Issue #35): valor do balanço MAIS RECENTE (tris_ult[-1]), NUNCA somado -
    # mesmo documento que já deu acoes_total/o último trimestre de lucro.
    tri_recente = tris_ult[-1]
    patrimonio_liquido = patrimonios.get(tri_recente)
    if patrimonio_liquido is not None:
        patrimonio_motivo, fonte_patrimonio = None, fontes_patrimonio[tri_recente]
    else:
        patrimonio_motivo = f"Patrimônio Líquido não encontrado no documento mais recente ({tri_recente})"
        fonte_patrimonio = None
    if contabil:
        tipo_acao = "Total (contabil_br.json)"
    elif " + " in acoes_detalhe:
        tipo_acao = "ON+PN"
    elif "ON" in acoes_detalhe:
        tipo_acao = "ON"
    else:
        tipo_acao = acoes_detalhe
    lucro_fonte_txt = "reusado de contabil_br.json (Issue #26)" if contabil else "release de resultados trimestral"
    return {
        "status": "ok", "acoes_total": acoes, "acoes_detalhe": acoes_detalhe, "tipo_acao": tipo_acao,
        "fator_adr": 1, "moeda_resultado": "BRL",
        "fonte_oficial": f"PDF RI (CVM/IPE) - ações: {fonte_acoes}; lucro: {lucro_fonte_txt}"
                        + (f"; dividendo: {fonte_dividendo}" if fonte_dividendo else "")
                        + (f"; patrimônio líquido: {fonte_patrimonio}" if fonte_patrimonio else ""),
        "data_ultimo_balanco": ult[-1]["fim"], "lucro_12m": sum(x["lucro"] for x in ult),
        "dividendo_12m": dividendo_12m, "dividendo_motivo": dividendo_motivo,
        "patrimonio_liquido": patrimonio_liquido, "patrimonio_motivo": patrimonio_motivo,
        "trimestres": ult,
    }


def _data_mais_recente_br(ticker: str, hoje: dt.date, *, buscar_cnpj=cnpj_do_ticker, buscar_docs=documentos_cvm) -> str | None:
    """Só a data do documento de resultado mais recente na CVM, sem baixar/ler PDF - usada para
    detectar balanço novo sem reler/recalcular tudo todo dia."""
    empresa = buscar_cnpj(ticker, hoje)
    if not empresa:
        return None
    docs = [d for d in buscar_docs(empresa[0], hoje) if RE_PRIORIDADE_DOC.search(f"{d.get('categoria', '')} {d.get('tipo', '')} {d.get('assunto', '')}")]
    if not docs:
        return None
    mais_novo = max(docs, key=lambda d: d["data"])
    data_doc = _data(mais_novo["data"])
    return f"{fim_do_trimestre(trimestre_do_documento(data_doc)):%d/%m/%Y}" if data_doc else None


# ------------------------------------------------------------ EUA: SEC EDGAR, XBRL companyfacts (10-Q/10-K)
FORMS_SEC_PERIODICOS = ("10-Q", "10-K", "10-Q/A", "10-K/A")


def soma_12m_sec(fatos: dict, tag: str, unidade: str, hoje: dt.date) -> dict:
    """Soma dos últimos 4 trimestres de um fato XBRL qualquer (ex.: us-gaap:NetIncomeLoss), nos
    mesmos moldes de `fetch_guidance.lpa_ttm_sec` (3 meses direto do 10-Q; 4º trimestre fiscal =
    ano do 10-K menos os 9 meses acumulados do 10-Q). Devolve {"status": "ok", "valor_12m",
    "data_fim", "trimestres"} ou {"status": "incompleto", "motivo"}."""
    dados = (((fatos.get("facts") or {}).get("us-gaap") or {}).get(tag) or {}).get("units", {}).get(unidade, [])
    if not dados:
        return {"status": "incompleto", "motivo": f"SEC sem {tag} ({unidade})"}
    por_periodo: dict[tuple, dict] = {}
    for e in dados:
        if e.get("form") not in FORMS_SEC_PERIODICOS or "start" not in e or "end" not in e:
            continue
        ini, fim = _data(e["start"]), _data(e["end"])
        if not ini or not fim:
            continue
        ch = (ini, fim)
        if ch not in por_periodo or e.get("filed", "") > por_periodo[ch].get("filed", ""):
            por_periodo[ch] = e
    tri: dict[dt.date, tuple] = {}
    longos = []
    for (ini, fim), e in por_periodo.items():
        dias = (fim - ini).days
        if 80 <= dias <= 100:
            tri[fim] = (float(e["val"]), e.get("filed", ""), e.get("form", ""))
        elif 255 <= dias <= 285 or 350 <= dias <= 380:
            longos.append((ini, fim, dias, float(e["val"]), e.get("filed", ""), e.get("form", "")))
    for ini, fim, dias, val, filed, form in longos:
        if dias < 350 or fim in tri:
            continue
        nove = next((l for l in longos if l[0] == ini and 255 <= l[2] <= 285), None)
        if nove:
            tri[fim] = (val - nove[3], filed, form)
    fins = sorted(tri)
    if len(fins) < 4:
        return {"status": "incompleto", "motivo": f"só {len(fins)} trimestre(s) na SEC"}
    ultimos = fins[-4:]
    if any(not 80 <= (b - a).days <= 100 for a, b in zip(ultimos, ultimos[1:])):
        return {"status": "incompleto", "motivo": "trimestres da SEC não são consecutivos"}
    if (hoje - ultimos[-1]).days > CONTABIL_IDADE_MAX:
        return {"status": "incompleto", "motivo": f"último trimestre na SEC termina em {ultimos[-1]:%d/%m/%Y}"}
    return {"status": "ok", "valor_12m": round(sum(tri[f][0] for f in ultimos), 6),
            "data_fim": f"{ultimos[-1]:%d/%m/%Y}",
            "trimestres": [{"fim": f"{f:%d/%m/%Y}", "valor": round(tri[f][0], 6), "form": tri[f][2]} for f in ultimos]}


def _acoes_sec(fatos: dict) -> float | None:
    """dei:EntityCommonStockSharesOutstanding (capa do 10-Q/10-K); se faltar, us-gaap:CommonStockSharesOutstanding."""
    unidades = (((fatos.get("facts") or {}).get("dei") or {}).get("EntityCommonStockSharesOutstanding") or {}).get("units", {}).get("shares", [])
    if not unidades:
        unidades = (((fatos.get("facts") or {}).get("us-gaap") or {}).get("CommonStockSharesOutstanding") or {}).get("units", {}).get("shares", [])
    if not unidades:
        return None
    melhor = max(unidades, key=lambda e: (e.get("end") or "", e.get("filed") or ""))
    return float(melhor["val"])


TAGS_PATRIMONIO_SEC = ("StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest")


def _patrimonio_sec(fatos: dict, data_fim: dt.date) -> tuple[float | None, str | None]:
    """Patrimônio líquido (us-gaap:StockholdersEquity; se faltar,
    StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest - companhias com
    participação de não controladores às vezes só têm o segundo). Valor do balanço no MESMO
    período/instante (`data_fim`) que já deu lucro_12m/acoes_total - NUNCA somado (é estoque, não
    fluxo). None sem o fato nessa data em nenhuma das 2 tags."""
    for tag in TAGS_PATRIMONIO_SEC:
        unidades = (((fatos.get("facts") or {}).get("us-gaap") or {}).get(tag) or {}).get("units", {}).get("USD", [])
        candidatos = [e for e in unidades if _data(e.get("end")) == data_fim]
        if candidatos:
            melhor = max(candidatos, key=lambda e: e.get("filed") or "")
            return float(melhor["val"]), tag
    return None, None


def buscar_fixos_eua(ticker: str, hoje: dt.date, *, cabecalho=cabecalho_sec, buscar_cik=cik_do_ticker) -> dict:
    """Fonte oficial dos EUA: SEC EDGAR, XBRL companyfacts - os mesmos fatos estruturados que vêm
    dos formulários 10-Q/10-K (nunca Investor Relations: a issue pede IR como 2º passo, mas a SEC já
    responde para qualquer ticker listado nos EUA, então o 2º passo não chegou a ser necessário;
    ver limitação no PR)."""
    cab = cabecalho()
    if not cab:
        return {"status": "nao_encontrado", "motivo": "sem SEC_CONTACT_EMAIL"}
    empresa = buscar_cik(ticker, cab)
    if not empresa:
        return {"status": "nao_encontrado", "motivo": "ticker não encontrado na SEC"}
    fatos = _get_sec(f"{SEC_DADOS}/api/xbrl/companyfacts/CIK{empresa[0]}.json", cab).json()
    lucro = soma_12m_sec(fatos, "NetIncomeLoss", "USD", hoje)
    if lucro["status"] != "ok":
        return {"status": "nao_encontrado", "motivo": f"lucro líquido (NetIncomeLoss): {lucro['motivo']}"}
    acoes = _acoes_sec(fatos)
    if not acoes:
        return {"status": "nao_encontrado", "motivo": "ações em circulação não encontradas na SEC"}
    dividendo = soma_12m_sec(fatos, "CommonStockDividendsPerShareDeclared", "USD/shares", hoje)
    return {
        "status": "ok", "acoes_total": acoes, "tipo_acao": "comum", "fator_adr": 1, "moeda_resultado": "USD",
        "fonte_oficial": "SEC EDGAR, XBRL companyfacts (10-Q/10-K)",
        "data_ultimo_balanco": lucro["data_fim"], "lucro_12m": lucro["valor_12m"],
        "dividendo_12m": dividendo["valor_12m"] if dividendo["status"] == "ok" else None,
        "dividendo_motivo": None if dividendo["status"] == "ok" else f"CommonStockDividendsPerShareDeclared: {dividendo['motivo']}",
        "trimestres": lucro["trimestres"],
    }


def _data_mais_recente_eua(ticker: str, hoje: dt.date, *, cabecalho=cabecalho_sec, buscar_cik=cik_do_ticker) -> str | None:
    """Só o fim do trimestre mais recente de NetIncomeLoss na SEC, sem recalcular o resto."""
    cab = cabecalho()
    if not cab:
        return None
    empresa = buscar_cik(ticker, cab)
    if not empresa:
        return None
    fatos = _get_sec(f"{SEC_DADOS}/api/xbrl/companyfacts/CIK{empresa[0]}.json", cab).json()
    r = soma_12m_sec(fatos, "NetIncomeLoss", "USD", hoje)
    return r.get("data_fim") if r.get("status") == "ok" else None


# ------------------------------------------------------------ fórmulas (fixas, não mude)
def _fmt(v: float | None, casas: int = 2) -> str:
    return "Sem dado" if v is None else f"{v:.{casas}f}".replace(".", ",")


def pl_medio_12m_fixo(fixos: dict, cotacoes_trimestrais: list[float] | None) -> float | None:
    """Média do P/L dos últimos 4 trimestres: cotação de fechamento do trimestre ÷ LPA daquele
    trimestre. None sem as 4 cotações trimestrais (cada uma precisa ser buscada à parte, ex. no
    histórico do Yahoo - só a cotação, nunca o lucro)."""
    acoes = fixos.get("acoes_total")
    trimestres = fixos.get("trimestres") or []
    if not acoes or len(trimestres) < 4 or not cotacoes_trimestrais or len(cotacoes_trimestrais) < 4:
        return None
    pls = []
    for t, fechamento in zip(trimestres[-4:], cotacoes_trimestrais[-4:]):
        lucro_tri = t.get("lucro", t.get("valor"))
        if lucro_tri is None or not fechamento:
            return None
        lpa_tri = lucro_tri / acoes
        if not lpa_tri:
            return None
        pls.append(fechamento / lpa_tri)
    return sum(pls) / len(pls)


def _contas(fixos: dict, lpa: float | None, pl: float | None, dy: float | None, cotacao: float,
           vpa: float | None, pvp: float | None, payout: float | None, roe: float | None) -> dict:
    """Texto da conta embaixo de cada indicador (CLAUDE.md / Issue #29 item 6; Issue #35: P/VP, Payout, ROE)."""
    acoes, lucro, dividendo = fixos.get("acoes_total"), fixos.get("lucro_12m"), fixos.get("dividendo_12m")
    patrimonio = fixos.get("patrimonio_liquido")
    fonte, data_bal = fixos.get("fonte_oficial", ""), fixos.get("data_ultimo_balanco", "")
    bi = lambda v: _fmt(v / 1e9, 2) if v is not None else "Sem dado"
    return {
        "acoes": f"Ações: {bi(acoes)} bi - Fonte: {fonte} ({data_bal})",
        "lpa": f"LPA: {bi(lucro)} / {bi(acoes)}" if lucro is not None and acoes else "LPA: Sem dado",
        "pl": f"P/L Atual: {_fmt(cotacao)} / {_fmt(lpa, 4)}" if lpa is not None else "P/L Atual: Sem dado",
        "dividendo": f"Dividendo Anual: {_fmt(dividendo, 4)}" if dividendo is not None else "Dividendo Anual: Sem dado",
        "dy": f"DY: {_fmt(dividendo, 4)} / {_fmt(cotacao)}" if dy is not None else "DY: Sem dado",
        "pvp": (f"P/VP: {_fmt(cotacao)} / ({bi(patrimonio)} bi / {bi(acoes)} bi)"
               if pvp is not None else "P/VP: Sem dado"),
        "payout": (f"Payout: {_fmt(dividendo, 4)} / {_fmt(lpa, 4)} = {_fmt(payout * 100, 1)}%"
                  if payout is not None else "Payout: Sem dado"),
        "roe": (f"ROE: {bi(lucro)} bi / {bi(patrimonio)} bi = {_fmt(roe * 100, 1)}%"
               if roe is not None else "ROE: Sem dado"),
    }


def calcular_indicadores(fixos: dict, cotacao: float, *, cotacoes_trimestrais: list[float] | None = None) -> dict:
    """As fórmulas fixas da Issue #29 (LPA, P/L, DY, P/L Médio 12m, ADR) + Issue #35 (P/VP, Payout,
    ROE), puras (sem rede).

    P/VP e ROE usam `patrimonio_liquido` como está (valor total do balanço, igual à Issue). Payout
    usa LPA no denominador, não `lucro_12m` bruto: `dividendo_12m` já é por ação (Issue #31), então
    dividir pelo lucro TOTAL daria uma % sem sentido (ordens de grandeza diferentes); dividendo por
    ação ÷ LPA é a mesma conta de dividendo total ÷ lucro total (ambos ÷ acoes_total se cancelam),
    só que com os dados que já temos - mesmo resultado, sem o passo extra. Decisão documentada no
    CLAUDE.md e no PR da Issue #35."""
    acoes, lucro, dividendo = fixos.get("acoes_total"), fixos.get("lucro_12m"), fixos.get("dividendo_12m")
    patrimonio = fixos.get("patrimonio_liquido")
    fator_adr = fixos.get("fator_adr") or 1
    lpa = lucro / acoes if acoes and lucro is not None else None
    pl = cotacao / lpa if lpa and cotacao else None
    dy = dividendo / cotacao if dividendo is not None and cotacao else None
    pl_medio = pl_medio_12m_fixo(fixos, cotacoes_trimestrais)
    vpa = patrimonio / acoes if acoes and patrimonio is not None else None
    pvp = cotacao / vpa if vpa and cotacao else None
    payout = dividendo / lpa if dividendo is not None and lpa else None
    roe = lucro / patrimonio if patrimonio and lucro is not None else None
    return {
        "cotacao": cotacao, "lpa": lpa, "pl": pl, "dy": dy, "plMedio12m": pl_medio,
        "lpaAdr": lpa * fator_adr if lpa is not None else None,
        "dividendoAdr": dividendo * fator_adr if dividendo is not None else None,
        "vpa": vpa, "pvp": pvp, "payout": payout, "roe": roe,
        "contas": _contas(fixos, lpa, pl, dy, cotacao, vpa, pvp, payout, roe),
    }


# ------------------------------------------------------------ cache sob demanda (ponto de entrada)
def _data_mais_recente(ticker: str, hoje: dt.date) -> str | None:
    return _data_mais_recente_br(ticker, hoje) if eh_br(ticker) else _data_mais_recente_eua(ticker, hoje)


def obter(ticker: str, hoje: dt.date, cotacao: float | None, *, cotacoes_trimestrais: list[float] | None = None,
         buscar_br=buscar_fixos_br, buscar_eua=buscar_fixos_eua,
         verificar_novo: bool = True, buscar_data_mais_recente=None, tabela: dict | None = None) -> dict:
    """Ponto de entrada único (lista sob demanda, CLAUDE.md):

    - ticker já em dados_fixos.json -> usa o salvo, só recalcula com a cotação do dia.
    - ticker novo -> busca 1x na fonte oficial; achou -> grava e calcula; não achou -> devolve
      {"status": "nao_encontrado", "mensagem": "Ticker não encontrado na fonte oficial."} e NÃO cria a entrada.
    """
    ch = chave(ticker)
    tab = _ler() if tabela is None else {k: dict(v) for k, v in tabela.items()}
    salvo = tab.get(ch)
    aviso = None
    if salvo is None:
        novo = (buscar_br if eh_br(ticker) else buscar_eua)(ticker, hoje)
        if novo.get("status") != "ok":
            return {"status": "nao_encontrado", "mensagem": MENSAGEM_NAO_ENCONTRADO, "motivo": novo.get("motivo"), "ticker": ch}
        salvo = {k: v for k, v in novo.items() if k != "status"}
        tab[ch] = salvo
        if tabela is None:
            _gravar(tab)
    elif verificar_novo:
        buscar_recente = buscar_data_mais_recente or (lambda: _data_mais_recente(ticker, hoje))
        try:
            recente = buscar_recente()
        except Exception as e:  # noqa: BLE001 - checagem best-effort; sem ela, só não mostra o aviso
            log.info("%s: não consegui checar balanço novo (%s)", ch, e.__class__.__name__)
            recente = None
        data_recente, data_salva = _data(recente), _data(salvo.get("data_ultimo_balanco"))
        if data_recente and data_salva and data_recente > data_salva:
            aviso = f"Balanço novo detectado, atualizar dados fixos de {ch}?"
    if cotacao is None:
        return {"status": "ok", "ticker": ch, **salvo, "avisoBalancoNovo": aviso}
    ind = calcular_indicadores(salvo, cotacao, cotacoes_trimestrais=cotacoes_trimestrais)
    return {"status": "ok", "ticker": ch, **salvo, **ind, "avisoBalancoNovo": aviso}
