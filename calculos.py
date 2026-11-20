"""Cálculos do FINTAI, separados da interface para poderem ser testados."""
from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
import pandas as pd

from utils.percentile import percentil_na_faixa

# PETR4, VALE3, BOVA11, TAEE11, SANB11 ... => ação/FII/ETF da B3
_PADRAO_B3 = re.compile(r"^(?=.*[A-Z])[A-Z0-9]{4}\d{1,2}[A-Z]?$")   # B3SA3: dígito dentro do próprio código


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
    ponto_medio: float   # ponto médio das médias de 52 semanas (linha da tabela)
    percentil: float     # posição do preço na faixa de 52 semanas, 0 a 100
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
    # só preço, sem dividendos
    retorno_preco_1a: float | None
    retorno_preco_3a: float | None
    retorno_preco_5a: float | None
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


TOLERANCIA_BASE_LPA = 0.10   # diferença máxima entre a série trimestral e o LPA de 12 meses


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
    # O LPA trimestral do Yahoo (earnings dates) pode vir em outra base que o LPA de 12 meses
    # (ex.: lucro AJUSTADO do banco contra lucro CONTÁBIL). Se o último valor da série não bate com o
    # LPA atual em até 10%, as bases são diferentes e comparar os dois P/L seria comparar coisas diferentes.
    if lpa_atual and lpa_atual > 0 and not (1 - TOLERANCIA_BASE_LPA) <= ttm.iloc[-1] / lpa_atual <= (1 + TOLERANCIA_BASE_LPA):
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


def lpa_contabil_ttm(lucro_tri: pd.Series | None, lpa_anual: pd.Series | None, acoes: float | None,
                     lpa_atual: float | None, datas_resultado=None) -> pd.Series | None:
    """LPA contábil de 12 meses em vigor a partir de cada balanço: série (data de divulgação -> LPA).

    Monta o lucro por ação de cada trimestre com o lucro líquido trimestral do Yahoo ÷ ações.
    Trimestre que falta sai do balanço anual (ano − os outros 3) ou, o mais recente, do LPA de 12
    meses (LPA atual − os 3 anteriores). Só devolve a série se o último valor bater com o LPA atual."""
    if lucro_tri is None or not acoes or acoes <= 0 or not lpa_atual or lpa_atual <= 0:
        return None
    q = _sem_fuso(lucro_tri.dropna().astype(float)) / acoes
    if q.empty:
        return None
    q.index = q.index.to_period("Q")
    q = q[~q.index.duplicated(keep="last")].to_dict()
    if lpa_anual is not None:
        for fim, valor in _sem_fuso(lpa_anual.dropna().astype(float)).items():
            tri = [pd.Timestamp(fim).to_period("Q") - k for k in range(4)]
            faltam = [t for t in tri if t not in q]
            if len(faltam) == 1:
                q[faltam[0]] = float(valor) - sum(q[t] for t in tri if t in q)
    datas = sorted(_sem_fuso(pd.Series(1, index=pd.DatetimeIndex(datas_resultado))).index) if datas_resultado is not None and len(datas_resultado) else []
    # balanço mais novo já divulgado e ainda fora do demonstrativo trimestral
    if datas:
        ult = max(q)
        novo = ult + 1
        if novo.end_time < datas[-1] <= novo.end_time + pd.Timedelta(days=120) and all(novo - k in q for k in (1, 2, 3)):
            q[novo] = lpa_atual - sum(q[novo - k] for k in (1, 2, 3))

    def divulgado(per):
        fim = per.end_time.normalize()
        prox = [t for t in datas if fim < t <= fim + pd.Timedelta(days=120)]
        return prox[0].normalize() if prox else fim + pd.Timedelta(days=45)

    pontos = {}
    for per in sorted(q):
        if all(per - k in q for k in range(4)):
            pontos[divulgado(per)] = sum(q[per - k] for k in range(4))
    if not pontos:
        return None
    serie = pd.Series(pontos).sort_index()
    if not (1 - TOLERANCIA_BASE_LPA) <= serie.iloc[-1] / lpa_atual <= (1 + TOLERANCIA_BASE_LPA):
        return None
    return serie


