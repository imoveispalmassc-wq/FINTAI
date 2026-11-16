"""Guidance oficial das empresas (override do Yahoo Finance).

Quando um ticker está em OVERRIDE, o LPA projetado e o dividendo projetado saem do guidance
divulgado pela própria empresa, e não do consenso de analistas do Yahoo:

    LPA projetado       = (lucro_min + lucro_max) / 2 / acoes
    Dividendo projetado = LPA projetado × payout

Regras para cadastrar (ver CLAUDE.md: só com fonte citada):
- Chave: ticker como o usuário digita, sem ".SA" (ex.: "BBAS3", "AAPL").
- lucro_min / lucro_max: lucro líquido projetado para o ano, na moeda da empresa e em unidades
  (ex.: 21_000_000_000 para R$ 21 bilhões).
- acoes: número total de ações (não em milhões). Opcional: sem ele, usa o número de ações do Yahoo Finance.
- lucro_tipo (opcional): como a empresa chama o lucro do guidance (ex.: "lucro líquido ajustado").
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

# Cadastro manual: sempre ganha do automático. Só com fonte oficial citada.
OVERRIDE: dict[str, dict] = {
    # Banco do Brasil, Fato Relevante "Revisão do Guidance 2026", divulgado no RI em 11/11/2026
    # (junto com o resultado do 3T26). Antes: R$ 18 a 22 bi e payout 30%. Realizado 9M26: R$ 8,6 bi.
    "BBAS3": {"lucro_min": 9_000_000_000, "lucro_max": 11_000_000_000, "payout": 0.25,
              "lucro_tipo": "lucro líquido ajustado",
              "fonte": "Banco do Brasil, Fato Relevante - Revisão do Guidance 2026 (RI)", "data": "11/11/2026"},
}

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

CAMPOS = ("lucro_min", "lucro_max", "fonte", "data")   # acoes e payout são opcionais


def validar(ticker: str, o: dict) -> list[str]:
    """Problemas no cadastro de um override. Lista vazia = válido."""
    erros = [f"falta o campo '{c}'" for c in CAMPOS if c not in o or o[c] in (None, "")]
    if erros:
        return erros
    try:
        lmin, lmax = (float(o[c]) for c in ("lucro_min", "lucro_max"))
        acoes = None if o.get("acoes") in (None, "") else float(o["acoes"])
        payout = None if o.get("payout") is None else float(o["payout"])
    except (TypeError, ValueError):
        return ["lucro_min, lucro_max, acoes e payout precisam ser números"]
    if lmin > lmax:
        erros.append("lucro_min maior que lucro_max")
    if acoes is not None and acoes <= 0:
        erros.append("acoes precisa ser maior que zero")
    if payout is not None and not 0 <= payout <= 1:
        erros.append("payout precisa estar entre 0 e 1 (ex.: 0.40 para 40%)")
    return erros


def guidance(ticker: str, tabela: dict | None = None, acoes_padrao: float | None = None) -> dict | None:
    """Guidance do ticker já calculado, ou None se não houver override válido.

    acoes_padrao: número de ações do Yahoo, usado quando o cadastro não traz `acoes`."""
    tabela = globals()["tabela"]() if tabela is None else tabela
    chave = ticker.strip().upper()
    chave = chave[:-3] if chave.endswith(".SA") else chave
    o = tabela.get(chave)
    if not o or validar(chave, o):
        return None
    acoes = float(o["acoes"]) if o.get("acoes") not in (None, "") else acoes_padrao
    if not acoes or acoes <= 0:
        return None
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
        "acoesFonte": "cadastro" if o.get("acoes") not in (None, "") else "Yahoo Finance",
        "lucroTipo": str(o.get("lucro_tipo") or "lucro líquido"),
    }
