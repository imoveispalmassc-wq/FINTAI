"""Busca automática de guidance oficial (projeção de lucro) das empresas da B3 e dos EUA.

Roda todo dia pelo GitHub Actions (.github/workflows/update-guidance.yml):

    python -m utils.fetch_guidance planejar --saida plano.json
    python -m utils.fetch_guidance aplicar plano.json --tipo commit
    python -m utils.fetch_guidance aplicar plano.json --tipo pr --resumo pr.md

Fluxo por ticker (lista em utils/guidance_tickers.json):
1. Acha o CNPJ pelo ticker no cadastro aberto da CVM (FCA, valores mobiliários).
2. Lista os documentos entregues à CVM (IPE: fatos relevantes, comunicados, resultados), do mais
   novo para o mais antigo. São os mesmos documentos que a B3 e o RI da empresa divulgam.
3. Lê o PDF e procura a faixa de lucro líquido projetada:
   a) primeiro por padrões de texto (grátis);
   b) só se os padrões acharem a faixa mas sem confiança, pede à API do Claude (precisa da
      variável ANTHROPIC_API_KEY, guardada nos Secrets do GitHub). O trecho devolvido tem de
      existir no documento, senão o resultado é descartado.
4. Decide como publicar:
   - "commit": ticker já aprovado antes, padrões de texto com confiança alta e variação de menos de 50%
     no LPA projetado;
   - "pr": primeira gravação do ticker, API do Claude, confiança baixa, documento com mais de 120 dias
     ou variação de 50% ou mais (mesmo com confiança alta);
   - nada muda quando não acha guidance ou não tem confiança: só registra no log.

O resultado vai para utils/guidance_auto.json, que utils/override.py lê. Um cadastro manual em
override.py sempre ganha do automático.

Ações dos EUA (ticker sem número, ex.: ADM, HSIC): SEC EDGAR. O robô lista os 8-K (e 6-K de empresas
estrangeiras) com o comunicado de resultados anexo (Exhibit 99.1, o mesmo press release da empresa) e
procura a faixa de LPA projetado ("adjusted EPS of $5.50 to $5.80") e o dividendo trimestral.
A SEC exige e-mail de contato no User-Agent: vem só da variável SEC_CONTACT_EMAIL (Secret do GitHub),
nunca do código. Sem ela, os tickers dos EUA ficam de fora com aviso no log.
"""
from __future__ import annotations

import argparse
import base64
import csv
import datetime as dt
import io
import json
import logging
import os
import re
import unicodedata
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ARQ_AUTO = RAIZ / "utils" / "guidance_auto.json"
ARQ_TICKERS = RAIZ / "utils" / "guidance_tickers.json"
ARQ_INICIAL = RAIZ / "utils" / "guidance_inicial.json"
ARQ_VISTOS = RAIZ / ".guidance_cache" / "vistos.json"   # persistido pelo cache do GitHub Actions

CVM = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC"
CABECALHO = {"User-Agent": "fintai-guidance/1.0 (+https://github.com/imoveispalmassc-wq/fintai)"}
LIMITE_MUDANCA = 0.50        # variação do LPA projetado de 50% ou mais vai para revisão
IDADE_MAXIMA_DIAS = 120      # documento mais velho que isso (mais de um trimestre) vai para revisão
MAX_DOCUMENTOS = 6           # documentos lidos por ticker, do mais novo para o mais antigo
MODELO = "claude-opus-5-5"

log = logging.getLogger("guidance")


# ------------------------------------------------------------ texto
def normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKC", texto or "").replace(" ", " ")
    return re.sub(r"\s+", " ", texto).strip()


def sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn").lower()


def numero_br(s: str) -> float:
    """'18,5' -> 18.5; '1.234,5' -> 1234.5; '18.5' -> 18.5; '1.234' -> 1234."""
    s = s.strip()
    if "," in s:
        return float(s.replace(".", "").replace(",", "."))
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        return float(s.replace(".", ""))
    return float(s)


def multiplicador(unidade: str | None) -> float | None:
    u = sem_acento(unidade or "")
    if u.startswith(("bilh", "bi")):
        return 1e9
    if u.startswith(("milh", "mi")):
        return 1e6
    return None


# ------------------------------------------------------------ extração por padrões de texto
@dataclass
class Extracao:
    lucro_min: float | None = None
    lucro_max: float | None = None
    payout: float | None = None
    ano: int | None = None
    trecho: str = ""
    confianca: str = "baixa"            # "alta" | "baixa"
    metodo: str = "padrões de texto"     # "padrões de texto" | "API do Claude"
    motivos: list[str] = field(default_factory=list)
    candidatos: int = 0                  # faixas de lucro distintas encontradas
    faixas: list = field(default_factory=list)   # todas as faixas (mín., máx.) achadas no documento


RE_LUCRO = re.compile(r"lucro\s+l[ií]quido(?:\s+(?:ajustado|recorrente|cont[áa]bil|gerencial))?", re.I)
UNID = r"(bilh[õo]es|bilh[ãa]o|bi\b|milh[õo]es|milh[ãa]o|mi\b)"
NUM = r"(\d{1,3}(?:\.\d{3})*(?:,\d{1,2})?|\d+(?:\.\d{1,2})?)"
RE_FAIXA = re.compile(
    rf"(?:R\$\s*)?{NUM}\s*{UNID}?\s*(?:a|e|at[ée]|-|–|—)\s*(?:R\$\s*)?{NUM}\s*{UNID}?", re.I)
RE_UNIDADE_SOLTA = re.compile(rf"R\$\s*{UNID}|\(\s*R\$\s*{UNID}\s*\)|em\s+{UNID}\s+de\s+reais", re.I)
RE_ANO = re.compile(r"(?:guidance|proje[cç](?:[õo]es|[ãa]o)|estimativas?|perspectivas?)[^.]{0,80}?\b(20\d{2})\b", re.I)
RE_PAYOUT = re.compile(
    r"payout[^%\d]{0,80}?(\d{1,3}(?:,\d+)?)\s*%(?:\s*(?:a|e|-|–)\s*(\d{1,3}(?:,\d+)?)\s*%)?", re.I)


