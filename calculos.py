"""Cálculos do FINTAI, separados da interface para poderem ser testados."""
from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
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
    zona: str            # só pelo preço: Zona de compra / Zona de venda / Neutro
    sinal: str           # preço + tendência: Compra / Aguardar / Venda / Manter / Neutro
    # tendência e força
    mm200: float | None
    inclinacao_mm200: float | None   # variação % da MM200 em ~3 meses
    ifr: float | None
    tendencia: str       # Alta / Baixa / Lateral / —
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


def _pl_diario(fechamentos: pd.Series, lpa_trimestral: pd.Series | None,
               lpa_atual: float | None, desdobramentos: pd.Series | None) -> pd.Series | None:
    """P/L de cada pregão: preço ÷ LPA acumulado dos 4 trimestres já divulgados na data."""
    if lpa_trimestral is None or len(lpa_trimestral.dropna()) < 4:
        return None
    e = _sem_fuso(lpa_trimestral.dropna().astype(float))
    e.index = e.index.normalize()
    e = e[~e.index.duplicated(keep="last")]
    ttm = e.rolling(4).sum().dropna()
    ttm = ttm[ttm.index <= fechamentos.index[-1]]
    if ttm.empty:
        return None
    # o último LPA calculado tem de bater com o informado (moeda, ADR, desdobramento)
    if lpa_atual and lpa_atual > 0 and not 0.6 <= ttm.iloc[-1] / lpa_atual <= 1.6:
        return None
    diario = ttm.reindex(fechamentos.index, method="ffill")
    pl = (fechamentos / diario)[diario > 0].dropna()
    pl = pl[pl <= 150]  # lucro quase zero distorce a média
    if pl.empty:
        return None
    # desdobramento no período deixa lucros antigos em outra base: não confiar
    if desdobramentos is not None and len(desdobramentos):
        d = _sem_fuso(desdobramentos)
        if (d[d.index > pl.index[0]] != 0).any():
            return None
    return pl


def pl_medio_12m(fechamentos_1a: pd.Series, lpa_trimestral: pd.Series | None,
                 lpa_atual: float | None, desdobramentos: pd.Series | None = None
                 ) -> tuple[float | None, str | None]:
    """P/L médio dos últimos 12 meses.

    "trimestral": média do P/L de cada pregão, com o LPA divulgado até a data.
    "simplificado" (sem histórico de lucros): preço médio do ano ÷ LPA atual.
    """
    if fechamentos_1a is None or fechamentos_1a.empty:
        return None, None
    try:
        pl = _pl_diario(fechamentos_1a, lpa_trimestral, lpa_atual, desdobramentos)
        if pl is not None and len(pl) >= 0.6 * len(fechamentos_1a):
            return float(pl.mean()), "trimestral"
    except Exception:
        pass
    if lpa_atual and lpa_atual > 0:
        return float(fechamentos_1a.mean() / lpa_atual), "simplificado"
    return None, None


def pl_medio_longo(fechamentos: pd.Series, lpa_trimestral: pd.Series | None,
                   lpa_atual: float | None, desdobramentos: pd.Series | None = None,
                   anos: int = 5) -> tuple[float | None, float | None]:
    """P/L médio de até `anos` anos. Devolve (média, anos cobertos); exige 2 anos de dados."""
    try:
        f = _sem_fuso(fechamentos).dropna()
        f = f[f.index > f.index[-1] - pd.DateOffset(years=anos)]
        pl = _pl_diario(f, lpa_trimestral, lpa_atual, desdobramentos)
        if pl is not None and len(pl) >= 504:
            return float(pl.mean()), len(pl) / 252
    except Exception:
        pass
    return None, None


# ------------------------------------------------------------ tendência
def indicadores(hist: pd.DataFrame) -> pd.DataFrame:
    """MM200, inclinação da MM200 em 63 pregões (~3 meses) e IFR de 14 dias (Wilder)."""
    c = hist["Close"]
    mm200 = c.rolling(200).mean()
    delta = c.diff()
    ganho = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    perda = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    ifr = 100 - 100 / (1 + ganho / perda.replace(0, np.nan))
    ifr = ifr.where(perda != 0, 100.0).where(ganho.notna())
    return pd.DataFrame({"mm200": mm200, "incl": (mm200 / mm200.shift(63) - 1) * 100, "ifr": ifr})


def classificar(preco, compra, venda, mm200, incl, ifr):
    """Regras do sinal (aceita números ou séries). Devolve (tendência, zona, sinal).

    Tendência: Alta = MM200 subindo (>1% em 3 meses) e preço acima dela;
               Baixa = MM200 caindo (<-1%) e preço abaixo dela; senão Lateral.
    Compra: preço <= ponto de compra e tendência não é de Baixa (senão: Aguardar).
    Venda:  preço >= ponto de venda, exceto em Alta com IFR < 70 (aí: Manter).
    """
    preco, compra, venda, mm200, incl, ifr = (
        np.asarray(x, dtype=float) for x in (preco, compra, venda, mm200, incl, ifr))
    alta = (incl > 1) & (preco > mm200)
    baixa = (incl < -1) & (preco < mm200)
    tendencia = np.select([np.isnan(mm200) | np.isnan(incl), alta, baixa],
                          ["—", "Alta", "Baixa"], "Lateral")
    barato, caro = preco <= compra, preco >= venda
    zona = np.select([barato, caro], ["Zona de compra", "Zona de venda"], "Neutro")
    forte = alta & ~(ifr >= 70)  # em alta e ainda não sobrecomprado
    sinal = np.select([barato & baixa, barato, caro & forte, caro],
                      ["Aguardar", "Compra", "Manter", "Venda"], "Neutro")
    return tendencia, zona, sinal


