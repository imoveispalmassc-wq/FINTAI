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

Guidance em lucro por ação (comum nos EUA): em vez de lucro_min/lucro_max, use lpa_min/lpa_max
(LPA projetado direto, sem precisar de ações). Opcionais: dividendo (dividendo anual por ação
divulgado pela empresa; ganha do payout) e periodo (ex.: "2026", "FY2027" para ano fiscal).
Base recalculada pela empresa (ex.: mudança no critério não-GAAP): base_AAAA_recalculada e, se informado,
base_AAAA_antes (ex.: base_2025_recalculada = 4.65, base_2025_antes = 4.97). Só com a tabela citada na fonte.

Exemplo (NÃO é dado real; o dicionário começa vazio):
    "XXXX3": {"lucro_min": 10_000_000_000, "lucro_max": 12_000_000_000, "acoes": 1_000_000_000,
              "payout": 0.40, "fonte": "Empresa X, release 4T25", "data": "10/02/2026"},
"""
from __future__ import annotations

import json
import re
from pathlib import Path

# Cadastro manual: sempre ganha do automático. Só com fonte oficial citada.
OVERRIDE: dict[str, dict] = {
    # Banco do Brasil, Fato Relevante "Revisão do Guidance 2026", divulgado no RI em 11/11/2026
    # (junto com o resultado do 3T26). Antes: R$ 18 a 22 bi e payout 30%. Realizado 9M26: R$ 8,6 bi.
    "BBAS3": {"lucro_min": 9_000_000_000, "lucro_max": 11_000_000_000, "payout": 0.25,
              "lucro_tipo": "lucro líquido ajustado",
              "fonte": "Banco do Brasil, Fato Relevante - Revisão do Guidance 2026 (RI)", "data": "11/11/2026"},
    # ADM, "ADM Reports Third Quarter 2026 Results" (03/11/2026): LPA ajustado 2026 elevado para cerca de
    # US$ 5,50 a 5,80 (antes US$ 5,15 a 5,60).
    "ADM": {"lpa_min": 5.50, "lpa_max": 5.80, "periodo": "2026", "lucro_tipo": "LPA ajustado",
            "fonte": "ADM Reports Third Quarter 2026 Results", "data": "03/11/2026"},
    # Henry Schein, SEC Form 8-K de 16/11/2026, Exhibit 99.1 (Business Wire, "Henry Schein Updates Presentation
    # of Non-GAAP Financial Measures", 16/11/2026 06:00 EST): LPA não-GAAP 2026 de US$ 5,42 a 5,48 (antes
    # 5,50 a 5,56), sem os ganhos de remensuração de aquisições. Tabela "Non-GAAP EPS As Recast":
    # 2025 = 4,65 (antes 4,97) e 2024 = 4,58 (antes 4,74).
    "HSIC": {"lpa_min": 5.42, "lpa_max": 5.48, "periodo": "2026", "lucro_tipo": "LPA ajustado (não-GAAP)",
             "base_2025_recalculada": 4.65, "base_2025_antes": 4.97,
             "base_2024_recalculada": 4.58, "base_2024_antes": 4.74,
             "fonte": "SEC Form 8-K HSIC, Exhibit 99.1 - Business Wire \"Henry Schein Updates Presentation of "
                      "Non-GAAP Financial Measures\" (16/11/2026 06:00 EST)", "data": "16/11/2026"},
    # AECOM, Form 8-K do 4T do ano fiscal 2026 (16/11/2026): LPA ajustado FY2027 de US$ 6,15 a 6,35;
    # dividendo trimestral elevado em 10% para US$ 0,34 (US$ 1,36 por ano).
    "ACM": {"lpa_min": 6.15, "lpa_max": 6.35, "periodo": "FY2027", "lucro_tipo": "LPA ajustado",
            "dividendo": 1.36, "fonte": "AECOM Form 8-K fiscal Q4 2026", "data": "16/11/2026"},
    # XP: sem guidance novo. Não cadastrar.
    # MOG-A, MOG-B, BJ, ESE: sem cadastro manual de propósito - já estão na fila pública
    # (Issues "Fila: MOG-A/MOG-B/BJ/ESE") pro robô validar sozinho com as 4 travas do AUTOMÁTICO
    # COM PROTEÇÃO, em vez de entrar pela mão aqui.
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
CAMPOS_LPA = ("lpa_min", "lpa_max", "fonte", "data")   # guidance em lucro por ação


def validar(ticker: str, o: dict) -> list[str]:
    """Problemas no cadastro de um override. Lista vazia = válido."""
    por_lpa = "lpa_min" in o or "lpa_max" in o
    erros = [f"falta o campo '{c}'" for c in (CAMPOS_LPA if por_lpa else CAMPOS) if c not in o or o[c] in (None, "")]
    if erros:
        return erros
    if por_lpa:
        try:
            lmin, lmax = float(o["lpa_min"]), float(o["lpa_max"])
            div = None if o.get("dividendo") in (None, "") else float(o["dividendo"])
        except (TypeError, ValueError):
            return ["lpa_min, lpa_max e dividendo precisam ser números"]
        if lmin > lmax:
            erros.append("lpa_min maior que lpa_max")
        if div is not None and div < 0:
            erros.append("dividendo não pode ser negativo")
        for k, v in o.items():
            if re.fullmatch(r"base_\d{4}_(recalculada|antes)", k):
                try:
                    float(v)
                except (TypeError, ValueError):
                    erros.append(f"{k} precisa ser número")
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
    base = {"fonte": str(o["fonte"]), "data": str(o["data"]), "url": str(o.get("url") or ""),
            "metodo": str(o.get("metodo") or "cadastro manual"), "periodo": str(o.get("periodo") or "")}
    if "lpa_min" in o:
        lmin, lmax = float(o["lpa_min"]), float(o["lpa_max"])
        lpa = (lmin + lmax) / 2
        div = None if o.get("dividendo") in (None, "") else float(o["dividendo"])
        payout = None if o.get("payout") is None else float(o["payout"])
        bases = sorted(({"ano": int(m.group(1)), "valor": float(v), "antes": None if o.get(f"base_{m.group(1)}_antes") in (None, "") else float(o[f"base_{m.group(1)}_antes"])}
                        for k, v in o.items() if (m := re.fullmatch(r"base_(\d{4})_recalculada", k))), key=lambda b: -b["ano"])
        return {**base, "lpa": lpa, "lpaMin": lmin, "lpaMax": lmax, "porLpa": True, "bases": bases,
                "dividendo": div if div is not None else (None if payout is None else lpa * payout),
                "dividendoFonte": "empresa" if div is not None else ("payout" if payout is not None else ""),
                "payout": payout, "lucroMin": None, "lucroMax": None, "acoes": None, "acoesFonte": "",
                "lucroTipo": str(o.get("lucro_tipo") or "LPA")}
    acoes = float(o["acoes"]) if o.get("acoes") not in (None, "") else acoes_padrao
    if not acoes or acoes <= 0:
        return None
    lpa = (float(o["lucro_min"]) + float(o["lucro_max"])) / 2 / acoes
    payout = None if o.get("payout") is None else float(o["payout"])
    return {**base, "porLpa": False, "bases": [], "dividendoFonte": "payout" if payout is not None else "",
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


# ------------------------------------------------------------ projeção do início do ano (congelada)
# Primeiro guidance que a empresa deu para o ano (ex.: ADM 2026 no release do 4T25). Gravado uma vez e
# TRAVADO: nunca é sobrescrito, mesmo quando a empresa atualiza o guidance depois. O robô grava em
# guidance_inicial.json; sem achar, fica {"status": "sem projeção inicial encontrada"}.
ARQ_INICIAL = Path(__file__).with_name("guidance_inicial.json")
SEM_INICIAL = "sem projeção inicial encontrada"


def tabela_inicial() -> dict[str, dict]:
    try:
        dados = json.loads(ARQ_INICIAL.read_text(encoding="utf-8"))
        return dados if isinstance(dados, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _tem_projecao(o: dict | None) -> bool:
    return bool(o) and ("lpa_min" in o or "lucro_min" in o)


def gravar_inicial(tabela: dict, ticker: str, ano: str, novo: dict | None) -> tuple[dict, bool]:
    """Grava a projeção inicial do ano só se ainda não houver uma. Devolve (tabela, gravou).

    Já existindo projeção para (ticker, ano), nada muda: o guidance inicial é congelado."""
    t = {k: dict(v) for k, v in tabela.items()}
    atual = t.setdefault(ticker, {}).get(ano)
    if _tem_projecao(atual):
        return t, False
    if novo is None:
        if not atual:
            t[ticker][ano] = {"status": SEM_INICIAL}
            return t, True
        return t, False
    t[ticker][ano] = {**novo, "travado": True}
    return t, True


def guidance_inicial(ticker: str, ano: str, tabela: dict | None = None, acoes_padrao: float | None = None) -> dict | None:
    """Projeção do início do ano já calculada (lpa, lpaMin, lpaMax, fonte, data) ou {"status": ...}."""
    tabela = tabela_inicial() if tabela is None else tabela
    chave = ticker.strip().upper()
    chave = chave[:-3] if chave.endswith(".SA") else chave
    o = (tabela.get(chave) or {}).get(str(ano))
    if o is None:
        return {"status": SEM_INICIAL, "ano": str(ano)}
    if not _tem_projecao(o):
        return {"status": o.get("status") or SEM_INICIAL, "ano": str(ano)}
    if validar(chave, o):
        return {"status": "projeção inicial inválida no cadastro", "ano": str(ano)}
    lucros = {}
    if "lpa_min" in o:
        lmin, lmax = float(o["lpa_min"]), float(o["lpa_max"])
    else:
        lucros = {"lucroMin": float(o["lucro_min"]), "lucroMax": float(o["lucro_max"])}
        acoes = float(o["acoes"]) if o.get("acoes") not in (None, "") else acoes_padrao
        if not acoes:
            return {"status": "sem número de ações para a projeção inicial", "ano": str(ano)}
        lmin, lmax = float(o["lucro_min"]) / acoes, float(o["lucro_max"]) / acoes
    return {"ano": str(ano), "lpa": (lmin + lmax) / 2, "lpaMin": lmin, "lpaMax": lmax, "fonte": str(o["fonte"]),
            "data": str(o["data"]), "url": str(o.get("url") or ""), "tipo": str(o.get("lucro_tipo") or ("LPA" if not lucros else "lucro líquido")),
            "travado": True, **lucros}