def extrair_por_padroes(texto: str, ano_alvo: int) -> Extracao | None:
    """Faixa de lucro líquido projetada, ano e payout. None se o texto não traz faixa de lucro."""
    t = normalizar(texto)
    faixas: dict[tuple[float, float], str] = {}
    revisao = False
    for m in RE_LUCRO.finditer(t):
        janela = t[m.start(): m.start() + 260]
        antes = t[max(0, m.start() - 300): m.start()]

        def mult_de(f):
            mult = multiplicador(f.group(4) or f.group(2))
            if mult is None:                     # unidade de cabeçalho de tabela: "(R$ bilhões)"
                u = RE_UNIDADE_SOLTA.search(janela) or RE_UNIDADE_SOLTA.search(antes)
                mult = multiplicador(next((g for g in u.groups() if g), None)) if u else None
            return mult

        pos = 0
        achou = False
        while True:
            f = RE_FAIXA.search(janela, pos)
            if not f:
                break
            # depois da primeira faixa, só contam as faixas coladas a ela (mesma linha de tabela,
            # ex.: "18 a 22  9 a 11" = anterior e revisada); texto no meio encerra a menção
            if achou and janela[pos:f.start()].strip(" ;,/|()") != "":
                break
            mult = mult_de(f)
            pos = f.end()
            if mult is None:
                if achou:
                    break
                continue
            a, b = numero_br(f.group(1)) * mult, numero_br(f.group(3)) * mult
            if not (0 < a <= b <= a * 2):        # faixa de guidance: mínimo <= máximo, no máximo o dobro
                if achou:
                    break
                continue
            faixas.setdefault((a, b), janela[: f.end()].strip())
            achou = True
        if achou and re.search(r"anterior|revis|atualiza", antes[-160:] + janela, re.I):
            revisao = True
    if not faixas:
        return None

    ex = Extracao(candidatos=len(faixas), faixas=list(faixas))
    (ex.lucro_min, ex.lucro_max), ex.trecho = next(iter(faixas.items()))
    if len(faixas) > 1:
        ex.motivos.append(f"{len(faixas)} faixas de lucro diferentes no documento (ex.: anterior e revisada)")
    if revisao:
        ex.motivos.append("documento fala em projeção anterior ou revisada")

    anos = {int(a) for a in RE_ANO.findall(t)}
    if ano_alvo in anos:
        ex.ano = ano_alvo
    elif anos:
        ex.ano = max(anos)
        ex.motivos.append(f"projeção para {ex.ano}, não para {ano_alvo}")
    else:
        ex.motivos.append("ano da projeção não encontrado")

    payouts = set()
    for p in RE_PAYOUT.finditer(t):
        v1 = numero_br(p.group(1))
        v2 = numero_br(p.group(2)) if p.group(2) else v1
        payouts.add(round((v1 + v2) / 2 / 100, 4))
    payouts = {p for p in payouts if 0 < p <= 1}
    if len(payouts) == 1:
        ex.payout = payouts.pop()
    elif len(payouts) > 1:
        ex.motivos.append("mais de um payout no documento: payout não usado")

    ex.confianca = "alta" if len(faixas) == 1 and ex.ano == ano_alvo and not revisao else "baixa"
    return ex


# ------------------------------------------------------------ API do Claude (só quando os padrões falham)
ESQUEMA_CLAUDE = {
    "type": "object",
    "properties": {
        "tem_guidance_de_lucro": {"type": "boolean"},
        "ano": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
        "lucro_min_reais": {"anyOf": [{"type": "number"}, {"type": "null"}]},
        "lucro_max_reais": {"anyOf": [{"type": "number"}, {"type": "null"}]},
        "payout_fracao": {"anyOf": [{"type": "number"}, {"type": "null"}]},
        "trecho": {"type": "string"},
    },
    "required": ["tem_guidance_de_lucro", "ano", "lucro_min_reais", "lucro_max_reais", "payout_fracao", "trecho"],
    "additionalProperties": False,
}

INSTRUCAO_CLAUDE = """Você lê um documento oficial de uma empresa brasileira (fato relevante, comunicado ou \
release de resultados entregue à CVM) e extrai o guidance (projeção oficial) de LUCRO LÍQUIDO do ano {ano}.

Regras:
- Use só o que está escrito no documento. Não estime nem complete nada.
- Se houver projeção anterior e revisada, use a VIGENTE (a mais recente/revisada).
- lucro_min_reais e lucro_max_reais em reais, por extenso (R$ 9 bilhões = 9000000000).
  Se o guidance for um valor único, repita-o nos dois campos.
- payout_fracao: fração do lucro distribuída (30% = 0.30), só se o documento disser; senão null.
- trecho: copie EXATAMENTE, palavra por palavra, a frase ou linha de tabela de onde tirou a faixa de lucro.
- Se o documento não traz guidance de lucro líquido para {ano}, responda tem_guidance_de_lucro = false \
e os números como null."""


def _so_letras_numeros(texto: str) -> str:
    return re.sub(r"[^a-z0-9]", "", sem_acento(texto))


def _confere(a: float, b: float, texto: str, trecho: str, faixas_do_documento) -> str | None:
    """Como a faixa devolvida pela API foi conferida no documento; None se não foi.

    1. A faixa é uma das que os padrões de texto acharam no próprio documento (mais forte).
    2. O trecho existe no documento, ignorando espaços, acentos e separadores de tabela."""
    for x, y in faixas_do_documento or []:
        if abs(x - a) <= 0.005 * a and abs(y - b) <= 0.005 * b:
            return "faixa encontrada no documento pelos padrões de texto"
    pedaco = _so_letras_numeros(trecho)[:80]
    if len(pedaco) >= 20 and pedaco in _so_letras_numeros(texto):
        return "trecho encontrado no documento"
    return None


