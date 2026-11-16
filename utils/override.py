"""Guidance oficial das empresas (override do Yahoo Finance).

Quando um ticker está em OVERRIDE, o LPA projetado e o dividendo projetado saem do guidance
divulgado pela própria empresa, e não do consenso de analistas do Yahoo:

    LPA projetado       = (lucro_min + lucro_max) / 2 / acoes
    Dividendo projetado = LPA projetado × payout

Regras para cadastrar (ver CLAUDE.md: só com fonte citada):
- Chave: ticker como o usuário digita, sem ".SA" (ex.: "BBAS3", "AAPL").
- lucro_min / lucro_max: lucro líquido projetado para o ano, na moeda da empresa e em unidades
  (ex.: 21_000_000_000 para R$ 21 bilhões).
- acoes: número total de ações (não em milhões).
- payout: fração do lucro distribuída (0,40 = 40%), entre 0 e 1. Opcional: sem ele, não há dividendo projetado.
- fonte: de onde veio (ex.: "Banco do Brasil, release 4T25 - guidance 2026").
- data: data da divulgação, "DD/MM/AAAA".

Exemplo (NÃO é dado real; o dicionário começa vazio):
    "XXXX3": {"lucro_min": 10_000_000_000, "lucro_max": 12_000_000_000, "acoes": 1_000_000_000,
              "payout": 0.40, "fonte": "Empresa X, release 4T25", "data": "10/02/2026"},
"""
from __future__ import annotations

import json
from pathlib import Path

# Cadastro manual: sempre ganha do automático.
OVERRIDE: dict[str, dict] = {}

# Cadastro automático, gravado pelo robô diário (utils/fetch_guidance.py).
ARQ_AUTO = Path(__file__).with_name("guidance_auto.json")


def _auto() -> dict[str, dict]:
    try:
        dados = json.loads(ARQ_AUTO.read_text(encoding="utf-8"))
        return dados if isinstance(dados, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def tabela() -> dict[str, dict]:
    """Automático + manual; para o mesmo ticker, o manual ganha."""
    return {**_auto(), **OVERRIDE}

CAMPOS = ("lucro_min", "lucro_max", "acoes", "fonte", "data")   # payout é opcional


def validar(ticker: str, o: dict) -> list[str]:
    """Problemas no cadastro de um override. Lista vazia = válido."""
    erros = [f"falta o campo '{c}'" for c in CAMPOS if c not in o or o[c] in (None, "")]
    if erros:
        return erros
    try:
        lmin, lmax, acoes = (float(o[c]) for c in ("lucro_min", "lucro_max", "acoes"))
        payout = None if o.get("payout") is None else float(o["payout"])
    except (TypeError, ValueError):
        return ["lucro_min, lucro_max, acoes e payout precisam ser números"]
    if lmin > lmax:
        erros.append("lucro_min maior que lucro_max")
    if acoes <= 0:
        erros.append("acoes precisa ser maior que zero")
    if payout is not None and not 0 <= payout <= 1:
        erros.append("payout precisa estar entre 0 e 1 (ex.: 0.40 para 40%)")
    return erros


def guidance(ticker: str, tabela: dict | None = None) -> dict | None:
    """Guidance do ticker já calculado, ou None se não houver override válido."""
    tabela = globals()["tabela"]() if tabela is None else tabela
    chave = ticker.strip().upper()
    chave = chave[:-3] if chave.endswith(".SA") else chave
    o = tabela.get(chave)
    if not o or validar(chave, o):
        return None
    acoes = float(o["acoes"])
    lpa = (float(o["lucro_min"]) + float(o["lucro_max"])) / 2 / acoes
    payout = None if o.get("payout") is None else float(o["payout"])
    return {
        "lpa": lpa,
        "lpaMin": float(o["lucro_min"]) / acoes,
        "lpaMax": float(o["lucro_max"]) / acoes,
        "dividendo": None if payout is None else lpa * payout,
        "payout": payout,
        "lucroMin": float(o["lucro_min"]), "lucroMax": float(o["lucro_max"]),
        "acoes": acoes, "fonte": str(o["fonte"]), "data": str(o["data"]),
        "url": str(o.get("url") or ""), "metodo": str(o.get("metodo") or "cadastro manual"),
    }
