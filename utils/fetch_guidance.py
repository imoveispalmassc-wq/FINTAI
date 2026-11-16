"""Busca automática de guidance oficial (projeção de lucro) das empresas da B3.

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
   - "commit": padrões de texto com confiança alta e variação de até 50% no LPA projetado;
   - "pr": veio da API do Claude, confiança baixa ou variação maior que 50%;
   - nada muda quando não acha guidance ou não tem confiança: só registra no log.

O resultado vai para utils/guidance_auto.json, que utils/override.py lê. Um cadastro manual em
override.py sempre ganha do automático.

Ações dos EUA ficam desligadas por enquanto (a SEC exige e-mail de contato no robô).
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
ARQ_VISTOS = RAIZ / ".guidance_cache" / "vistos.json"   # persistido pelo cache do GitHub Actions

CVM = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC"
CABECALHO = {"User-Agent": "fintai-guidance/1.0 (+https://github.com/imoveispalmassc-wq/fintai)"}
LIMITE_MUDANCA = 0.50        # variação do LPA projetado acima disso vai para revisão
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
            # ex.: "22 a 26  18 a 22" = anterior e revisada); texto no meio encerra a menção
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

    ex = Extracao(candidatos=len(faixas))
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
- lucro_min_reais e lucro_max_reais em reais, por extenso (R$ 18 bilhões = 18000000000).
  Se o guidance for um valor único, repita-o nos dois campos.
- payout_fracao: fração do lucro distribuída (30% = 0.30), só se o documento disser; senão null.
- trecho: copie EXATAMENTE, palavra por palavra, a frase ou linha de tabela de onde tirou a faixa de lucro.
- Se o documento não traz guidance de lucro líquido para {ano}, responda tem_guidance_de_lucro = false \
e os números como null."""


def extrair_com_claude(pdf: bytes, texto: str, ano_alvo: int) -> Extracao | None:
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
    # o trecho tem de existir no documento: sem isso, o número pode ter sido inventado
    if not trecho or sem_acento(trecho)[:120] not in sem_acento(normalizar(texto)):
        log.error("  trecho devolvido pela API do Claude não foi encontrado no documento: descartado")
        return None
    payout = dados.get("payout_fracao")
    return Extracao(lucro_min=float(a), lucro_max=float(b),
                    payout=float(payout) if payout is not None and 0 < payout <= 1 else None,
                    ano=dados.get("ano"), trecho=trecho[:400], confianca="baixa", metodo="API do Claude",
                    motivos=["lido pela API do Claude: precisa de revisão"], candidatos=1)


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


def _lpa(o: dict) -> float | None:
    try:
        return (float(o["lucro_min"]) + float(o["lucro_max"])) / 2 / float(o["acoes"])
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None


def planejar_ticker(ticker: str, hoje: dt.date, anterior: dict | None, vistos: set[str], *,
                    buscar_cnpj=cnpj_do_ticker, buscar_docs=documentos_cvm, ler_pdf=texto_do_pdf,
                    buscar_acoes=acoes_yahoo, ler_com_claude=extrair_com_claude) -> dict:
    """Decide o que fazer com um ticker. Não grava nada."""
    item = {"ticker": ticker, "acao": "nada", "motivo": "", "novo": None, "anterior": anterior}
    if not re.fullmatch(r"[A-Z]{4}\d{1,2}", ticker):
        item["motivo"] = "ações fora da B3 desligadas por enquanto"
        return item
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
        try:
            pdf, texto = ler_pdf(doc["link"])
        except Exception as e:  # noqa: BLE001
            log.info("  não abriu %s (%s)", doc["link"], e.__class__.__name__)
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
            ex = ler_com_claude(pdf, texto, ano) or ex
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
        mudou_muito = bool(lpa_ant and lpa_novo and abs(lpa_novo / lpa_ant - 1) > LIMITE_MUDANCA)
        motivos = list(ex.motivos)
        if mudou_muito:
            motivos.append(f"LPA projetado mudou {abs(lpa_novo / lpa_ant - 1):.0%} (limite {LIMITE_MUDANCA:.0%})")
        revisar = ex.metodo == "API do Claude" or ex.confianca != "alta" or mudou_muito
        item.update(acao="pr" if revisar else "commit", novo=novo,
                    motivo="; ".join(motivos) or "padrões de texto, confiança alta")
        return item
    item["motivo"] = "nenhum documento recente com guidance de lucro"
    return item


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
    plano = []
    for t in tickers:
        log.info("%s", t)
        vistos = set(vistos_por_ticker.get(t, []))
        try:
            item = planejar_ticker(t, hoje, auto.get(t), vistos)
        except Exception as e:  # noqa: BLE001 - um ticker com erro não derruba os outros
            item = {"ticker": t, "acao": "erro", "motivo": f"{e.__class__.__name__}: {e}", "novo": None, "anterior": auto.get(t)}
        vistos_por_ticker[t] = sorted(vistos)[-50:]
        nivel = logging.ERROR if item["acao"] == "erro" else logging.INFO
        log.log(nivel, "  -> %s: %s", item["acao"], item["motivo"])
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
    return aplicados


def resumo_pr(itens: list[dict]) -> str:
    def bi(v):
        return f"R$ {v / 1e9:,.1f} bi".replace(",", "X").replace(".", ",").replace("X", ".")

    linhas = ["Guidance encontrado automaticamente que precisa de revisão antes de ir para o app.", ""]
    for i in itens:
        n, a = i["novo"], i.get("anterior") or {}
        payout = "—" if n.get("payout") is None else f"{n['payout']:.0%}"
        linhas += [f"## {i['ticker']}", "",
                   f"- **Novo:** lucro de {bi(n['lucro_min'])} a {bi(n['lucro_max'])} ({n.get('ano')}), "
                   f"payout {payout}, LPA projetado {_lpa(n):.2f}",
                   f"- **Anterior:** " + (f"lucro de {bi(a['lucro_min'])} a {bi(a['lucro_max'])}, LPA {_lpa(a):.2f}" if _lpa(a) else "nenhum"),
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