def extrair_com_claude(pdf: bytes, texto: str, ano_alvo: int, faixas_do_documento=()) -> Extracao | None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        log.info("  sem ANTHROPIC_API_KEY: leitura pela API do Claude desligada")
        return None
    import anthropic

    client = anthropic.Anthropic()
    conteudo = []
    if pdf and len(pdf) < 30 * 1024 * 1024:
        conteudo.append({"type": "document", "source": {
            "type": "base64", "media_type": "application/pdf", "data": base64.standard_b64encode(pdf).decode()}})
    else:
        conteudo.append({"type": "text", "text": texto[:400_000]})
    conteudo.append({"type": "text", "text": INSTRUCAO_CLAUDE.format(ano=ano_alvo)})
    try:
        resposta = client.beta.messages.create(
            model=MODELO, max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            output_config={"format": {"type": "json_schema", "schema": ESQUEMA_CLAUDE}},
            messages=[{"role": "user", "content": conteudo}],
        )
    except anthropic.APIStatusError as e:
        log.error("  API do Claude recusou a chamada (%s): %s", e.status_code, e.message)
        return None
    except anthropic.APIConnectionError:
        log.error("  API do Claude fora do alcance")
        return None
    if resposta.stop_reason in ("refusal", "max_tokens"):
        log.error("  API do Claude não concluiu a leitura (%s)", resposta.stop_reason)
        return None
    bruto = next((b.text for b in resposta.content if b.type == "text"), "")
    try:
        dados = json.loads(bruto)
    except json.JSONDecodeError:
        log.error("  resposta da API do Claude fora do formato")
        return None
    if not dados.get("tem_guidance_de_lucro"):
        log.info("  API do Claude: documento sem guidance de lucro para %s", ano_alvo)
        return None
    a, b, trecho = dados.get("lucro_min_reais"), dados.get("lucro_max_reais"), normalizar(dados.get("trecho", ""))
    if not (a and b and 0 < a <= b <= a * 2):
        log.error("  API do Claude devolveu faixa inválida: %s a %s", a, b)
        return None
    # a faixa tem de estar no documento: sem isso, o número pode ter sido inventado
    conferido = _confere(float(a), float(b), texto, trecho, faixas_do_documento)
    if not conferido:
        log.error("  API do Claude leu R$ %.1f a %.1f bi, mas a faixa não foi encontrada no documento: descartado",
                  a / 1e9, b / 1e9)
        return None
    log.info("  API do Claude leu R$ %.1f a %.1f bi (%s)", a / 1e9, b / 1e9, conferido)
    payout = dados.get("payout_fracao")
    return Extracao(lucro_min=float(a), lucro_max=float(b),
                    payout=float(payout) if payout is not None and 0 < payout <= 1 else None,
                    ano=dados.get("ano"), trecho=trecho[:400], confianca="baixa", metodo="API do Claude",
                    motivos=[f"lido pela API do Claude ({conferido}): precisa de revisão"], candidatos=1)


# ------------------------------------------------------------ CVM (dados abertos)
def _get(url: str, **kw):
    import requests

    r = requests.get(url, headers=CABECALHO, timeout=60, **kw)
    r.raise_for_status()
    return r


def _csv_do_zip(url: str, nome_contem: str) -> list[dict]:
    z = zipfile.ZipFile(io.BytesIO(_get(url).content))
    nome = next(n for n in z.namelist() if nome_contem in n)
    with z.open(nome) as f:
        linhas = csv.DictReader(io.TextIOWrapper(f, encoding="latin-1"), delimiter=";")
        return [{k.strip().lower(): (v or "").strip() for k, v in linha.items() if k} for linha in linhas]


def _campo(linha: dict, *pedacos: str) -> str:
    for chave, valor in linha.items():
        if all(p in chave for p in pedacos):
            return valor
    return ""


def cnpj_do_ticker(ticker: str, hoje: dt.date) -> tuple[str, str] | None:
    """CNPJ e nome da empresa pelo código de negociação (FCA da CVM, valores mobiliários)."""
    for ano in (hoje.year, hoje.year - 1):
        try:
            linhas = _csv_do_zip(f"{CVM}/FCA/DADOS/fca_cia_aberta_{ano}.zip", "valor_mobiliario")
        except Exception as e:  # noqa: BLE001 - arquivo do ano pode não existir ainda
            log.info("  cadastro FCA %s indisponível (%s)", ano, e.__class__.__name__)
            continue
        for linha in linhas:
            if _campo(linha, "codigo", "negociacao").upper() == ticker:
                return _campo(linha, "cnpj"), _campo(linha, "nome") or _campo(linha, "denom")
    return None


PALAVRAS_PROJECAO = re.compile(r"proje|guidance|estimativ|perspectiv", re.I)
PALAVRAS_RESULTADO = re.compile(r"resultado|desempenho|release", re.I)


def documentos_cvm(cnpj: str, hoje: dt.date) -> list[dict]:
    """Documentos IPE da empresa que podem trazer guidance, do mais novo para o mais antigo."""
    docs = []
    for ano in (hoje.year, hoje.year - 1):
        try:
            linhas = _csv_do_zip(f"{CVM}/IPE/DADOS/ipe_cia_aberta_{ano}.zip", "ipe_cia_aberta")
        except Exception as e:  # noqa: BLE001
            log.info("  documentos IPE %s indisponíveis (%s)", ano, e.__class__.__name__)
            continue
        for l in linhas:
            if re.sub(r"\D", "", _campo(l, "cnpj")) != re.sub(r"\D", "", cnpj):
                continue
            assunto = " ".join([_campo(l, "categoria"), _campo(l, "tipo"), _campo(l, "especie"), _campo(l, "assunto")])
            if not (PALAVRAS_PROJECAO.search(assunto) or PALAVRAS_RESULTADO.search(assunto)):
                continue
            docs.append({"data": _campo(l, "data", "entrega") or _campo(l, "data", "referencia"),
                         "categoria": _campo(l, "categoria"), "assunto": _campo(l, "assunto"),
                         "link": _campo(l, "link")})
    docs = [d for d in docs if d["link"].startswith("http")]
    return sorted(docs, key=lambda d: d["data"], reverse=True)


def texto_do_pdf(link: str) -> tuple[bytes, str]:
    from pypdf import PdfReader

    pdf = _get(link).content
    if not pdf.lstrip().startswith(b"%PDF"):
        # o RAD da CVM às vezes devolve uma página HTML com o arquivo dentro
        inicio = pdf.find(b"%PDF")
        b64 = re.search(rb"JVBERi0[A-Za-z0-9+/=\s]{100,}", pdf)
        if inicio >= 0:
            pdf = pdf[inicio:]
        elif b64:
            pdf = base64.b64decode(re.sub(rb"\s", b"", b64.group(0)))
        else:
            titulo = re.search(rb"<title>(.*?)</title>", pdf, re.I | re.S)
            raise ValueError(f"não é PDF ({(titulo.group(1).strip()[:80] if titulo else pdf[:60])!r})")
    leitor = PdfReader(io.BytesIO(pdf))
    return pdf, "\n".join((p.extract_text() or "") for p in leitor.pages)


