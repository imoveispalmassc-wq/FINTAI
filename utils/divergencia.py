"""Automação total de divergência - Issue #48, item 9.

Quando um robô do projeto (TTM diário em utils/ttm_auto.py, guidance automático em
utils/fetch_guidance.py, ou a biblioteca própria em utils/biblioteca.py) acha um número
diferente do que já está salvo, ele mesmo abre uma Issue sozinho (`abrir_issue_divergencia`, API
REST do GitHub com o `GITHUB_TOKEN` padrão do Actions - não precisa de um token especial, só
"Issues: write" no mesmo repositório). Um SEGUNDO workflow, disparado por
`issues: opened` filtrando a label "divergencia" (`.github/workflows/divergencia-revisar.yml`),
chama a API do Claude para revisar a Issue com as MESMAS 4 travas já documentadas do AUTOMÁTICO
COM PROTEÇÃO (`revisar_divergencia`, que reaproveita `utils.fetch_guidance.avaliar_travas` -
nunca duplica a lógica das travas):

- Passou nas 4 travas -> abre um pull request com a correção sugerida (NUNCA comita direto na
  main - mesma regra travada de REGRA 6 do TTM automático, CLAUDE.md). Merge publica, fechar
  descarta.
- Travou em alguma -> a Issue de divergência fica aberta, esperando a decisão humana (o workflow
  comenta qual trava falhou, mas não fecha nem publica nada).

Este módulo é genérico de propósito (qualquer robô pode chamar `detectar` +
`abrir_issue_divergencia`). Hoje é acionado automaticamente em dois pontos:
- `utils.ttm_auto._avisar_divergencia_ttm` - TTM diário recalculado por um documento novo e
  diferente do LPA TTM que já estava em `ttm_diario.json`.
- `utils.biblioteca.salvar_na_biblioteca` - qualquer campo da biblioteca própria (item 8) gravado
  com um valor contábil diferente do anterior.

O guidance automático (`utils/fetch_guidance.py`) já tem o seu PRÓPRIO mecanismo equivalente
(AUTOMÁTICO COM PROTEÇÃO: `avaliar_travas` + PR "Guidance travado"/issue "Guidance publicado") -
de propósito, ele NÃO também abre uma Issue "divergencia" genérica por cima: seria o mesmo aviso
duplicado. `revisar_divergencia`, abaixo, é o que faz a ponte entre os dois mundos: reaproveita a
MESMA função `avaliar_travas` do guidance automático para decidir as divergências abertas por
este módulo, em vez de duplicar a lógica das 4 travas.

LIMITAÇÃO CONHECIDA (documentada no PR da Issue #48): a Issue de divergência (`abrir_issue_
divergencia`) guarda só um resumo (ticker, campo, salvo, novo, fonte, link, data/hora) - não o
texto completo do documento oficial. Por isso, quando `revisar_issue_divergencia` (chamada pelo
segundo workflow) reavalia a trava "Número em 2 lugares" (que conta quantas vezes a faixa aparece
no TEXTO do documento), ela sempre falha nesse fluxo específico (não há texto para contar) - e a
divergência fica travada esperando decisão humana, em vez de abrir PR sozinha. Isso é intencional
e do lado seguro (nunca publica sem confirmação completa), mas, na prática, a maioria das
divergências abertas por este caminho só vai virar PR automático depois de uma melhoria futura
que inclua o texto do documento no corpo da Issue (ou que compare contra o próprio documento de
novo, como o guidance automático já faz).
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
from pathlib import Path

log = logging.getLogger("divergencia")

API = "https://api.github.com"
REPO = "imoveispalmassc-wq/fintai"
LABEL = "divergencia"
TIMEOUT = 8


def detectar(salvo, novo, tolerancia: float = 0.001) -> bool:
    """True quando `novo` é realmente diferente de `salvo` (fora de uma tolerância de
    arredondamento - 0,1% por padrão). None/ausência de um dos dois lados nunca é "divergência":
    é só "ainda não tinha nada salvo", caso já tratado por quem chama."""
    if salvo is None or novo is None:
        return False
    try:
        salvo_n, novo_n = float(salvo), float(novo)
    except (TypeError, ValueError):
        return salvo != novo
    if salvo_n == 0:
        return novo_n != 0
    return abs(novo_n / salvo_n - 1) > tolerancia


def _cabecalho(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


def abrir_issue_divergencia(ticker: str, campo: str, salvo, novo, fonte: str, link: str | None,
                            data_hora: str, base: str = "contábil", *, token: str | None = None,
                            repo: str = REPO, criar=None) -> dict | None:
    """Abre a Issue "Divergência: TICKER - Salvo: X / Novo: Y" (label "divergencia"), com o corpo
    pedido na Issue #48: fonte + link + data/hora + se é contábil ou ajustado (`base`). Usa o
    `GITHUB_TOKEN` padrão do Actions (token=None lê de os.environ) - só precisa de permissão de
    Issues no mesmo repositório, nunca de conteúdo. Nunca levanta exceção: best-effort, True/dict
    só quando a Issue foi criada; None sem token ou se a API falhar (quem chama não trava por
    isso - ver utils.biblioteca.salvar_na_biblioteca)."""
    token = token or os.environ.get("GITHUB_TOKEN")
    if not token:
        log.warning("divergencia: sem GITHUB_TOKEN: não abri a issue de divergência de %s.%s", ticker, campo)
        return None
    titulo = f"Divergência: {ticker} - Salvo: {salvo} / Novo: {novo}"
    corpo = (
        f"**Ticker:** {ticker}\n"
        f"**Campo:** {campo}\n"
        f"**Base:** {base}\n"
        f"**Salvo:** {salvo}\n"
        f"**Novo:** {novo}\n"
        f"**Fonte:** {fonte}\n"
        f"**Link:** {link or 'sem link'}\n"
        f"**Data/hora:** {data_hora}\n\n"
        "Um segundo workflow (`divergencia-revisar.yml`) vai chamar a API do Claude para revisar "
        "esta divergência com as mesmas 4 travas do AUTOMÁTICO COM PROTEÇÃO (fonte oficial, número "
        "em 2 lugares, variação até 20%, P/L plausível). Se passar nas 4, abre um pull request com "
        "a correção sugerida (nunca vai direto para a main). Se travar em alguma, esta Issue fica "
        "aberta esperando a sua decisão."
    )
    if criar is None:
        import requests

        def criar(titulo_, corpo_):
            r = requests.post(f"{API}/repos/{repo}/issues", headers=_cabecalho(token), timeout=TIMEOUT,
                              json={"title": titulo_, "labels": [LABEL], "body": corpo_})
            r.raise_for_status()
            return r.json()
    try:
        return criar(titulo, corpo)
    except Exception as e:  # noqa: BLE001
        log.warning("divergencia: não consegui abrir a issue de %s.%s (%s: %s)",
                   ticker, campo, e.__class__.__name__, e)
        return None


def revisar_divergencia(ticker: str, novo: dict, salvo: dict | None, texto_fonte: str,
                        hoje: dt.date, *, buscar_mercado=None) -> dict:
    """Reaproveita utils.fetch_guidance.avaliar_travas (as MESMAS 4 travas do AUTOMÁTICO COM
    PROTEÇÃO) para decidir se a divergência pode virar um pull request automático ou se trava
    esperando decisão humana. `novo`/`salvo` seguem o mesmo formato aceito por avaliar_travas
    (ex.: {"lucro_min": ..., "lucro_max": ...} ou {"lpa_min": ..., "lpa_max": ...})."""
    from utils.fetch_guidance import avaliar_travas, mercado_yahoo

    buscar_mercado = buscar_mercado or mercado_yahoo
    return avaliar_travas(ticker, novo, salvo, texto_fonte, hoje, duvidas=[], buscar_mercado=buscar_mercado)


# ------------------------------------------------------------ revisão automática da Issue (2º workflow)
_PADROES_CAMPOS = (
    ("ticker", r"\*\*Ticker:\*\*\s*(.+)"), ("campo", r"\*\*Campo:\*\*\s*(.+)"),
    ("base", r"\*\*Base:\*\*\s*(.+)"), ("salvo", r"\*\*Salvo:\*\*\s*(.+)"),
    ("novo", r"\*\*Novo:\*\*\s*(.+)"), ("fonte", r"\*\*Fonte:\*\*\s*(.+)"),
    ("link", r"\*\*Link:\*\*\s*(.+)"), ("data_hora", r"\*\*Data/hora:\*\*\s*(.+)"),
)


def parsear_issue(corpo: str) -> dict:
    """Extrai os campos do corpo da Issue de divergência, no formato gravado por
    `abrir_issue_divergencia` ("**Campo:** valor" por linha). Campo ausente não aparece no dict -
    nunca inventa um valor que não estava escrito na Issue."""
    campos = {}
    for chave, padrao in _PADROES_CAMPOS:
        m = re.search(padrao, corpo or "")
        if m:
            valor = m.group(1).strip()
            campos[chave] = None if valor.lower() in ("none", "sem link") else valor
    return campos


def _num_ou_texto(txt):
    try:
        return float(txt)
    except (TypeError, ValueError):
        return txt


def revisar_issue_divergencia(corpo: str, hoje: dt.date, *, buscar_mercado=None) -> dict:
    """Revisa uma Issue de divergência já aberta (chamada pelo 2º workflow,
    `.github/workflows/divergencia-revisar.yml`): reaproveita `avaliar_travas` (via
    `revisar_divergencia`) com o que está disponível na própria Issue. Ver a LIMITAÇÃO CONHECIDA
    no topo deste módulo sobre a trava "Número em 2 lugares". Devolve
    {"campos": {...}, "decisao": {"publica": bool, "travas": [...], "motivo": str}}."""
    campos = parsear_issue(corpo)
    if not campos.get("ticker") or campos.get("salvo") is None or campos.get("novo") is None:
        return {"campos": campos, "decisao": {"publica": False, "travas": [],
               "motivo": "TRAVADO - corpo da Issue fora do formato esperado (sem ticker/salvo/novo)"}}
    salvo, novo = _num_ou_texto(campos["salvo"]), _num_ou_texto(campos["novo"])
    novo_dict = {"lpa_min": novo, "lpa_max": novo, "url": campos.get("link") or ""}
    salvo_dict = {"lpa_min": salvo, "lpa_max": salvo}
    decisao = revisar_divergencia(campos["ticker"], novo_dict, salvo_dict, "", hoje, buscar_mercado=buscar_mercado)
    return {"campos": campos, "decisao": decisao}


def aplicar_correcao(ticker: str, campo: str, valor, caminho: Path) -> None:
    """Grava a correção já CONFIRMADA (passou nas 4 travas) no arquivo indicado (ex.:
    utils/biblioteca.json), pra entrar no pull request que o workflow cria em seguida - nunca
    comita direto na main (isso é feito pelo workflow, fora deste módulo, igual à REGRA 6)."""
    dados = json.loads(caminho.read_text(encoding="utf-8")) if caminho.exists() else {}
    dados.setdefault(ticker.upper(), {}).setdefault(campo, {})["valor"] = valor
    caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    p = argparse.ArgumentParser(description="Revisão automática de divergência - Issue #48, item 9")
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("revisar", help="revisa o corpo de uma Issue de divergência com as 4 travas")
    pr.add_argument("--corpo", required=True, help="arquivo com o corpo da Issue")
    pr.add_argument("--saida", default="revisao.json")

    pa = sub.add_parser("aplicar", help="grava a correção já confirmada (passou nas 4 travas)")
    pa.add_argument("--ticker", required=True)
    pa.add_argument("--campo", required=True)
    pa.add_argument("--valor", required=True, type=float)
    pa.add_argument("--caminho", default="utils/biblioteca.json")

    args = p.parse_args(argv)
    if args.cmd == "revisar":
        corpo = Path(args.corpo).read_text(encoding="utf-8")
        resultado = revisar_issue_divergencia(corpo, dt.date.today())
        Path(args.saida).write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("%s", resultado["decisao"]["motivo"])
        return 0
    if args.cmd == "aplicar":
        aplicar_correcao(args.ticker, args.campo, args.valor, Path(args.caminho))
        log.info("aplicado: %s.%s = %s em %s", args.ticker, args.campo, args.valor, args.caminho)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
