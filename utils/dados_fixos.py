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
    documentos_cvm,
    fim_do_trimestre,
    ler_lucro_trimestre,
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


def extrair_acoes_br(texto: str) -> tuple[float | None, str]:
    """ON + PN + Units em circulação achados no texto (capa do ITR/DFP). None se nenhuma classe for
    encontrada. `detalhe` lista as classes achadas, para a conta aparecer na tela."""
    partes = []
    for nome, regex in (("ON", RE_ON), ("PN", RE_PN), ("Units", RE_UNITS)):
        m = regex.search(texto)
        if m:
            partes.append((nome, _inteiro_br(m.group(1))))
    if not partes:
        return None, ""
    total = sum(v for _, v in partes)
    return total, " + ".join(f"{n} {v:,.0f}".replace(",", ".") for n, v in partes)


def buscar_fixos_br(ticker: str, hoje: dt.date, *, buscar_cnpj=cnpj_do_ticker, buscar_docs=documentos_cvm,
                    ler_pdf=texto_do_pdf) -> dict:
    """Fonte oficial do Brasil: 1º PDF RI (release/ITR/DFP), documentos entregues à CVM (IPE).

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
    lidos: dict[str, dict] = {}
    acoes, acoes_detalhe, fonte_acoes = None, "", ""
    for doc in docs:
        data_doc = _data(doc["data"])
        if not data_doc:
            continue
        tri = trimestre_do_documento(data_doc)
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
        if tri not in lidos:
            relatorio = bool(RE_RELATORIO_DOC.search(f"{doc.get('categoria', '')} {doc.get('tipo', '')} {doc.get('assunto', '')}"))
            r = ler_lucro_trimestre(texto, tri, "Lucro Líquido", tabela_vence=relatorio)
            if r["valor"] is not None:
                lidos[tri] = {"tri": tri, "fim": f"{fim_do_trimestre(tri):%d/%m/%Y}", "lucro": r["valor"],
                             "data": _data_br(doc["data"]), "url": doc["link"]}
        ordem = sorted(lidos, key=fim_do_trimestre)
        if acoes and len(ordem) >= 4 and all(tri_anterior(b) == a for a, b in zip(ordem[-4:], ordem[-3:])):
            break
    if not acoes:
        return {"status": "nao_encontrado", "motivo": "número de ações (ON/PN/Units) não encontrado nos documentos da CVM"}
    ult = sorted(lidos.values(), key=lambda x: fim_do_trimestre(x["tri"]))[-4:]
    if len(ult) < 4 or any(tri_anterior(b["tri"]) != a["tri"] for a, b in zip(ult, ult[1:])):
        return {"status": "nao_encontrado", "motivo": "4 trimestres consecutivos de lucro líquido não encontrados na CVM"}
    return {
        "status": "ok", "acoes_total": acoes, "acoes_detalhe": acoes_detalhe,
        "tipo_acao": "ON+PN" if " + " in acoes_detalhe else ("ON" if "ON" in acoes_detalhe else acoes_detalhe),
        "fator_adr": 1, "moeda_resultado": "BRL",
        "fonte_oficial": f"PDF RI (CVM/IPE) - ações: {fonte_acoes}; lucro: release de resultados trimestral",
        "data_ultimo_balanco": ult[-1]["fim"], "lucro_12m": sum(x["lucro"] for x in ult),
        "dividendo_12m": None, "dividendo_motivo": "dividendos dos últimos 12 meses não encontrados nos documentos lidos",
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


def _contas(fixos: dict, lpa: float | None, pl: float | None, dy: float | None, cotacao: float) -> dict:
    """Texto da conta embaixo de cada indicador (CLAUDE.md / Issue #29, item 6)."""
    acoes, lucro, dividendo = fixos.get("acoes_total"), fixos.get("lucro_12m"), fixos.get("dividendo_12m")
    fonte, data_bal = fixos.get("fonte_oficial", ""), fixos.get("data_ultimo_balanco", "")
    bi = lambda v: _fmt(v / 1e9, 2) if v is not None else "Sem dado"
    return {
        "acoes": f"Ações: {bi(acoes)} bi - Fonte: {fonte} ({data_bal})",
        "lpa": f"LPA: {bi(lucro)} / {bi(acoes)}" if lucro is not None and acoes else "LPA: Sem dado",
        "pl": f"P/L Atual: {_fmt(cotacao)} / {_fmt(lpa, 4)}" if lpa is not None else "P/L Atual: Sem dado",
        "dividendo": f"Dividendo Anual: {_fmt(dividendo, 4)}" if dividendo is not None else "Dividendo Anual: Sem dado",
        "dy": f"DY: {_fmt(dividendo, 4)} / {_fmt(cotacao)}" if dy is not None else "DY: Sem dado",
    }


def calcular_indicadores(fixos: dict, cotacao: float, *, cotacoes_trimestrais: list[float] | None = None) -> dict:
    """As fórmulas fixas da Issue #29, puras (sem rede): LPA, P/L, DY, P/L Médio 12m e a versão ADR."""
    acoes, lucro, dividendo = fixos.get("acoes_total"), fixos.get("lucro_12m"), fixos.get("dividendo_12m")
    fator_adr = fixos.get("fator_adr") or 1
    lpa = lucro / acoes if acoes and lucro is not None else None
    pl = cotacao / lpa if lpa and cotacao else None
    dy = dividendo / cotacao if dividendo is not None and cotacao else None
    pl_medio = pl_medio_12m_fixo(fixos, cotacoes_trimestrais)
    return {
        "cotacao": cotacao, "lpa": lpa, "pl": pl, "dy": dy, "plMedio12m": pl_medio,
        "lpaAdr": lpa * fator_adr if lpa is not None else None,
        "dividendoAdr": dividendo * fator_adr if dividendo is not None else None,
        "contas": _contas(fixos, lpa, pl, dy, cotacao),
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