def acoes_yahoo(ticker: str) -> float | None:
    import yfinance as yf

    try:
        info = yf.Ticker(f"{ticker}.SA").info or {}
        return float(info.get("sharesOutstanding") or info.get("impliedSharesOutstanding") or 0) or None
    except Exception:  # noqa: BLE001
        return None


# ------------------------------------------------------------ plano e aplicação
def _data_br(data: str) -> str:
    try:
        return dt.date.fromisoformat(data[:10]).strftime("%d/%m/%Y")
    except ValueError:
        return data


def _data(texto: str | None) -> dt.date | None:
    """'2026-11-11', '2026-11-11 10:00' ou '11/11/2026' -> date."""
    texto = (texto or "").strip()
    for formato, tam in (("%Y-%m-%d", 10), ("%d/%m/%Y", 10)):
        try:
            return dt.datetime.strptime(texto[:tam], formato).date()
        except ValueError:
            continue
    return None


def _lpa(o: dict) -> float | None:
    try:
        if "lpa_min" in o:
            return (float(o["lpa_min"]) + float(o["lpa_max"])) / 2
        return (float(o["lucro_min"]) + float(o["lucro_max"])) / 2 / float(o["acoes"])
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None


def planejar_ticker(ticker: str, hoje: dt.date, anterior: dict | None, vistos: set[str], *,
                    buscar_cnpj=cnpj_do_ticker, buscar_docs=documentos_cvm, ler_pdf=texto_do_pdf,
                    buscar_acoes=acoes_yahoo, ler_com_claude=extrair_com_claude) -> dict:
    """Decide o que fazer com um ticker. Não grava nada."""
    item = {"ticker": ticker, "acao": "nada", "motivo": "", "novo": None, "anterior": anterior}
    if not re.fullmatch(r"[A-Z]{4}\d{1,2}", ticker):
        return planejar_ticker_eua(ticker, hoje, anterior)
    empresa = buscar_cnpj(ticker, hoje)
    if not empresa:
        item.update(acao="erro", motivo="CNPJ não encontrado no cadastro da CVM")
        return item
    cnpj, nome = empresa
    ano = hoje.year
    for doc in buscar_docs(cnpj, hoje)[:MAX_DOCUMENTOS]:
        if anterior and anterior.get("documento") == doc["link"]:
            item["motivo"] = "guidance já atualizado com o documento mais recente"
            return item
        data_doc, data_ant = _data(doc["data"]), _data((anterior or {}).get("data"))
        if data_doc and data_ant and data_doc < data_ant:
            # documentos vêm do mais novo para o mais antigo: daqui para trás, tudo é anterior
            # ao guidance que já está no app (ex.: a faixa de maio depois da revisão de novembro)
            item["motivo"] = f"documento de {_data_br(doc['data'])} é mais antigo que o guidance atual ({anterior['data']}): descartado"
            return item
        try:
            pdf, texto = ler_pdf(doc["link"])
        except Exception as e:  # noqa: BLE001
            log.info("  não abriu documento de %s (%s: %s)", _data_br(doc["data"]), e.__class__.__name__, e)
            continue
        ex = extrair_por_padroes(texto, ano)
        if ex is None:
            continue                                   # documento sem faixa de lucro: tenta o anterior
        # este é o documento mais novo com faixa de lucro: nunca volta para um mais antigo
        if ex.confianca != "alta":
            if doc["link"] in vistos:
                item["motivo"] = "documento já tentado sem confiança; aguardando documento novo"
                return item
            vistos.add(doc["link"])
            ex = ler_com_claude(pdf, texto, ano, ex.faixas) or ex
            if ex.metodo != "API do Claude":
                item.update(acao="erro", motivo="faixa de lucro encontrada sem confiança: " + "; ".join(ex.motivos))
                return item
        acoes = buscar_acoes(ticker)
        if not acoes:
            item.update(acao="erro", motivo="número de ações indisponível no Yahoo Finance")
            return item
        novo = {"lucro_min": ex.lucro_min, "lucro_max": ex.lucro_max, "acoes": acoes, "payout": ex.payout,
                "fonte": f"{nome}, {doc['categoria'] or 'documento'} de {_data_br(doc['data'])} (CVM)",
                "data": _data_br(doc["data"]), "url": doc["link"], "documento": doc["link"],
                "ano": ex.ano, "metodo": ex.metodo, "trecho": ex.trecho[:400], "acoes_fonte": "Yahoo Finance"}
        if anterior and all(anterior.get(k) == novo[k] for k in ("lucro_min", "lucro_max", "payout", "ano")):
            item["motivo"] = "mesma faixa do guidance atual"
            return item
        lpa_novo, lpa_ant = _lpa(novo), _lpa(anterior or {})
        # arredonda para o corte de exatamente 50% (ex.: 18-22 -> 9-11) não escapar por erro de ponto flutuante
        mudou_muito = bool(lpa_ant and lpa_novo and round(abs(lpa_novo / lpa_ant - 1), 6) >= LIMITE_MUDANCA)
        motivos = list(ex.motivos)
        primeira = not anterior        # ticker ainda sem guidance aprovado: a primeira gravação sempre passa por você
        if primeira:
            motivos.append("primeira gravação deste ticker: precisa da sua aprovação")
        idade = (hoje - data_doc).days if data_doc else None
        velho = idade is None or idade > IDADE_MAXIMA_DIAS
        if velho:
            motivos.append(f"documento de {_data_br(doc['data'])}, com mais de {IDADE_MAXIMA_DIAS} dias: "
                           "pode existir guidance mais novo que o robô não leu")
        if mudou_muito:
            motivos.append(f"LPA projetado mudou {abs(lpa_novo / lpa_ant - 1):.0%} (revisão a partir de {LIMITE_MUDANCA:.0%})")
        revisar = primeira or ex.metodo == "API do Claude" or ex.confianca != "alta" or mudou_muito or velho
        item.update(acao="pr" if revisar else "commit", novo=novo,
                    motivo="; ".join(motivos) or "padrões de texto, confiança alta")
        return item
    item["motivo"] = "nenhum documento recente com guidance de lucro"
    return item


# ------------------------------------------------------------ EUA: SEC EDGAR (8-K / 6-K + press release)
SEC_ARQUIVOS = "https://www.sec.gov"
SEC_DADOS = "https://data.sec.gov"
FORMS_SEC = ("8-K", "6-K")