def pl_medio_contabil(fechamentos_1a: pd.Series, ttm: pd.Series | None, minimo: float = 0.5) -> dict | None:
    """P/L médio do último ano com o LPA contábil em vigor em cada pregão.

    Só usa os dias cobertos por algum balanço; exige `minimo` do ano coberto."""
    if ttm is None or fechamentos_1a is None or fechamentos_1a.empty:
        return None
    f = _sem_fuso(fechamentos_1a.dropna())
    lpa = ttm.reindex(ttm.index.union(f.index)).ffill().reindex(f.index)
    ok = lpa.notna() & (lpa > 0)
    if ok.sum() < minimo * len(f):
        return None
    pl = (f[ok] / lpa[ok])
    pl = pl[pl <= 150]
    if pl.empty:
        return None
    precos = f[pl.index]
    return {"pl": float(pl.mean()), "preco_medio": float(precos.mean()), "desde": pl.index[0],
            "meses": len(pl) / len(f) * 12}


def media_no_periodo(fechamentos_1a: pd.Series, ttm: pd.Series | None, minimo: float = 0.5) -> float | None:
    """Média de uma série de 12 meses (ex.: receita) em vigor nos pregões do último ano, só nos dias cobertos."""
    if ttm is None or fechamentos_1a is None or fechamentos_1a.empty:
        return None
    dias = _sem_fuso(fechamentos_1a.dropna()).index
    v = ttm.reindex(ttm.index.union(dias)).ffill().reindex(dias).dropna()
    if len(v) < minimo * len(dias):
        return None
    return float(v.mean())


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


def tendencia(preco: float, mm200: float | None, inclinacao: float | None) -> str:
    """Alta = MM200 subindo (>1% em 3 meses) e preço acima dela;
    Baixa = MM200 caindo (<-1%) e preço abaixo dela; senão Lateral."""
    if mm200 is None or inclinacao is None or pd.isna(mm200) or pd.isna(inclinacao):
        return "—"
    if inclinacao > 1 and preco > mm200:
        return "Alta"
    if inclinacao < -1 and preco < mm200:
        return "Baixa"
    return "Lateral"


# ------------------------------------------------------------ fundamentos
def dy_atual_e_medio(hist: pd.DataFrame) -> tuple[float | None, float | None]:
    """Dividend yield de hoje e a média do DY diário dos últimos 12 meses.

    DY de cada dia = proventos pagos nos 365 dias anteriores ÷ preço do dia."""
    if "Dividends" not in hist:
        return None, None
    h = _sem_fuso(hist)
    pagos = h["Dividends"].fillna(0).rolling("365D").sum()
    dy = (pagos / h["Close"] * 100).dropna()
    if dy.empty:
        return None, None
    ano = dy[dy.index > dy.index[-1] - pd.DateOffset(years=1)]
    # sem um ano inteiro de proventos antes da janela, a média ficaria subestimada
    if h.index[0] > ano.index[0] - pd.Timedelta(days=360):
        return float(dy.iloc[-1]), None
    return float(dy.iloc[-1]), float(ano.mean())


def crescimento_lpa(lpa_trimestral: pd.Series | None, lpa_anual: pd.Series | None
                    ) -> tuple[float | None, float | None, str]:
    """LPA atual e o de 12 meses antes. Devolve (atual, anterior, base usada).

    Preferência: soma dos 4 últimos trimestres contra os 4 anteriores.
    Sem 8 trimestres, usa os dois últimos anos fiscais."""
    if lpa_trimestral is not None:
        e = _sem_fuso(lpa_trimestral.dropna().astype(float))
        e = e[~e.index.duplicated(keep="last")]
        if len(e) >= 8:
            return float(e.iloc[-4:].sum()), float(e.iloc[-8:-4].sum()), "últimos 4 trimestres"
    if lpa_anual is not None:
        a = _sem_fuso(lpa_anual.dropna().astype(float))
        if len(a) >= 2:
            return float(a.iloc[-1]), float(a.iloc[-2]), "último ano fiscal"
    return None, None, ""


