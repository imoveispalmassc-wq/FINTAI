"""Monta, a partir dos dados do Yahoo Finance, o pacote único que a tela de detalhes lê.

Fonte única de verdade: cada indicador é calculado uma vez aqui e todas as seções da tela
usam o mesmo valor. O que faltar vai como None e a tela mostra "Dados indisponíveis".
"""
from __future__ import annotations

import math

import pandas as pd

from calculos import (Resultado, crescimento_lpa, dy_atual_e_medio, pl_medio_12m,
                      pl_medio_longo, preco_justo_graham, preco_teto_bazin)
from utils.signals import (backtest_percentil, decidir_estado, fundamento_quebrou,
                           selo_backtest)

SIMBOLO = {"BRL": "R$", "USD": "US$", "EUR": "€", "GBP": "£"}
ROTULO_PERIODOS = ["1 ano", "3 anos", "5 anos"]


def _n(v, casas: int = 6):
    """Número seguro para JSON: None no lugar de ausente, NaN ou infinito."""
    if v is None:
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) or math.isinf(v) else round(v, casas)


def _sem_fuso(df):
    df = df.copy()
    if getattr(df.index, "tz", None) is not None:
        df.index = df.index.tz_localize(None)   # mantém o horário local da bolsa
    return df.sort_index()


