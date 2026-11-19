"""Fila de tickers novos pedidos por usuários do app público, guardada como Issues do GitHub.

O app (Streamlit Cloud) não tem permissão para gravar no repositório: só o robô, via GitHub
Actions, grava arquivo (utils/guidance_tickers.json, utils/queue_nao_validado.json etc.). Para
avisar o robô de um ticker novo sem tocar no conteúdo do repositório, o app abre (ou comenta, se
já existir) uma Issue com a label "fila-ticker" neste mesmo repositório — Issues são uma feature
do GitHub separada do conteúdo versionado, então isso não é "gravar no repositório".

Usa um token com permissão SÓ de "Issues: Read and write" (GITHUB_QUEUE_TOKEN), nunca com
permissão de conteúdo. O valor do token nunca aparece no código nem no log.
"""
from __future__ import annotations

import datetime as dt
import logging

import requests

log = logging.getLogger("fila_tickers")

API = "https://api.github.com"
REPO = "imoveispalmassc-wq/fintai"
LABEL = "fila-ticker"
PREFIXO = "Fila: "
TIMEOUT = 8


def _cabecalho(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


def _buscar_issue(ticker: str, token: str) -> dict | None:
    titulo = f"{PREFIXO}{ticker}"
    r = requests.get(f"{API}/search/issues", headers=_cabecalho(token), timeout=TIMEOUT,
                     params={"q": f'repo:{REPO} is:issue is:open label:{LABEL} in:title "{titulo}"'})
    r.raise_for_status()
    return next((i for i in r.json().get("items", []) if i["title"] == titulo), None)


def _criar_issue(ticker: str, token: str) -> dict:
    agora = f"{dt.datetime.now(dt.timezone.utc):%d/%m/%Y %H:%M UTC}"
    r = requests.post(f"{API}/repos/{REPO}/issues", headers=_cabecalho(token), timeout=TIMEOUT,
                      json={"title": f"{PREFIXO}{ticker}", "labels": [LABEL],
                            "body": f"Pedido automático do app: alguém digitou **{ticker}**, sem guidance "
                                    f"verificado ainda.\n\nPrimeiro pedido: {agora}."})
    r.raise_for_status()
    return r.json()


def _comentar_issue(numero: int, token: str, corpo: str = "+1 pedido.") -> None:
    r = requests.post(f"{API}/repos/{REPO}/issues/{numero}/comments", headers=_cabecalho(token),
                      timeout=TIMEOUT, json={"body": corpo})
    r.raise_for_status()


def pedir_ticker(ticker: str, token: str | None, *, buscar=None, criar=None, comentar=None) -> bool:
    """Registra um pedido de `ticker` na fila (abre a Issue, ou comenta numa já aberta para dar dedup
    e contar quantas vezes foi pedido). Nunca levanta exceção — uma falha na fila não pode travar a
    tela do usuário. True se conseguiu falar com a API; False se faltou token ou a API falhou."""
    if not token:
        return False
    buscar, criar, comentar = buscar or _buscar_issue, criar or _criar_issue, comentar or _comentar_issue
    try:
        issue = buscar(ticker, token)
        comentar(issue["number"], token) if issue else criar(ticker, token)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("fila: não consegui registrar %s (%s: %s)", ticker, e.__class__.__name__, e)
        return False


def _listar_issues_abertas(token: str) -> list[dict]:
    issues, pagina = [], 1
    while True:
        r = requests.get(f"{API}/repos/{REPO}/issues", headers=_cabecalho(token), timeout=TIMEOUT,
                         params={"state": "open", "labels": LABEL, "per_page": 100, "page": pagina})
        r.raise_for_status()
        lote = r.json()
        issues += lote
        if len(lote) < 100:
            return issues
        pagina += 1


def listar_fila(token: str, *, buscar=None) -> list[dict]:
    """Issues abertas da fila: {"ticker", "numero", "pedidos" (1 + comentários), "criada_em"},
    da mais pedida para a menos pedida. Duplicatas (mesmo ticker) não existem: dedup já é feito
    na hora de pedir (pedir_ticker só cria issue nova se não achar uma aberta com o mesmo título)."""
    issues = (buscar or _listar_issues_abertas)(token)
    fila = [{"ticker": i["title"][len(PREFIXO):].strip(), "numero": i["number"],
            "pedidos": 1 + i.get("comments", 0), "criada_em": i.get("created_at")}
           for i in issues if i.get("title", "").startswith(PREFIXO)]
    return sorted(fila, key=lambda x: x["pedidos"], reverse=True)


def fechar_issue(numero: int, token: str, comentario: str, *, comentar=None, fechar=None) -> None:
    """Fecha a issue da fila, com um comentário explicando o resultado (validado ou travado)."""
    (comentar or _comentar_issue)(numero, token, comentario)
    r = (fechar or (lambda n, t: requests.patch(f"{API}/repos/{REPO}/issues/{n}", headers=_cabecalho(t),
                                                 timeout=TIMEOUT, json={"state": "closed"})))(numero, token)
    if r is not None:
        r.raise_for_status()
