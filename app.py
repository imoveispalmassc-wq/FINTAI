"""FINTAI: dashboard de ações (EUA e Brasil).

Rodar:  streamlit run app.py
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

from calculos import Resultado, calcular, normalizar_ticker

st.set_page_config(page_title="FINTAI", page_icon="📈", layout="wide")

VERDE, VERMELHO, AZUL, CINZA = "#1f9d6b", "#d64545", "#2f6fdb", "#8a94a6"
SIMBOLO = {"BRL": "R$", "USD": "US$", "EUR": "€", "GBP": "£"}


# ------------------------------------------------------------ formatação
def num(v, casas=2):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    s = f"{v:,.{casas}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def dinheiro(v, moeda):
    return "—" if v is None else f"{SIMBOLO.get(moeda, moeda)} {num(v)}"


def pct(v):
    return "—" if v is None else f"{'+' if v > 0 else ''}{num(v)}%"


def quantidade(v):
    if not v:
        return "—"
    for lim, suf in ((1e12, "tri"), (1e9, "bi"), (1e6, "mi")):
        if v >= lim:
            return f"{num(v / lim)} {suf}"
    return num(v, 0)


# ------------------------------------------------------------ dados
@st.cache_data(ttl=900, show_spinner=False)
def baixar(ticker: str):
    tk = yf.Ticker(ticker)
    hist = tk.history(period="5y", interval="1d", auto_adjust=False)
    if hist is None or hist.empty:
        raise ValueError(f"Não encontrei dados para {ticker}. Confira o código.")
    try:
        info = tk.info or {}
    except Exception:
        info = {}
    try:
        divs = tk.dividends
    except Exception:
        divs = pd.Series(dtype=float)
    return hist, divs, info


def fundamentos(info: dict, r: Resultado):
    lpa = info.get("trailingEps") or info.get("epsTrailingTwelveMonths")
    pl = info.get("trailingPE")
    if pl is None and lpa:
        pl = r.preco_atual / lpa if lpa > 0 else None
    acoes = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding")
    div = r.dividendo_12m
    dy = r.dividend_yield
    if not div and info.get("dividendRate"):  # sem histórico, usa o informado
        div = float(info["dividendRate"])
        dy = div / r.preco_atual * 100
    return pl, lpa, acoes, div, dy


# ------------------------------------------------------------ gráficos
def grafico_preco(hist: pd.DataFrame, r: Resultado, moeda: str):
    h = hist.copy()
    if getattr(h.index, "tz", None) is not None:
        h.index = h.index.tz_localize(None)
    h = h[h.index > h.index[-1] - pd.DateOffset(years=1)]
    fig = go.Figure(
        go.Candlestick(
            x=h.index, open=h["Open"], high=h["High"], low=h["Low"], close=h["Close"],
            increasing_line_color=VERDE, decreasing_line_color=VERMELHO, name="Preço",
        )
    )
    linhas = [
        (r.ponto_venda, "Ponto de venda", VERMELHO, "dash"),
        (r.ponto_medio, "Ponto médio", CINZA, "dot"),
        (r.ponto_compra, "Ponto de compra", VERDE, "dash"),
        (r.maximo_1a, "Máx. 52 sem.", VERMELHO, "solid"),
        (r.minimo_1a, "Mín. 52 sem.", VERDE, "solid"),
    ]
    for y, nome, cor, estilo in linhas:
        fig.add_hline(
            y=y, line_color=cor, line_dash=estilo, line_width=1.2, opacity=0.8,
            annotation_text=f"{nome}: {num(y)}", annotation_position="right",
            annotation_font_color=cor,
        )
    fig.update_layout(
        height=430, margin=dict(l=10, r=150, t=10, b=10),
        xaxis_rangeslider_visible=False, showlegend=False,
        yaxis_title=SIMBOLO.get(moeda, moeda),
    )
    return fig


def grafico_escada(r: Resultado):
    rotulos = ["1 ano", "3 anos", "5 anos"]
    valores = [r.retorno_1a, r.retorno_3a, r.retorno_5a]
    x = [l for l, v in zip(rotulos, valores) if v is not None]
    y = [v for v in valores if v is not None]
    fig = go.Figure()
    fig.add_bar(
        x=x, y=y, marker_color=[VERDE if v >= 0 else VERMELHO for v in y],
        text=[pct(v) for v in y], textposition="outside", width=0.98,
        cliponaxis=False,
    )
    # linha em degraus ligando o topo de cada barra
    if y:
        fig.add_scatter(
            x=x, y=y, mode="lines", line_shape="hv",
            line=dict(color=AZUL, width=2), hoverinfo="skip",
        )
    fig.add_hline(y=0, line_color=CINZA, line_width=1)
    fig.update_layout(
        height=330, margin=dict(l=10, r=10, t=30, b=10), showlegend=False,
        bargap=0.02, yaxis_title="Retorno total (%)",
    )
    return fig


# ------------------------------------------------------------ painel
def painel(ticker: str):
    with st.spinner(f"Buscando {ticker}..."):
        hist, divs, info = baixar(ticker)
    r = calcular(hist, divs)
    moeda = info.get("currency") or ("BRL" if ticker.endswith(".SA") else "USD")
    pl, lpa, acoes, div, dy = fundamentos(info, r)
    nome = info.get("longName") or info.get("shortName") or ticker

    st.subheader(f"{nome}  ·  {ticker}")
    st.caption(
        f"Último pregão: {r.data_ultimo:%d/%m/%Y} · Moeda: {moeda} · "
        "Fonte: Yahoo Finance (pode ter atraso de 15 min)"
    )

    cor = {"Zona de compra": VERDE, "Zona de venda": VERMELHO}.get(r.sinal, CINZA)
    st.markdown(
        f"<div style='font-size:2.2rem;font-weight:700'>{dinheiro(r.preco_atual, moeda)} "
        f"<span style='font-size:1rem;padding:4px 12px;border-radius:999px;"
        f"background:{cor}22;color:{cor};vertical-align:middle'>{r.sinal}</span></div>",
        unsafe_allow_html=True,
    )

    # 1) Pontos de compra e venda
    st.markdown("#### Pontos de compra e venda")
    c = st.columns(3)
    c[0].metric("Ponto de compra", dinheiro(r.ponto_compra, moeda),
                pct((r.ponto_compra / r.preco_atual - 1) * 100) + " do preço", delta_color="off")
    c[1].metric("Ponto médio", dinheiro(r.ponto_medio, moeda),
                pct((r.ponto_medio / r.preco_atual - 1) * 100) + " do preço", delta_color="off")
    c[2].metric("Ponto de venda", dinheiro(r.ponto_venda, moeda),
                pct((r.ponto_venda / r.preco_atual - 1) * 100) + " do preço", delta_color="off")

    # 2) 1 ano e médias de 52 semanas
    st.markdown("#### Últimos 12 meses × média de 52 semanas")
    tabela = pd.DataFrame(
        {
            "1 ano (extremo)": [dinheiro(r.minimo_1a, moeda), dinheiro(r.maximo_1a, moeda),
                                dinheiro(r.fechamento_1a, moeda)],
            "Média de 52 semanas": [dinheiro(r.media_minimas, moeda),
                                    dinheiro(r.media_maximas, moeda),
                                    dinheiro(r.media_fechamentos, moeda)],
        },
        index=["Mínimo", "Máximo", "Fechamento"],
    )
    col_t, col_a = st.columns([1, 1])
    col_t.table(tabela)
    col_a.markdown("**Ano corrente**")
    a = col_a.columns(2)
    a[0].metric(f"Máxima de {r.data_ultimo.year}", dinheiro(r.maxima_ano, moeda))
    a[1].metric(f"Mínima de {r.data_ultimo.year}", dinheiro(r.minima_ano, moeda))

    st.plotly_chart(grafico_preco(hist, r, moeda), width="stretch", key=f"preco_{ticker}")

    # 3) Fundamentos
    st.markdown("#### Indicadores")
    f = st.columns(5)
    f[0].metric("P/L", num(pl))
    f[1].metric("LPA básico", dinheiro(lpa, moeda) if lpa is not None else "—")
    f[2].metric("Dividendo anual (12m)", dinheiro(div, moeda))
    f[3].metric("Dividend yield", f"{num(dy)}%")
    f[4].metric("Ações em circulação", quantidade(acoes))

    # 4) Retornos em escada
    st.markdown("#### Retorno acumulado (com dividendos)")
    st.plotly_chart(grafico_escada(r), width="stretch", key=f"escada_{ticker}")

    with st.expander("Como os pontos são calculados"):
        st.markdown(
            f"""