def cabecalho_sec() -> dict | None:
    """User-Agent exigido pela SEC, com o e-mail do Secret SEC_CONTACT_EMAIL. None se não houver."""
    email = (os.environ.get("SEC_CONTACT_EMAIL") or "").strip()
    if not email or "@" not in email:
        return None
    return {"User-Agent": f"fintai/1.0 (contato: {email})", "Accept-Encoding": "gzip, deflate"}


def _get_sec(url: str, cab: dict):
    import requests

    r = requests.get(url, headers=cab, timeout=60)
    r.raise_for_status()
    return r


def cik_do_ticker(ticker: str, cab: dict) -> tuple[str, str] | None:
    """CIK (10 dígitos) e nome da empresa pelo ticker (lista oficial da SEC)."""
    dados = _get_sec(f"{SEC_ARQUIVOS}/files/company_tickers.json", cab).json()
    for linha in dados.values():
        if str(linha.get("ticker", "")).upper() == ticker.upper():
            return f"{int(linha['cik_str']):010d}", str(linha.get("title", ticker))
    return None


def documentos_sec(cik: str, cab: dict) -> list[dict]:
    """8-K/6-K mais recentes com o anexo de comunicado (Exhibit 99.x), do mais novo para o mais antigo."""
    sub = _get_sec(f"{SEC_DADOS}/submissions/CIK{cik}.json", cab).json()
    rec = sub.get("filings", {}).get("recent", {})
    docs = []
    for form, data, acc, itens in zip(rec.get("form", []), rec.get("filingDate", []),
                                      rec.get("accessionNumber", []), rec.get("items", [""] * len(rec.get("form", [])))):
        if form not in FORMS_SEC:
            continue
        # 8-K: só resultados (2.02) ou comunicados (7.01/8.01); 6-K não tem itens
        if form == "8-K" and itens and not any(x in itens for x in ("2.02", "7.01", "8.01")):
            continue
        docs.append({"form": form, "data": data, "acc": acc, "cik": cik})
        if len(docs) >= MAX_DOCUMENTOS:
            break
    return docs


def anexo_sec(doc: dict, cab: dict) -> tuple[str, str] | None:
    """Link e texto do Exhibit 99.1 (press release) de um 8-K/6-K."""
    pasta = f"{SEC_ARQUIVOS}/Archives/edgar/data/{int(doc['cik'])}/{doc['acc'].replace('-', '')}"
    itens = _get_sec(f"{pasta}/index.json", cab).json().get("directory", {}).get("item", [])
    nomes = [i["name"] for i in itens if i.get("name", "").lower().endswith((".htm", ".html", ".txt"))]
    alvo = next((n for n in nomes if re.search(r"ex[-_]?99[-_.]?0?1|ex991|exhibit991|dex991", n, re.I)), None) \
        or next((n for n in nomes if re.search(r"ex[-_]?99|exhibit99", n, re.I)), None)
    if not alvo:
        return None
    html = _get_sec(f"{pasta}/{alvo}", cab).text
    return f"{pasta}/{alvo}", texto_de_html(html)


def texto_de_html(html: str) -> str:
    import html as h

    t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", h.unescape(t)).strip()


# "adjusted EPS of approximately $5.50 to $5.80", "non-GAAP diluted EPS ... $5.42 to $5.48",
# "adjusted EPS of between $6.15 and $6.35"
RE_EPS_FAIXA = re.compile(
    r"((?:adjusted|non-gaap)[^.$]{0,60}?\b(?:eps|earnings per (?:diluted )?share)\b[^.$]{0,80}?)"
    r"\$\s?(\d{1,3}\.\d{2})\s*(?:to|and|-|–)\s*\$\s?(\d{1,3}\.\d{2})", re.I)
RE_ANO_EUA = re.compile(r"\b(fiscal(?:\s+year)?\s+|fy\s?|full[- ]year\s+|year\s+)?(20\d{2})\b", re.I)
RE_DIV_TRI = re.compile(r"quarterly (?:cash )?dividend[^.$]{0,120}?\$\s?(\d{1,2}\.\d{2,4})\s*per (?:common )?share", re.I)
RE_CONTEXTO_GUIDANCE = re.compile(r"guidance|outlook|expects?|forecast|range", re.I)
# faixa nova x faixa antiga quando o comunicado traz as duas (ex.: ADM 03/11/2026)
RE_FAIXA_NOVA = re.compile(r"\bupdated\b|\brevised\b|\bnow (?:expects?|anticipates?|sees|projects?)\b|"
                           r"outlook (?:is )?updated|\braising\b|\braised\b|\blowering\b|\blowered\b", re.I)
RE_FAIXA_ANTIGA = re.compile(r"\bpreviously\b|\bprevious\b|\bprior (?:outlook|guidance|range|expectation)s?\b|"
                             r"\bprior\b|\bearlier\b", re.I)


def _contexto_da_faixa(texto: str, inicio: int) -> str:
    """Trecho da mesma frase antes da faixa (até 160 caracteres), para ver se ela é a nova ou a antiga."""
    antes = texto[max(0, inicio - 160): inicio]
    # corta no fim da frase anterior (". " seguido de maiúscula), em "; " ou na abertura de parêntese
    cortes = [m.end() for m in re.finditer(r"\.\s+(?=[A-Z])|;\s|\(", antes)]
    return antes[cortes[-1]:] if cortes else antes