def _serie(df: pd.DataFrame, rot: str, variacao: str, base=None, **extra) -> dict | None:
    """Série do gráfico. Os instantes vão como horário local da bolsa tratado como UTC."""
    if df is None or df.empty:
        return None
    df = _sem_fuso(df).dropna(subset=["Close"])
    if len(df) < 2:
        return None
    t = ((df.index - pd.Timestamp(0)) // pd.Timedelta(milliseconds=1)).tolist()
    col = lambda nome: [_n(x, 4) for x in df[nome]]
    vol = df["Volume"].fillna(0) if "Volume" in df else pd.Series(0, index=df.index)
    return {"t": t, "o": col("Open"), "h": col("High"), "l": col("Low"), "c": col("Close"),
            "v": [_n(x, 0) or 0 for x in vol], "rot": rot, "variacao": variacao,
            "base": _n(base, 4), **extra}


def series_do_grafico(hist: pd.DataFrame, intraday: dict) -> dict:
    h = _sem_fuso(hist).dropna(subset=["Close"])
    fim = h.index[-1]
    regra = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    anterior = h["Close"].iloc[-2] if len(h) > 1 else None

    def desde(anos):
        """Do último pregão até `anos` atrás, incluindo o fechamento-base (o mesmo que o
        cálculo de retorno usa), para gráfico e retorno darem o mesmo número."""
        antes = h[h.index <= fim - pd.DateOffset(years=anos)]
        return h[h.index >= antes.index[-1]] if len(antes) else h

    um_ano = desde(1)
    cinco_d = desde(5)
    cinco = cinco_d.resample("W-FRI").agg(regra).dropna(subset=["Close"])
    tudo = h.resample("MS").agg(regra).dropna(subset=["Close"])
    return {
        "hoje": _serie(intraday.get("hoje"), "hora", "no dia", base=anterior),
        "1s": _serie(intraday.get("1s"), "dia", "em 7 dias"),
        "1m": _serie(intraday.get("1m"), "dia", "em 30 dias"),
        "1a": _serie(um_ano, "mes", "em 12 meses", casas=1, soPreco=True),
        "5a": _serie(cinco, "ano", "em 5 anos", base=cinco_d["Close"].iloc[0]),
        "max": _serie(tudo, "ano", "em todo o histórico"),
    }


def fundamentos(d: dict, r: Resultado) -> dict:
    """Indicadores fundamentalistas, calculados uma única vez."""
    info, hist, lpa_tri = d["info"], _sem_fuso(d["hist"]), d["lpa_tri"]
    preco, fim = r.preco_atual, r.data_ultimo
    lpa = info.get("trailingEps") or info.get("epsTrailingTwelveMonths")
    pl = preco / lpa if lpa and lpa > 0 else None       # sempre preço ÷ LPA, para as contas baterem
    splits = hist["Stock Splits"] if "Stock Splits" in hist else None
    pl_medio, metodo = pl_medio_12m(r.fechamentos_1a, lpa_tri, lpa, splits)
    pl_hist, anos_hist = pl_medio_longo(hist["Close"], lpa_tri, lpa, splits)
    lpa_agora, lpa_antes, base_lpa = crescimento_lpa(lpa_tri, d["lpa_anual"])

    prov = hist["Dividends"][hist["Dividends"] > 0] if "Dividends" in hist else pd.Series(dtype=float)
    soma = lambda a, b: float(prov[(prov.index > fim - pd.DateOffset(years=a)) & (prov.index <= fim - pd.DateOffset(years=b))].sum())
    div12, div12_antes = soma(1, 0), soma(2, 1)
    cobre_5 = hist.index[0] <= fim - pd.DateOffset(years=5) + pd.Timedelta(days=10)
    dy = div12 / preco * 100 if preco else None
    _, dy_medio = dy_atual_e_medio(hist)
    bazin, div_medio5 = preco_teto_bazin(prov, hist.index[0], fim)
    vpa = info.get("bookValue")

    divida, caixa, ebitda = info.get("totalDebt"), info.get("totalCash"), info.get("ebitda")
    dl_ebitda = (divida - (caixa or 0)) / ebitda if divida is not None and ebitda and ebitda > 0 else None
    return dict(
        pl=pl, pl_medio=pl_medio, metodo=metodo, lpa=lpa,
        lpa_agora=lpa_agora, lpa_antes=lpa_antes, base_lpa=base_lpa,
        div=div12, div_antes=div12_antes, dy=dy, dy_medio=dy_medio,
        div5=soma(5, 0) if cobre_5 else None,
        acoes=info.get("sharesOutstanding") or info.get("impliedSharesOutstanding"),
        vpa=vpa, graham=preco_justo_graham(lpa, vpa), bazin=bazin, div_medio5=div_medio5,
        pl_hist=pl_hist, anos_hist=anos_hist,
        justo_pl=pl_hist * lpa if pl_hist and lpa and lpa > 0 else None,
        dl_ebitda=dl_ebitda,
        lucros=d["lucro_tri"] if d["lucro_tri"] is not None else lpa_tri,
    )


def _backtest(hist, anos, nome):
    try:
        b = backtest_percentil(hist, anos)
    except Exception:
        return None
    ref = b["referencia"]
    if not ref["casos"]:
        return None
    lado = lambda s: {"vezes": s["casos"], "retorno": _n(s["retorno_12m"], 2), "acerto": _n(s["acerto_12m"], 1)}
    return {
        "anos": _n(b["anos"], 2), "insuficiente": bool(b["insuficiente"]),
        "oportunidade": lado(b["compra"]), "cara": lado(b["venda"]),
        "referencia": {"retorno": _n(ref["retorno_12m"], 2), "subiu": _n(ref["acerto_12m"], 1)},
        "compraValidada": selo_backtest("compra", b["compra"]["acerto_12m"], b["compra"]["retorno_12m"],
                                        ref["retorno_12m"], b["compra"]["casos"], nome).validado,
        "vendaValidada": selo_backtest("venda", b["venda"]["acerto_12m"], b["venda"]["retorno_12m"],
                                       ref["retorno_12m"], b["venda"]["casos"], nome).validado,
    }


def montar(ticker: str, d: dict, r: Resultado, comparadores: dict, padrao: str) -> dict:
    """Pacote completo da tela para um ticker."""
    info, hist = d["info"], d["hist"]
    cod = info.get("currency") or ("BRL" if ticker.endswith(".SA") else "USD")
    moeda = SIMBOLO.get(cod, cod)
    curto = ticker[:-3] if ticker.endswith(".SA") else ticker
    f = fundamentos(d, r)

    bt5, btmax = _backtest(hist, 5, curto), _backtest(hist, None, curto)
    quebrou, motivo = fundamento_quebrou(f["lucros"], f["dl_ebitda"])
    estado = decidir_estado(
        r.percentil, r.minimo_1a, r.maximo_1a,
        compra_validada=bool(bt5 and bt5["compraValidada"]),
        venda_validada=bool(bt5 and bt5["vendaValidada"]),
        quebrou=quebrou, motivo_quebra=motivo, simbolo=moeda,
        preco=r.preco_atual, tendencia=r.tendencia)

    after = None
    if info.get("postMarketPrice") and info.get("postMarketChangePercent") is not None:
        hora = ""
        try:
            fuso = info.get("exchangeTimezoneName") or "America/New_York"
            hora = f"{pd.Timestamp(info['postMarketTime'], unit='s', tz='UTC').tz_convert(fuso):%H:%M}"
        except Exception:
            pass
        after = {"preco": _n(info["postMarketPrice"], 4), "variacao": _n(info["postMarketChangePercent"], 2),
                 "hora": hora}

    series = series_do_grafico(hist, d.get("intraday") or {})
    um_ano = series["1a"]
    agora = pd.Timestamp.now(tz="America/Sao_Paulo")
    return {
        "ticker": curto, "nome": info.get("shortName") or info.get("longName") or curto,
        "razao": info.get("longName") or info.get("shortName") or curto,
        "bolsa": info.get("fullExchangeName") or info.get("exchange") or "",
        "moeda": moeda, "codMoeda": cod, "fonte": "Yahoo Finance",
        "data": f"{r.data_ultimo:%d/%m/%Y}", "atualizado": f"{agora:%d/%m/%Y} às {agora:%H:%M}",
        "preco": _n(r.preco_atual, 4), "varDia": _n(r.variacao_dia, 2), "after": after,
        "min52": _n(r.minimo_1a, 4), "max52": _n(r.maximo_1a, 4),
        "min30": _n(r.minimo_30d, 4), "max30": _n(r.maximo_30d, 4),
        "mm200": _n(r.mm200, 4), "tendencia": r.tendencia, "forca": _n(r.ifr, 0),
        "pl": _n(f["pl"], 4), "plMedio12": _n(f["pl_medio"], 4), "plMetodo": f["metodo"],
        "lpa": _n(f["lpa"], 4), "lpaAgora": _n(f["lpa_agora"], 4), "lpa12Atras": _n(f["lpa_antes"], 4),
        "baseLpa": f["base_lpa"],
        "dividendo": _n(f["div"], 4), "dividendo12Atras": _n(f["div_antes"], 4),
        "dyMedio12": _n(f["dy_medio"], 4), "dividendos5Anos": _n(f["div5"], 4),
        "acoes": _n(f["acoes"], 0), "vpa": _n(f["vpa"], 4),
        "plHistorico": _n(f["pl_hist"], 4), "plHistAnos": _n(f["anos_hist"], 1),
        "graham": _n(f["graham"], 4), "justoPL": _n(f["justo_pl"], 4),
        "bazin": _n(f["bazin"], 4), "divMedio5": _n(f["div_medio5"], 4),
        "retorno": {"periodos": ROTULO_PERIODOS,
                    "total": [_n(x, 2) for x in (r.retorno_1a, r.retorno_3a, r.retorno_5a)],
                    "preco": [_n(x, 2) for x in (r.retorno_preco_1a, r.retorno_preco_3a, r.retorno_preco_5a)]},
        "preco1AnoAtras": um_ano["c"][0] if um_ano else None,
        "data1AnoAtras": f"{pd.Timestamp(um_ano['t'][0], unit='ms'):%d/%m/%Y}" if um_ano else None,
        "comparadores": comparadores, "comparadorPadrao": padrao,
        "backtest": {"5a": bt5, "max": btmax},
        "decisao": {"codigo": estado.codigo, "rotulo": estado.rotulo, "texto": estado.texto, "zona": estado.zona},
        "series": series,
    }