# ------------------------------------------------------------ backtest
def backtest(hist: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Aplica as regras semana a semana no histórico, só com dados conhecidos em cada data,
    e mede o retorno 6 e 12 meses depois de cada sinal."""
    h = _sem_fuso(hist).dropna(subset=["High", "Low", "Close"])
    adj = (h["Adj Close"] if "Adj Close" in h else h["Close"]).ffill()
    ind = indicadores(h)
    w = h.resample("W-FRI").agg({"Low": "min", "High": "max", "Close": "last"})
    w["adj"] = adj.resample("W-FRI").last()
    for col in ind:
        w[col] = ind[col].resample("W-FRI").last()
    w = w.dropna(subset=["Close"])
    m_min, m_max, m_fech = (w[c].rolling(52).mean() for c in ("Low", "High", "Close"))
    compra, venda = (m_min + m_fech) / 2, (m_max + m_fech) / 2
    _, zona, sinal = classificar(w["Close"], compra, venda, w["mm200"], w["incl"], w["ifr"])
    valido = compra.notna().to_numpy()
    r6 = (w["adj"].shift(-26) / w["adj"] - 1).to_numpy() * 100
    r12 = (w["adj"].shift(-52) / w["adj"] - 1).to_numpy() * 100

    def linha(nome, mascara):
        m = mascara & valido
        a, b = r6[m & ~np.isnan(r6)], r12[m & ~np.isnan(r12)]
        return {
            "Situação": nome, "Semanas": int(len(a)),
            "Retorno 6m": a.mean() if len(a) else None,
            "Acerto 6m": (a > 0).mean() * 100 if len(a) else None,
            "Retorno 12m": b.mean() if len(b) else None,
            "Acerto 12m": (b > 0).mean() * 100 if len(b) else None,
            "_n12": int(len(b)),
        }

    linhas = [
        linha("Sinal de compra", sinal == "Compra"),
        linha("Zona de compra, sem filtro", zona == "Zona de compra"),
        linha("Sinal de venda", sinal == "Venda"),
        linha("Zona de venda, sem filtro", zona == "Zona de venda"),
        linha("Qualquer semana (referência)", np.ones(len(w), dtype=bool)),
    ]
    tabela = pd.DataFrame(linhas).set_index("Situação")
    ref = tabela.loc["Qualquer semana (referência)"]

    def veredito(nome, melhor_se_maior):
        l = tabela.loc[nome]
        if l["_n12"] < 8 or ref["Retorno 12m"] is None or pd.isna(ref["Retorno 12m"]):
            return "poucos"
        dif = l["Retorno 12m"] - ref["Retorno 12m"]
        if not melhor_se_maior:
            dif = -dif
        return "ajudou" if dif > 2 else "atrapalhou" if dif < -2 else "indiferente"

    anos = (w.index[valido][-1] - w.index[valido][0]).days / 365.25 if valido.any() else 0
    resumo = {
        "compra": veredito("Sinal de compra", True),
        "venda": veredito("Sinal de venda", False),
        "anos": anos,
    }
    return tabela, resumo


# ------------------------------------------------------------ preço justo
def preco_teto_bazin(dividendos: pd.Series | None, inicio_hist: pd.Timestamp,
                     fim: pd.Timestamp, taxa: float = 0.06) -> tuple[float | None, float | None]:
    """Bazin: dividendo médio anual (até 3 anos) ÷ 6%. Devolve (preço-teto, dividendo médio)."""
    if dividendos is None or not len(dividendos):
        return None, None
    d = _sem_fuso(dividendos)
    somas = []
    for k in range(3):
        a, b = fim - pd.DateOffset(years=k + 1), fim - pd.DateOffset(years=k)
        if a < inicio_hist - pd.Timedelta(days=10):
            break
        somas.append(float(d[(d.index > a) & (d.index <= b)].sum()))
    if not somas or sum(somas) <= 0:
        return None, None
    media = sum(somas) / len(somas)
    return media / taxa, media


def preco_justo_graham(lpa: float | None, vpa: float | None) -> float | None:
    """Graham: raiz de (22,5 × LPA × VPA). Só vale com lucro e patrimônio positivos."""
    if lpa and vpa and lpa > 0 and vpa > 0:
        return float((22.5 * lpa * vpa) ** 0.5)
    return None


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

    ind = indicadores(hist).iloc[-1]
    tendencia, zona, sinal = (str(x) for x in classificar(
        preco, ponto_compra, ponto_venda, ind["mm200"], ind["incl"], ind["ifr"]))

    def _ou_none(v):
        return None if pd.isna(v) else float(v)

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
        zona=zona,
        sinal=sinal,
        mm200=_ou_none(ind["mm200"]),
        inclinacao_mm200=_ou_none(ind["incl"]),
        ifr=_ou_none(ind["ifr"]),
        tendencia=tendencia,
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