def extrair_eps_eua(texto: str, ano_minimo: int) -> dict | None:
    """Faixa de LPA projetado num comunicado dos EUA. None se não houver nenhuma faixa.

    Confiança alta: uma única faixa distinta, com palavra de projeção por perto e ano >= ano_minimo."""
    achados = []
    for m in RE_EPS_FAIXA.finditer(texto):
        a, b = float(m.group(2)), float(m.group(3))
        if not 0 < a <= b < 1000:
            continue
        janela = texto[max(0, m.start() - 250): m.end() + 120]
        anos = [(bool(x.group(1)), int(x.group(2))) for x in RE_ANO_EUA.finditer(janela)]
        anos_ok = [(f, y) for f, y in anos if ano_minimo <= y <= ano_minimo + 2]
        fiscal, ano = max(anos_ok, key=lambda x: x[1]) if anos_ok else (False, None)
        frase = _contexto_da_faixa(texto, m.start()) + m.group(1)
        achados.append({"lpa_min": a, "lpa_max": b, "ano": ano, "fiscal": fiscal,
                        "contexto": bool(RE_CONTEXTO_GUIDANCE.search(janela)),
                        "nova": bool(RE_FAIXA_NOVA.search(frase)), "antiga": bool(RE_FAIXA_ANTIGA.search(frase)),
                        "trecho": texto[max(0, m.start() - 120): m.end() + 40].strip()})
    if not achados:
        return None
    distintos = {(x["lpa_min"], x["lpa_max"]) for x in achados if x["ano"]}
    melhor = next((x for x in achados if x["ano"] and x["contexto"]), achados[0])
    escolha = ""
    if len(distintos) > 1:
        # duas ou mais faixas: ignora as marcadas como antigas (previously, prior...) e, se ainda
        # sobrar mais de uma, fica com as marcadas como novas (updated, now expects, raising...)
        restantes = [x for x in achados if x["ano"] and not x["antiga"]]
        if len({(x["lpa_min"], x["lpa_max"]) for x in restantes}) > 1:
            restantes = [x for x in restantes if x["nova"]]
        faixas_restantes = {(x["lpa_min"], x["lpa_max"]) for x in restantes}
        if len(faixas_restantes) == 1:
            melhor = next(x for x in restantes)
            ignoradas = sorted(distintos - faixas_restantes)
            escolha = "faixa nova escolhida; ignorada(s): " + ", ".join(f"{a:.2f} a {b:.2f}" for a, b in ignoradas)
            distintos = faixas_restantes
    motivos = []
    if not melhor["ano"]:
        motivos.append(f"faixa de LPA sem ano {ano_minimo} ou seguinte por perto")
    if not melhor["contexto"]:
        motivos.append("faixa sem palavra de projeção (guidance/outlook/expects) por perto")
    if len(distintos) > 1:
        # tabela "anterior x atual" ou várias métricas: pode ser o guidance velho
        motivos.append(f"{len(distintos)} faixas de LPA diferentes no documento")
    div = {round(float(x), 4) for x in RE_DIV_TRI.findall(texto)}
    periodo = (f"FY{melhor['ano']}" if melhor["fiscal"] and "fiscal" in melhor["trecho"].lower() else str(melhor["ano"] or ""))
    return {**melhor, "periodo": periodo, "confianca": "baixa" if motivos else "alta", "motivos": motivos, "escolha": escolha,
            "dividendo": round(div.pop() * 4, 4) if len(div) == 1 else None, "faixas": sorted(distintos)}


def planejar_ticker_eua(ticker: str, hoje: dt.date, anterior: dict | None, *,
                        cabecalho=cabecalho_sec, buscar_cik=cik_do_ticker, buscar_docs=documentos_sec,
                        ler_anexo=anexo_sec) -> dict:
    """Mesmo critério do Brasil, com documentos da SEC. Não grava nada."""
    item = {"ticker": ticker, "acao": "nada", "motivo": "", "novo": None, "anterior": anterior}
    cab = cabecalho()
    if not cab:
        item.update(acao="erro", motivo="sem SEC_CONTACT_EMAIL (Secret do GitHub): a SEC exige e-mail de contato")
        return item
    empresa = buscar_cik(ticker, cab)
    if not empresa:
        item.update(acao="erro", motivo="ticker não encontrado na lista da SEC")
        return item
    cik, nome = empresa
    for doc in buscar_docs(cik, cab):
        data_doc, data_ant = _data(doc["data"]), _data((anterior or {}).get("data"))
        if data_doc and data_ant and data_doc < data_ant:
            item["motivo"] = f"documento de {_data_br(doc['data'])} é mais antigo que o guidance atual ({anterior['data']}): descartado"
            return item
        try:
            anexo = ler_anexo(doc, cab)
        except Exception as e:  # noqa: BLE001
            log.info("  não abriu %s de %s (%s)", doc["form"], _data_br(doc["data"]), e.__class__.__name__)
            continue
        if not anexo:
            continue
        link, texto = anexo
        if anterior and anterior.get("documento") == link:
            item["motivo"] = "guidance já atualizado com o documento mais recente"
            return item
        ex = extrair_eps_eua(texto, hoje.year)
        if ex is None:
            continue                                   # comunicado sem faixa de LPA: tenta o anterior
        if ex["confianca"] != "alta":
            item.update(acao="erro", motivo="faixa de LPA encontrada sem confiança: " + "; ".join(ex["motivos"]))
            return item
        novo = {"lpa_min": ex["lpa_min"], "lpa_max": ex["lpa_max"], "periodo": ex["periodo"],
                "lucro_tipo": "LPA ajustado", "fonte": f"{nome}, Form {doc['form']} Exhibit 99.1 de {_data_br(doc['data'])} (SEC)",
                "data": _data_br(doc["data"]), "url": link, "documento": link, "ano": ex["ano"],
                "metodo": "padrões de texto (SEC)", "trecho": ex["trecho"][:400]}
        if ex["dividendo"]:
            novo["dividendo"] = ex["dividendo"]
        if anterior and all(anterior.get(k) == novo.get(k) for k in ("lpa_min", "lpa_max", "dividendo", "ano")):
            item["motivo"] = "mesma faixa do guidance atual"
            return item
        lpa_novo, lpa_ant = _lpa(novo), _lpa(anterior or {})
        mudou_muito = bool(lpa_ant and lpa_novo and round(abs(lpa_novo / lpa_ant - 1), 6) >= LIMITE_MUDANCA)
        motivos = []
        if not anterior:
            motivos.append("primeira gravação deste ticker: precisa da sua aprovação")
        idade = (hoje - data_doc).days if data_doc else None
        if idade is None or idade > IDADE_MAXIMA_DIAS:
            motivos.append(f"documento de {_data_br(doc['data'])}, com mais de {IDADE_MAXIMA_DIAS} dias")
        if mudou_muito:
            motivos.append(f"LPA projetado mudou {abs(lpa_novo / lpa_ant - 1):.0%} (revisão a partir de {LIMITE_MUDANCA:.0%})")
        if ex.get("escolha"):
            novo["escolha"] = ex["escolha"]
        item.update(acao="pr" if motivos else "commit", novo=novo,
                    motivo="; ".join(motivos + ([ex["escolha"]] if ex.get("escolha") else [])) or "padrões de texto, confiança alta")
        return item
    item["motivo"] = "nenhum 8-K/6-K recente com faixa de LPA projetado"
    return item


