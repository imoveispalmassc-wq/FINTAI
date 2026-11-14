"""Cálculos do FINTAI, separados da interface para poderem ser testados."""
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


def _sem_fuso(obj):
    obj = obj.copy()
    if getattr(obj.index, "tz", None) is not None:
        obj.index = obj.index.tz_localize(None)
    return obj.sort_index()


@dataclass
class Resultado:
    preco_atual: float
    variacao_dia: float | None
    data_ultimo: pd.Timestamp
    # 1 ano (extremos)
    minimo_1a: float
    maximo_1a: float
    fechamento_1a: float
    medio_1a: float
    # médias semanais de 52 semanas
    media_minimas: float
    media_maximas: float
    media_fechamentos: float
    # últimos 30 dias (extremos e médias diárias)
    minimo_30d: float
    maximo_30d: float
    fechamento_30d: float
    medio_30d: float
    media_min_30d: float
    media_max_30d: float
    media_fech_30d: float
    medio_media_30d: float
    # pontos de operação (base: médias de 52 semanas)
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
    fechamentos_1a: pd.Series
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


def pl_medio_12m(fechamentos_1a: pd.Series, lpa_trimestral: pd.Series | None,
                 lpa_atual: float | None) -> tuple[float | None, str | None]:
    """P/L médio dos últimos 12 meses.

    Método "trimestral": a cada pregão, preço ÷ LPA acumulado dos 4 trimestres
    já divulgados até aquela data; depois tira a média.
    Método "simplificado" (quando falta o histórico de lucros): preço médio do
    ano ÷ LPA atual.
    """
    if fechamentos_1a is None or fechamentos_1a.empty:
        return None, None
    try:
        if lpa_trimestral is not None and len(lpa_trimestral.dropna()) >= 4:
            e = _sem_fuso(lpa_trimestral.dropna().astype(float))
            e.index = e.index.normalize()
            e = e[~e.index.duplicated(keep="last")]
            ttm = e.rolling(4).sum().dropna()
            ttm = ttm[ttm.index <= fechamentos_1a.index[-1]]
            cobre = len(ttm) and ttm.index[0] <= fechamentos_1a.index[0] + pd.Timedelta(days=45)
            # o último LPA calculado tem de bater com o informado (moeda, desdobramento)
            coerente = not lpa_atual or lpa_atual <= 0 or 0.6 <= ttm.iloc[-1] / lpa_atual <= 1.6
            if cobre and coerente:
                diario = ttm.reindex(fechamentos_1a.index, method="ffill")
                pl = (fechamentos_1a / diario)[diario > 0].dropna()
                if len(pl) >= 0.6 * len(fechamentos_1a):
                    return float(pl.mean()), "trimestral"
    except Exception:
        pass
    if lpa_atual and lpa_atual > 0:
        return float(fechamentos_1a.mean() / lpa_atual), "simplificado"
    return None, None


def calcular(hist: pd.DataFrame, dividendos: pd.Series | None) -> Resultado:
    """hist: histórico diário (colunas High, Low, Close e, se houver, Adj Close)."""
    hist = _sem_fuso(hist).dropna(subset=["High", "Low", "Close"])
    if hist.empty:
        raise ValueError("Sem histórico de preços para este ticker.")

    fim = hist.index[-1]
    preco = float(hist["Close"].iloc[-1])
    variacao = None
    if len(hist) > 1 and hist["Close"].iloc[-2]:
        variacao = (preco / float(hist["Close"].iloc[-2]) - 1) * 100

    # ---- janela de 1 ano
    um_ano = hist[hist.index > fim - pd.DateOffset(years=1)]
    minimo_1a = float(um_ano["Low"].min())
    maximo_1a = float(um_ano["High"].max())

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

    # ---- últimos 30 dias corridos
    d30 = hist[hist.index > fim - pd.Timedelta(days=30)]
    minimo_30d = float(d30["Low"].min())
    maximo_30d = float(d30["High"].max())
    media_min_30d = float(d30["Low"].mean())
    media_max_30d = float(d30["High"].mean())
    media_fech_30d = float(d30["Close"].mean())

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

    # ---- retornos (com dividendos reinvestidos quando houver Adj Close)
    serie_ret = hist["Adj Close"] if "Adj Close" in hist else hist["Close"]
    serie_ret = serie_ret.dropna()

    # ---- dividendos 12 meses
    div_12m = 0.0
    if dividendos is not None and len(dividendos):
        d = _sem_fuso(dividendos)
        div_12m = float(d[d.index > fim - pd.DateOffset(years=1)].sum())
    dy = div_12m / preco * 100 if preco else 0.0

    return Resultado(
        preco_atual=preco,
        variacao_dia=variacao,
        data_ultimo=fim,
        minimo_1a=minimo_1a,
        maximo_1a=maximo_1a,
        fechamento_1a=preco,
        medio_1a=(minimo_1a + maximo_1a) / 2,
        media_minimas=media_min,
        media_maximas=media_max,
        media_fechamentos=media_fech,
        minimo_30d=minimo_30d,
        maximo_30d=maximo_30d,
        fechamento_30d=preco,
        medio_30d=(minimo_30d + maximo_30d) / 2,
        media_min_30d=media_min_30d,
        media_max_30d=media_max_30d,
        media_fech_30d=media_fech_30d,
        medio_media_30d=(media_min_30d + media_max_30d) / 2,
        ponto_compra=ponto_compra,
        ponto_venda=ponto_venda,
        ponto_medio=ponto_medio,
        sinal=sinal,
        maxima_ano=float(do_ano["High"].max()),
        minima_ano=float(do_ano["Low"].min()),
        retorno_1a=_retorno(serie_ret, 1),
        retorno_3a=_retorno(serie_ret, 3),
        retorno_5a=_retorno(serie_ret, 5),
        dividendo_12m=div_12m,
        dividend_yield=dy,
        fechamentos_1a=um_ano["Close"],
        semanal=semanal,
    )