- **Média de 52 semanas**: para cada uma das últimas 52 semanas pego a mínima, a máxima e o
  fechamento da semana e tiro a média de cada uma.
  Mínimas: **{num(r.media_minimas)}** · Máximas: **{num(r.media_maximas)}** ·
  Fechamentos: **{num(r.media_fechamentos)}**
- **Ponto de compra** = (média das mínimas + média dos fechamentos) ÷ 2
- **Ponto de venda** = (média das máximas + média dos fechamentos) ÷ 2
- **Ponto médio** = (média das mínimas + média das máximas) ÷ 2
- **Sinal**: preço ≤ ponto de compra → zona de compra; preço ≥ ponto de venda → zona de venda.
- **Retornos** usam o preço ajustado (inclui dividendos e desdobramentos).
- **Dividendo anual** = soma dos proventos pagos nos últimos 12 meses.

*Ferramenta de estudo, não é recomendação de investimento.*
"""
        )
        st.dataframe(
            r.semanal.rename(columns={"Low": "Mínima", "High": "Máxima", "Close": "Fechamento"})
            .sort_index(ascending=False).style.format("{:.2f}"),
            width="stretch",
        )


def resumo(tickers: list[str]):
    linhas = []
    for t in tickers:
        try:
            hist, divs, info = baixar(t)
            r = calcular(hist, divs)
            pl, lpa, acoes, div, dy = fundamentos(info, r)
            linhas.append({
                "Ticker": t, "Preço": r.preco_atual, "Compra": r.ponto_compra,
                "Médio": r.ponto_medio, "Venda": r.ponto_venda, "Sinal": r.sinal,
                "P/L": pl, "DY %": dy, "Ret. 1a %": r.retorno_1a,
                "Ret. 3a %": r.retorno_3a, "Ret. 5a %": r.retorno_5a,
            })
        except Exception as e:
            linhas.append({"Ticker": t, "Sinal": f"Erro: {e}"})
    df = pd.DataFrame(linhas).set_index("Ticker")
    st.dataframe(df.style.format(precision=2, na_rep="—"), width="stretch")


# ------------------------------------------------------------ página
st.title("📈 FINTAI")
st.caption("Painel de ações dos EUA e do Brasil")
st.write("Digite um ou mais tickers separados por vírgula. "
         "Brasileiras podem ir sem o .SA (ex.: PETR4, ITUB4, BOVA11); americanas como AAPL, MSFT.")

entrada = st.text_input("Tickers", value="PETR4, AAPL", key="tickers")
tickers = list(dict.fromkeys(normalizar_ticker(t) for t in entrada.split(",") if t.strip()))

if not tickers:
    st.info("Digite pelo menos um ticker.")
    st.stop()

if len(tickers) > 1:
    st.markdown("### Comparativo")
    resumo(tickers)

abas = st.tabs(tickers)
for aba, t in zip(abas, tickers):
    with aba:
        try:
            painel(t)
        except Exception as e:
            st.error(f"{t}: {e}")
