"""Cálculos do dashboard, separados da interface para poderem ser testados."""
from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

# PETR4, VALE3, BOVA11, TAEE11, SANB11 ... => ação/FII/ETF da B3
_PADRAO_B3 = re.compile(r"^[A-Z]{4}\d{1,2}[A-Z]?$")


def normalizar_ticker(texto: str) -> str:
    """Coloca .SA em tickers da B3 digitados sem sufixo (PETR4 -> PETR4.SA)."""
    t = texto.strip().upper()
    if not t:
        return t
    if "." not in t and _PADRAO_B3.match(t):
        return f"{t}.SA"
    return t


def _sem_fuso(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if getattr(df.index, "tz", None) is not None:
        df.index = df.index.tz_localize(None)
    return df.sort_index()


@dataclass
class Resultado:
    preco_atual: float
    data_ultimo: pd.Timestamp
    # 1 ano (52 semanas)
    minimo_1a: float
    maximo_1a: float
    fechamento_1a: float
    # médias semanais de 52 semanas
    media_minimas: float
    media_maximas: float
    media_fechamentos: float
    # pontos de operação
    ponto_compra: float
    ponto_venda: float
    ponto_medio: float
    sinal: str
    # ano corrente
    maxima_ano: float
    minima_ano: float
    # retornos em %
    retorno_1a: float | None
    retorno_3a: float | None
    retorno_5a: float | None
    # dividendos dos últimos 12 meses
    dividendo_12m: float
    dividend_yield: float
    semanal: pd.DataFrame


def _retorno(serie: pd.Series, anos: int) -> float | None:
    """Retorno total em % entre o pregão mais próximo de N anos atrás e hoje."""
    fim = serie.index[-1]
    inicio_alvo = fim - pd.DateOffset(years=anos)
    # exige histórico que cubra o período (tolerância de 10 dias)
    if serie.index[0] > inicio_alvo + pd.Timedelta(days=10):
        return None
    base = serie[serie.index <= inicio_alvo]
    valor_base = base.iloc[-1] if len(base) else serie.iloc[0]
    if not valor_base:
        return None
    return (serie.iloc[-1] / valor_base - 1) * 100


def calcular(hist: pd.DataFrame, dividendos: pd.Series | None) -> Resultado:
    """hist: histórico diário (colunas High, Low, Close e, se houver, Adj Close)."""
    hist = _sem_fuso(hist).dropna(subset=["High", "Low", "Close"])
    if hist.empty:
        raise ValueError("Sem histórico de preços para este ticker.")

    fim = hist.index[-1]
    preco = float(hist["Close"].iloc[-1])

    # ---- janela de 1 ano
    um_ano = hist[hist.index > fim - pd.DateOffset(years=1)]
    minimo_1a = float(um_ano["Low"].min())
    maximo_1a = float(um_ano["High"].max())
    fechamento_1a = preco

    # ---- 52 semanas: mínima, máxima e fechamento de cada semana
    semanal = (
        um_ano.resample("W-FRI")
        .agg({"Low": "min", "High": "max", "Close": "last"})
        .dropna()
        .tail(52)
    )
    media_min = float(semanal["Low"].mean())
    media_max = float(semanal["High"].mean())
    media_fech = float(semanal["Close"].mean())

    # ---- pontos de compra e venda
    ponto_compra = (media_min + media_fech) / 2
    ponto_venda = (media_max + media_fech) / 2
    ponto_medio = (media_min + media_max) / 2

    if preco <= ponto_compra:
        sinal = "Zona de compra"
    elif preco >= ponto_venda:
        sinal = "Zona de venda"
    else:
        sinal = "Neutro"

    # ---- ano corrente
    do_ano = hist[hist.index >= pd.Timestamp(year=fim.year, month=1, day=1)]
    maxima_ano = float(do_ano["High"].max())
    minima_ano = float(do_ano["Low"].min())

    # ---- retornos (com dividendos reinvestidos quando houver Adj Close)
    serie_ret = hist["Adj Close"] if "Adj Close" in hist else hist["Close"]
    serie_ret = serie_ret.dropna()

    # ---- dividendos 12 meses
    div_12m = 0.0
    if dividendos is not None and len(dividendos):
        d = dividendos.copy()
        if getattr(d.index, "tz", None) is not None:
            d.index = d.index.tz_localize(None)
        div_12m = float(d[d.index > fim - pd.DateOffset(years=1)].sum())
    dy = div_12m / preco * 100 if preco else 0.0

    return Resultado(
        preco_atual=preco,
        data_ultimo=fim,
        minimo_1a=minimo_1a,
        maximo_1a=maximo_1a,
        fechamento_1a=fechamento_1a,
        media_minimas=media_min,
        media_maximas=media_max,
        media_fechamentos=media_fech,
        ponto_compra=ponto_compra,
        ponto_venda=ponto_venda,
        ponto_medio=ponto_medio,
        sinal=sinal,
        maxima_ano=maxima_ano,
        minima_ano=minima_ano,
        retorno_1a=_retorno(serie_ret, 1),
        retorno_3a=_retorno(serie_ret, 3),
        retorno_5a=_retorno(serie_ret, 5),
        dividendo_12m=div_12m,
        dividend_yield=dy,
        semanal=semanal,
    )
