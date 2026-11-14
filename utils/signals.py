"""Regras de decisão do FINTAI: estado do ativo, selo do teste histórico e fundamentos."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from utils.formato import num
from utils.percentile import (P_CARO, P_COMPRA, P_OPORTUNIDADE, percentil_movel,
                              preco_no_percentil)

ACERTO_MINIMO = 60.0   # % de acerto em 12 meses para validar um sinal
CASOS_MINIMOS = 8      # semanas de histórico no sinal para a estatística valer
DIVIDA_EBITDA_MAX = 4.0
TOLERANCIA = 5.0       # % de diferença para um critério deixar de ser "Neutro"


# ------------------------------------------------------------ selo do backtest
@dataclass(frozen=True)
class Selo:
    validado: bool
    rotulo: str
    texto: str


def selo_backtest(tipo: str, acerto_12m: float | None, retorno_12m: float | None,
                  referencia_12m: float | None, casos: int, ticker: str = "") -> Selo:
    """Valida um sinal pelo que aconteceu nos 12 meses seguintes, no histórico do ativo.

    tipo "compra": acerto = % das vezes em que a ação subiu; validado se acerto > 60%
        e o retorno médio superou a referência (comprar em uma semana qualquer).
    tipo "venda": acerto = % das vezes em que a ação caiu; validado se acerto > 60%
        e o retorno médio ficou abaixo da referência.
    """
    nome = ticker or "este ativo"
    faltam = (acerto_12m is None or retorno_12m is None or referencia_12m is None
              or casos < CASOS_MINIMOS)
    if tipo == "compra":
        ok = not faltam and acerto_12m > ACERTO_MINIMO and retorno_12m > referencia_12m
        if ok:
            if referencia_12m > 0:
                texto = f"Comprar nesse sinal deu {num(retorno_12m / referencia_12m, 1)}x mais retorno"
            else:
                texto = "Comprar nesse sinal rendeu mais do que comprar em uma semana qualquer"
        elif faltam:
            texto = f"Poucos casos no histórico. NÃO use esse sinal para comprar {nome}."
        else:
            texto = (f"Comprar nesse sinal não rendeu mais do que comprar em uma semana "
                     f"qualquer. NÃO use esse sinal para comprar {nome}.")
    elif tipo == "venda":
        ok = not faltam and acerto_12m > ACERTO_MINIMO and retorno_12m < referencia_12m
        if ok:
            texto = (f"Depois desse sinal a ação caiu em {num(acerto_12m, 0)}% das vezes. "
                     "Vender nesse sinal evitou perdas.")
        elif not faltam and retorno_12m > 0:
            texto = f"Quem vendeu perdeu alta. NÃO use esse sinal para vender {nome}."
        elif faltam:
            texto = f"Poucos casos no histórico. NÃO use esse sinal para vender {nome}."
        else:
            texto = f"Vender nesse sinal não se confirmou. NÃO use esse sinal para vender {nome}."
    else:
        raise ValueError("tipo deve ser 'compra' ou 'venda'")
    return Selo(ok, "SINAL VALIDADO ✅" if ok else "SINAL INVALIDADO ❌", texto)


# ------------------------------------------------------------ fundamento quebrou
def fundamento_quebrou(lucros_trimestrais: pd.Series | None,
                       divida_liquida_ebitda: float | None) -> tuple[bool, str]:
    """True se os 2 últimos trimestres deram prejuízo ou dívida líquida/EBITDA > 4."""
    if lucros_trimestrais is not None:
        l = lucros_trimestrais.dropna().sort_index()
        if len(l) >= 2 and (l.iloc[-2:] < 0).all():
            return True, "2 trimestres seguidos de prejuízo"
    if divida_liquida_ebitda is not None and divida_liquida_ebitda > DIVIDA_EBITDA_MAX:
        return True, f"dívida líquida de {num(divida_liquida_ebitda, 1)}x o EBITDA (limite: 4x)"
    return False, ""


# ------------------------------------------------------------ estado
@dataclass(frozen=True)
class Estado:
    codigo: str   # COMPRAR | AGUARDAR | CARO | VENDER
    rotulo: str
    texto: str


def decidir_estado(percentil: float, minimo: float, maximo: float, *,
                   compra_validada: bool, venda_validada: bool,
                   quebrou: bool = False, motivo_quebra: str = "",
                   simbolo: str = "R$") -> Estado:
    """Decide o estado do ativo. Ordem de prioridade:

    1. VENDER  - fundamento quebrou; ou preço >= percentil 70 com venda validada no histórico.
    2. CARO    - preço >= percentil 70 (sem venda validada). Nunca fala em vender.
    3. COMPRAR - preço <= percentil 35 com compra validada no histórico.
    4. AGUARDAR - todo o resto.
    """
    p = round(percentil)
    if quebrou:
        return Estado("VENDER", "VENDER · Fundamento quebrou",
                      f"Fundamento quebrou: {motivo_quebra}.")
    if percentil >= P_CARO:
        if venda_validada:
            return Estado("VENDER", "VENDER · Validado pelo histórico",
                          f"Preço no percentil {p} e, no histórico deste ativo, a ação caiu na "
                          "maioria das vezes nos 12 meses seguintes.")
        limite = preco_no_percentil(minimo, maximo, P_CARO)
        return Estado("CARO", "CARO · Não comprar",
                      f"Caro para comprar agora. Preço no percentil {p}. "
                      f"Volta à zona neutra abaixo de {simbolo} {num(limite)} (percentil {P_CARO}).")
    if percentil <= P_COMPRA:
        if compra_validada:
            return Estado("COMPRAR", "COMPRAR · Oportunidade",
                          f"Preço no percentil {p} e comprar nessa faixa foi validado "
                          "pelo histórico deste ativo.")
        return Estado("AGUARDAR", "AGUARDAR · Neutro",
                      f"Preço no percentil {p}, mas comprar nessa faixa não foi validado pelo "
                      "histórico deste ativo. Sem vantagem estatística agora.")
    alvo = preco_no_percentil(minimo, maximo, P_OPORTUNIDADE)
    return Estado("AGUARDAR", "AGUARDAR · Neutro",
                  f"Preço no percentil {p} - sem vantagem estatística agora. "
                  f"Ponto de oportunidade em {simbolo} {num(alvo)} (percentil {P_OPORTUNIDADE}).")


# ------------------------------------------------------------ critérios de fundamentos
@dataclass(frozen=True)
class Avaliacao:
    status: str            # Favorável | Neutro | Desfavorável | Sem dados
    icone: str
    diferenca: float | None  # % do valor atual em relação à referência


def avaliar_criterio(atual: float | None, referencia: float | None, *,
                     maior_e_melhor: bool, tolerancia: float = TOLERANCIA) -> Avaliacao:
    """Compara o valor atual com a referência. Diferença dentro de ±5% é Neutro."""
    if atual is None or referencia is None or pd.isna(atual) or pd.isna(referencia) or referencia == 0:
        return Avaliacao("Sem dados", "➖", None)
    dif = (atual - referencia) / abs(referencia) * 100
    if abs(dif) < tolerancia:
        return Avaliacao("Neutro", "⚠️", dif)
    bom = dif > 0 if maior_e_melhor else dif < 0
    return Avaliacao("Favorável", "✅", dif) if bom else Avaliacao("Desfavorável", "❌", dif)


# ------------------------------------------------------------ teste histórico
def backtest_percentil(hist: pd.DataFrame) -> dict:
    """Aplica as regras de percentil semana a semana, só com dados conhecidos em cada data,
    e mede o que aconteceu 6 e 12 meses depois.

    Devolve, para "compra" (percentil <= 35), "venda" (percentil >= 70) e "referencia"
    (qualquer semana): casos, retorno médio de 6 e 12 meses e acerto de 12 meses.
    Na venda, acerto = % das vezes em que a ação caiu.
    """
    h = hist.copy()
    if getattr(h.index, "tz", None) is not None:
        h.index = h.index.tz_localize(None)
    h = h.sort_index().dropna(subset=["High", "Low", "Close"])
    adj = (h["Adj Close"] if "Adj Close" in h else h["Close"]).ffill()
    w = h.resample("W-FRI").agg({"Low": "min", "High": "max", "Close": "last"})
    w["adj"] = adj.resample("W-FRI").last()
    w = w.dropna(subset=["Close"])
    perc = percentil_movel(w["Close"], w["Low"], w["High"]).to_numpy()
    valido = ~np.isnan(perc)
    r6 = (w["adj"].shift(-26) / w["adj"] - 1).to_numpy() * 100
    r12 = (w["adj"].shift(-52) / w["adj"] - 1).to_numpy() * 100

    def medir(mascara, acerto_na_queda=False):
        m = mascara & valido
        a, b = r6[m & ~np.isnan(r6)], r12[m & ~np.isnan(r12)]
        acerto = None
        if len(b):
            acerto = float(((b < 0) if acerto_na_queda else (b > 0)).mean() * 100)
        return {"casos": int(len(b)),
                "retorno_6m": float(a.mean()) if len(a) else None,
                "retorno_12m": float(b.mean()) if len(b) else None,
                "acerto_12m": acerto}

    with np.errstate(invalid="ignore"):
        compra, venda = perc <= P_COMPRA, perc >= P_CARO
    datas = w.index[valido]
    return {
        "compra": medir(compra),
        "venda": medir(venda, acerto_na_queda=True),
        "referencia": medir(np.ones(len(w), dtype=bool)),
        "anos": (datas[-1] - datas[0]).days / 365.25 if len(datas) else 0.0,
    }