# ------------------------------------------------------------ projeção do início do ano (congelada)
def _janela_inicial(ano: str) -> tuple[dt.date, dt.date, int]:
    """Período em que sai o primeiro guidance do ano: release do 4T do ano anterior (jan-abr) e o 10-K.
    Ano fiscal (FY2027): o ano fiscal pode começar no meio do ano anterior, então a janela começa em julho."""
    fiscal = ano.upper().startswith("FY")
    n = int(re.sub(r"\D", "", ano))
    inicio = dt.date(n - 1, 7, 1) if fiscal else dt.date(n, 1, 1)
    return inicio, dt.date(n, 4, 30), n


def documentos_sec_periodo(cik: str, cab: dict, inicio: dt.date, fim: dt.date) -> list[dict]:
    """8-K de resultado (2.02), 6-K e 10-K entre as datas, do MAIS ANTIGO para o mais novo."""
    sub = _get_sec(f"{SEC_DADOS}/submissions/CIK{cik}.json", cab).json()
    rec = sub.get("filings", {}).get("recent", {})
    n = len(rec.get("form", []))
    docs = []
    for i in range(n):
        form, data = rec["form"][i], rec["filingDate"][i]
        itens = (rec.get("items") or [""] * n)[i]
        d = _data(data)
        if not d or not inicio <= d <= fim:
            continue
        if form == "8-K" and "2.02" not in (itens or ""):
            continue
        if form not in ("8-K", "6-K", "10-K"):
            continue
        docs.append({"form": form, "data": data, "acc": rec["accessionNumber"][i], "cik": cik,
                     "principal": (rec.get("primaryDocument") or [""] * n)[i]})
    return sorted(docs, key=lambda x: x["data"])


def texto_sec(doc: dict, cab: dict) -> tuple[str, str] | None:
    """8-K/6-K: o press release (Exhibit 99.1). 10-K: o documento principal."""
    if doc["form"] == "10-K" and doc.get("principal"):
        url = f"{SEC_ARQUIVOS}/Archives/edgar/data/{int(doc['cik'])}/{doc['acc'].replace('-', '')}/{doc['principal']}"
        return url, texto_de_html(_get_sec(url, cab).text)
    return anexo_sec(doc, cab)


def buscar_inicial_eua(ticker: str, ano: str, *, cabecalho=cabecalho_sec, buscar_cik=cik_do_ticker,
                       buscar_docs=documentos_sec_periodo, ler=texto_sec) -> tuple[dict | None, str]:
    """Primeiro guidance de LPA para o ano (`2026` ou `FY2027`). Devolve (novo, motivo)."""
    cab = cabecalho()
    if not cab:
        return None, "sem SEC_CONTACT_EMAIL"
    empresa = buscar_cik(ticker, cab)
    if not empresa:
        return None, "ticker não encontrado na SEC"
    cik, nome = empresa
    inicio, fim, n = _janela_inicial(ano)
    for doc in buscar_docs(cik, cab, inicio, fim):
        try:
            lido = ler(doc, cab)
        except Exception as e:  # noqa: BLE001
            log.info("  inicial: não abriu %s de %s (%s)", doc["form"], _data_br(doc["data"]), e.__class__.__name__)
            continue
        if not lido:
            continue
        link, texto = lido
        ex = extrair_eps_eua(texto, n)
        if not ex or ex["ano"] != n:
            continue
        if ex["confianca"] != "alta":
            return None, "projeção inicial encontrada sem confiança: " + "; ".join(ex["motivos"])
        return ({"lpa_min": ex["lpa_min"], "lpa_max": ex["lpa_max"], "lucro_tipo": "LPA ajustado",
                 "fonte": f"{nome}, Form {doc['form']}{' Exhibit 99.1' if doc['form'] != '10-K' else ''} de {_data_br(doc['data'])} (SEC)",
                 "data": _data_br(doc["data"]), "url": link, "metodo": "robô (primeiro documento do ano)",
                 "trecho": ex["trecho"][:400]}, "")
    return None, "sem projeção inicial encontrada"


def buscar_inicial_br(ticker: str, ano: str, *, buscar_cnpj=cnpj_do_ticker, buscar_docs=documentos_cvm,
                      ler_pdf=texto_do_pdf, buscar_acoes=acoes_yahoo) -> tuple[dict | None, str]:
    """Primeiro guidance de lucro do ano nos documentos da CVM (jan a abr). Só com confiança alta."""
    n = int(re.sub(r"\D", "", ano))
    empresa = buscar_cnpj(ticker, dt.date(n, 12, 31))
    if not empresa:
        return None, "CNPJ não encontrado na CVM"
    cnpj, nome = empresa
    docs = [d for d in buscar_docs(cnpj, dt.date(n, 12, 31))
            if (x := _data(d["data"])) and dt.date(n, 1, 1) <= x <= dt.date(n, 4, 30)]
    for doc in sorted(docs, key=lambda d: d["data"]):
        try:
            _, texto = ler_pdf(doc["link"])
        except Exception:  # noqa: BLE001
            continue
        ex = extrair_por_padroes(texto, n)
        if ex is None or ex.ano != n:
            continue
        if ex.confianca != "alta":
            return None, "projeção inicial encontrada sem confiança: " + "; ".join(ex.motivos)
        acoes = buscar_acoes(ticker)
        if not acoes:
            return None, "número de ações indisponível"
        return ({"lucro_min": ex.lucro_min, "lucro_max": ex.lucro_max, "acoes": acoes,
                 "fonte": f"{nome}, {doc['categoria'] or 'documento'} de {_data_br(doc['data'])} (CVM)",
                 "data": _data_br(doc["data"]), "url": doc["link"], "metodo": "robô (primeiro documento do ano)",
                 "trecho": ex.trecho[:400]}, "")
    return None, "sem projeção inicial encontrada"


def ano_alvo(ticker: str, hoje: dt.date) -> str:
    """Ano da projeção: o período do guidance atual (ex.: FY2027) ou o ano corrente."""
    from utils.override import tabela
    return str((tabela().get(ticker) or {}).get("periodo") or hoje.year)