# ------------------------------------------------------------ preço justo
def preco_teto_bazin(dividendos: pd.Series | None, inicio_hist: pd.Timestamp,
                     fim: pd.Timestamp, taxa: float = 0.06, anos: int = 5
                     ) -> tuple[float | None, float | None]:
    """Bazin: dividendo médio anual (até 5 anos) ÷ 6%. Devolve (preço-teto, dividendo médio)."""
    if dividendos is None or not len(dividendos):
        return None, None
    d = _sem_fuso(dividendos)
    somas = []
    for k in range(anos):
        a, b = fim - pd.DateOffset(years=k + 1), fim - pd.DateOffset(years=k)
        if a < inicio_hist - pd.Timedelta(days=10):
            break
        somas.append(float(d[(d.index > a) & (d.index <= b)].sum()))
    if not somas or sum(somas) <= 0:
        return None, None
    media = sum(somas) / len(somas)
    return media / taxa, media


def graham_duas_versoes(lpa_ttm: float | None, lpa_media_3a: float | None,
                        vpa: float | None) -> dict:
    """Graham com o lucro dos últimos 12 meses e com o lucro médio de 3 anos.

    Graham_atual = √(22,5 × LPA_TTM × VPA)        (não existe se LPA_TTM <= 0)
    Graham_media = √(22,5 × LPA_medio_3a × VPA)   (não existe sem média; regra de prejuízo)
    Graham_usado = o MENOR dos dois; se só um existir, esse.
    Aviso quando LPA_TTM < 60% da média de 3 anos: o valor pode estar otimista.
    """
    atual = preco_justo_graham(lpa_ttm, vpa)
    media = preco_justo_graham(lpa_media_3a, vpa)
    if atual is not None and media is not None:
        usado, base = (atual, "atual") if atual <= media else (media, "media")
    elif atual is not None:
        usado, base = atual, "atual"
    elif media is not None:
        usado, base = media, "media"
    else:
        usado, base = None, None
    aviso = (lpa_ttm is not None and lpa_media_3a is not None and lpa_media_3a > 0
             and lpa_ttm < lpa_media_3a * 0.60)
    return {"atual": atual, "media": media, "usado": usado, "base": base, "aviso": bool(aviso)}


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

    ponto_medio = (media_min + media_max) / 2

    ind = indicadores(hist).iloc[-1]

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
        ponto_medio=ponto_medio,
        percentil=percentil_na_faixa(preco, minimo_1a, maximo_1a),
        mm200=_ou_none(ind["mm200"]),
        inclinacao_mm200=_ou_none(ind["incl"]),
        ifr=_ou_none(ind["ifr"]),
        tendencia=tendencia(preco, _ou_none(ind["mm200"]), _ou_none(ind["incl"])),
        maxima_ano=float(do_ano["High"].max()),
        minima_ano=float(do_ano["Low"].min()),
        retorno_1a=_retorno(serie_ret, 1),
        retorno_3a=_retorno(serie_ret, 3),
        retorno_5a=_retorno(serie_ret, 5),
        retorno_preco_1a=_retorno(hist["Close"], 1),
        retorno_preco_3a=_retorno(hist["Close"], 3),
        retorno_preco_5a=_retorno(hist["Close"], 5),
        dividendo_12m=div_12m,
        dividend_yield=dy,
        fechamentos_1a=um_ano["Close"],
        semanal=semanal,
    )
retorno_periodo = _retorno