def planejar_inicial(ticker: str, hoje: dt.date, iniciais: dict) -> dict | None:
    """Busca a projeção inicial só se ainda não houver uma gravada (congelada)."""
    from utils.override import _tem_projecao
    ano = ano_alvo(ticker, hoje)
    if _tem_projecao((iniciais.get(ticker) or {}).get(ano)):
        return None                                      # já travada: nunca busca de novo
    br = bool(re.fullmatch(r"[A-Z]{4}\d{1,2}", ticker))
    novo, motivo = (buscar_inicial_br if br else buscar_inicial_eua)(ticker, ano)
    return {"ano": ano, "novo": novo, "motivo": motivo}


def _ler_json(caminho: Path, padrao):
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return padrao


def planejar(hoje: dt.date | None = None) -> list[dict]:
    hoje = hoje or dt.date.today()
    tickers = [t.strip().upper() for t in _ler_json(ARQ_TICKERS, [])]
    auto = _ler_json(ARQ_AUTO, {})
    vistos_por_ticker = _ler_json(ARQ_VISTOS, {})
    iniciais = _ler_json(ARQ_INICIAL, {})
    plano = []
    for t in tickers:
        log.info("%s", t)
        vistos = set(vistos_por_ticker.get(t, []))
        try:
            item = planejar_ticker(t, hoje, auto.get(t), vistos)
        except Exception as e:  # noqa: BLE001 - um ticker com erro não derruba os outros
            item = {"ticker": t, "acao": "erro", "motivo": f"{e.__class__.__name__}: {e}", "novo": None, "anterior": auto.get(t)}
        try:
            ini = planejar_inicial(t, hoje, iniciais)
        except Exception as e:  # noqa: BLE001
            ini = {"ano": ano_alvo(t, hoje), "novo": None, "motivo": f"{e.__class__.__name__}: {e}"}
        if ini:
            item["inicial"] = ini
            log.info("  projeção inicial %s: %s", ini["ano"], "achada" if ini["novo"] else ini["motivo"])
        vistos_por_ticker[t] = sorted(vistos)[-50:]
        nivel = logging.ERROR if item["acao"] == "erro" else logging.INFO
        log.log(nivel, "  -> %s: %s", item["acao"], item["motivo"])
        if item["acao"] == "erro" and os.environ.get("GITHUB_ACTIONS"):
            # aparece como aviso amarelo no resumo da execução, mesmo com o robô terminando "verde"
            print(f"::warning title=Guidance {t} não gravado::{item['motivo']}", flush=True)
        plano.append(item)
    ARQ_VISTOS.parent.mkdir(exist_ok=True)
    ARQ_VISTOS.write_text(json.dumps(vistos_por_ticker, ensure_ascii=False, indent=2), encoding="utf-8")
    return plano


def aplicar(plano: list[dict], tipo: str) -> list[dict]:
    """Grava em guidance_auto.json só os itens do tipo pedido ("commit" ou "pr")."""
    auto = _ler_json(ARQ_AUTO, {})
    aplicados = [i for i in plano if i["acao"] == tipo and i["novo"]]
    for i in aplicados:
        auto[i["ticker"]] = i["novo"]
    if aplicados:
        ARQ_AUTO.write_text(json.dumps(dict(sorted(auto.items())), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if tipo == "commit":
        aplicar_iniciais(plano)
    return aplicados


def aplicar_iniciais(plano: list[dict]) -> int:
    """Grava as projeções iniciais achadas (ou o aviso de que não achou). Nunca sobrescreve uma já gravada."""
    from utils.override import gravar_inicial
    tab, n = _ler_json(ARQ_INICIAL, {}), 0
    for i in plano:
        ini = i.get("inicial")
        if not ini:
            continue
        tab, gravou = gravar_inicial(tab, i["ticker"], ini["ano"], ini["novo"])
        n += gravou
    if n:
        ARQ_INICIAL.write_text(json.dumps(dict(sorted(tab.items())), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return n


def resumo_pr(itens: list[dict]) -> str:
    def bi(v):
        return f"R$ {v / 1e9:,.1f} bi".replace(",", "X").replace(".", ",").replace("X", ".")

    linhas = ["Guidance encontrado automaticamente que precisa de revisão antes de ir para o app.", ""]
    for i in itens:
        n, a = i["novo"], i.get("anterior") or {}
        payout = "—" if n.get("payout") is None else f"{n['payout']:.0%}"
        novo_txt = (f"LPA de {n['lpa_min']:.2f} a {n['lpa_max']:.2f} ({n.get('periodo') or n.get('ano')})"
                    + (f", dividendo anual {n['dividendo']:.2f}" if n.get("dividendo") else "")) if "lpa_min" in n \
            else f"lucro de {bi(n['lucro_min'])} a {bi(n['lucro_max'])} ({n.get('ano')}), payout {payout}"
        linhas += [f"## {i['ticker']}", "",
                   f"- **Novo:** {novo_txt}, LPA projetado {_lpa(n):.2f}",
                   f"- **Anterior:** " + (f"LPA {_lpa(a):.2f}" if _lpa(a) else "nenhum"),
                   f"- **Por que revisar:** {i['motivo']}",
                   f"- **Método:** {n['metodo']}",
                   f"- **Fonte:** [{n['fonte']}]({n['url']})",
                   f"- **Trecho do documento:** \"{n['trecho']}\"", ""]
    linhas.append("Confira o trecho no documento original antes de aprovar. Se estiver errado, feche o PR sem juntar.")
    return "\n".join(linhas)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    pp = sub.add_parser("planejar")
    pp.add_argument("--saida", default="plano.json")
    pa = sub.add_parser("aplicar")
    pa.add_argument("plano")
    pa.add_argument("--tipo", choices=["commit", "pr"], required=True)
    pa.add_argument("--resumo")
    args = p.parse_args(argv)
    if args.cmd == "planejar":
        plano = planejar()
        Path(args.saida).write_text(json.dumps(plano, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("plano: %s", ", ".join(f"{i['ticker']}={i['acao']}" for i in plano) or "nenhum ticker")
        return 0
    plano = json.loads(Path(args.plano).read_text(encoding="utf-8"))
    aplicados = aplicar(plano, args.tipo)
    log.info("%s: %d ticker(s) gravado(s)", args.tipo, len(aplicados))
    if args.resumo and aplicados:
        Path(args.resumo).write_text(resumo_pr(aplicados), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
