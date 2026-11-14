"""FINTAI: dashboard de ações (EUA e Brasil).

Rodar:  streamlit run app.py
"""
from __future__ import annotations

from html import escape

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

from calculos import Resultado, calcular, normalizar_ticker, pl_medio_12m

st.set_page_config(page_title="FINTAI", page_icon="📈", layout="wide")

VERDE, VERMELHO, AZUL, AMBAR = "#2fbf8a", "#f06a6a", "#5b8def", "#f2b84b"
TEXTO, SUAVE, BORDA = "#e8edf5", "#8c99b0", "#263147"
SIMBOLO = {"BRL": "R$", "USD": "US$", "EUR": "€", "GBP": "£"}

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Space+Grotesk:wght@600;700&display=swap');
:root {{ --verde:{VERDE}; --vermelho:{VERMELHO}; --azul:{AZUL}; --ambar:{AMBAR};
  --texto:{TEXTO}; --suave:{SUAVE}; --borda:{BORDA}; --cartao:#161e2e; --cartao2:#1b2538; }}
.stApp {{ font-family: 'Inter', system-ui, sans-serif; }}
.block-container {{ padding-top: 2.2rem; max-width: 1150px; }}
#MainMenu, footer {{ visibility: hidden; }}
.marca {{ display:flex; align-items:baseline; gap:.7rem; flex-wrap:wrap; margin-bottom:.4rem; }}
.marca b {{ font-family:'Space Grotesk',sans-serif; font-size:2rem; letter-spacing:.04em; color:var(--texto); }}
.marca b i {{ font-style:normal; color:var(--azul); }}
.marca span {{ color:var(--suave); font-size:.95rem; }}
.heroi {{ background:linear-gradient(135deg,#1b2740 0%,#141c2c 70%); border:1px solid var(--borda);
  border-radius:18px; padding:1.3rem 1.4rem; margin:.4rem 0 1rem; }}
.heroi .nome {{ font-size:1.05rem; font-weight:600; color:var(--texto); }}
.heroi .sub {{ color:var(--suave); font-size:.8rem; margin-top:.15rem; }}
.heroi .linha {{ display:flex; align-items:center; gap:.8rem; flex-wrap:wrap; margin-top:.8rem; }}
.heroi .preco {{ font-family:'Space Grotesk',sans-serif; font-size:2.5rem; font-weight:700; line-height:1;
  color:var(--texto); font-variant-numeric:tabular-nums; }}
.var {{ font-weight:600; font-size:.95rem; font-variant-numeric:tabular-nums; }}
.pill {{ padding:.3rem .8rem; border-radius:999px; font-size:.82rem; font-weight:600; white-space:nowrap; }}
.sec {{ font-family:'Space Grotesk',sans-serif; font-size:1.1rem; font-weight:600; color:var(--texto);
  margin:1.6rem 0 .7rem; }}
.sec small {{ font-family:'Inter',sans-serif; font-weight:400; color:var(--suave); font-size:.8rem; margin-left:.4rem; }}
.grade {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:.7rem; }}
.kpi {{ background:var(--cartao); border:1px solid var(--borda); border-radius:14px; padding:.85rem 1rem; min-width:0; }}
.kpi .r {{ color:var(--suave); font-size:.74rem; letter-spacing:.05em; text-transform:uppercase; }}
.kpi .v {{ color:var(--texto); font-size:1.3rem; font-weight:700; margin-top:.25rem;
  font-variant-numeric:tabular-nums; overflow-wrap:anywhere; }}
.kpi .n {{ color:var(--suave); font-size:.76rem; margin-top:.15rem; }}
.kpi.compra {{ border-top:3px solid var(--verde); }} .kpi.medio {{ border-top:3px solid var(--ambar); }}
.kpi.venda {{ border-top:3px solid var(--vermelho); }}
.faixa {{ background:var(--cartao); border:1px solid var(--borda); border-radius:14px; padding:1rem 1.1rem 0.9rem; margin-top:.7rem; }}
.trilho {{ position:relative; height:12px; border-radius:999px; margin:1.6rem .4rem .5rem; }}
.trilho i {{ position:absolute; top:-5px; width:2px; height:22px; transform:translateX(-1px); border-radius:2px; }}
.trilho u {{ position:absolute; top:-9px; width:16px; height:16px; transform:translate(-8px,6px); border-radius:50%;
  background:var(--texto); border:3px solid var(--azul); box-shadow:0 0 0 4px #5b8def33; }}
.trilho em {{ position:absolute; top:-1.5rem; transform:translateX(-50%); font-style:normal; font-size:.72rem;
  font-weight:600; color:var(--azul); white-space:nowrap; }}
.pontas {{ display:flex; justify-content:space-between; color:var(--suave); font-size:.76rem; font-variant-numeric:tabular-nums; }}
.legenda {{ display:flex; gap:1rem; flex-wrap:wrap; color:var(--suave); font-size:.76rem; margin-top:.5rem; }}
.legenda span::before {{ content:""; display:inline-block; width:9px; height:9px; border-radius:2px; margin-right:.35rem; background:var(--c); }}
.rolagem {{ overflow-x:auto; border:1px solid var(--borda); border-radius:14px; background:var(--cartao); }}
table.t {{ width:100%; border-collapse:collapse; font-variant-numeric:tabular-nums; font-size:.92rem; }}
table.t th, table.t td {{ padding:.65rem .9rem; text-align:right; white-space:nowrap; border:none; }}
table.t thead th {{ color:var(--suave); font-weight:500; font-size:.74rem; letter-spacing:.04em; text-transform:uppercase;
  border-bottom:1px solid var(--borda); background:var(--cartao2); }}
table.t th:first-child, table.t td:first-child {{ text-align:left; color:var(--suave); font-weight:500; }}
table.t td {{ color:var(--texto); border-bottom:1px solid #26314766; }}
table.t tr:last-child td {{ border-bottom:none; font-weight:700; color:var(--ambar); }}
table.t tr:last-child td:first-child {{ color:var(--ambar); }}
@media (max-width: 560px) {{
  .grade.tres {{ grid-template-columns:1fr; gap:.5rem; }}
  .grade.tres .kpi {{ display:grid; grid-template-columns:1fr auto; align-items:center; column-gap:.8rem;
    border-top:none; border-left:3px solid var(--borda); padding:.7rem .9rem; }}
  .grade.tres .kpi.compra {{ border-left-color:var(--verde); }} .grade.tres .kpi.medio {{ border-left-color:var(--ambar); }}
  .grade.tres .kpi.venda {{ border-left-color:var(--vermelho); }}
  .grade.tres .kpi .v {{ grid-column:2; grid-row:1 / span 2; margin:0; }}
  .grade.tres .kpi .n {{ grid-column:1; }}
  table.t {{ font-size:.82rem; }}
  table.t th, table.t td {{ padding:.6rem .45rem; }}
  table.t thead th {{ white-space:normal; font-size:.66rem; vertical-align:bottom; }}
  .heroi .preco {{ font-size:2.1rem; }}
}}
.rodape {{ color:var(--suave); font-size:.76rem; margin-top:1.5rem; text-align:center; }}
</style>
"""


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


def kpi(rotulo, valor, nota="", classe=""):
    nota_html = f"<div class='n'>{nota}</div>" if nota else ""
    return f"<div class='kpi {classe}'><div class='r'>{rotulo}</div><div class='v'>{valor}</div>{nota_html}</div>"


def grade(*cartoes, classe=""):
    st.markdown(f"<div class='grade {classe}'>{''.join(cartoes)}</div>", unsafe_allow_html=True)


def secao(titulo, detalhe=""):
    extra = f"<small>{detalhe}</small>" if detalhe else ""
    st.markdown(f"<div class='sec'>{titulo}{extra}</div>", unsafe_allow_html=True)


# ------------------------------------------------------------ dados
@st.cache_data(ttl=900, show_spinner=False)
def baixar(ticker: str):
    tk = yf.Ticker(ticker)
    hist = tk.history(period="5y", interval="1d", auto_adjust=False)
    if hist is None or hist.empty:
        raise ValueError(f"Não encontrei dados para {ticker}. Confira o código.")
    try:
        info = dict(tk.info or {})
    except Exception:
        info = {}
    try:
        divs = tk.dividends
    except Exception:
        divs = pd.Series(dtype=float)
    lpa_tri = None
    try:  # LPA divulgado a cada trimestre, para o P/L médio
        datas = tk.get_earnings_dates(limit=16)
        if datas is not None and "Reported EPS" in datas:
            lpa_tri = datas["Reported EPS"].dropna()
    except Exception:
        lpa_tri = None
    return hist, divs, info, lpa_tri


def fundamentos(info: dict, r: Resultado, lpa_tri):
    lpa = info.get("trailingEps") or info.get("epsTrailingTwelveMonths")
    pl = info.get("trailingPE")
    if pl is None and lpa and lpa > 0:
        pl = r.preco_atual / lpa
    pl_medio, metodo = pl_medio_12m(r.fechamentos_1a, lpa_tri, lpa)
    acoes = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding")
    div, dy = r.dividendo_12m, r.dividend_yield
    if not div and info.get("dividendRate"):  # sem histórico, usa o informado
        div = float(info["dividendRate"])
        dy = div / r.preco_atual * 100
    return pl, pl_medio, metodo, lpa, acoes, div, dy


# ------------------------------------------------------------ blocos visuais
def bloco_heroi(nome, ticker, moeda, r: Resultado):
    cor = {"Zona de compra": VERDE, "Zona de venda": VERMELHO}.get(r.sinal, SUAVE)
    var = ""
    if r.variacao_dia is not None:
        cv = VERDE if r.variacao_dia >= 0 else VERMELHO
        seta = "▲" if r.variacao_dia >= 0 else "▼"
        var = f"<span class='var' style='color:{cv}'>{seta} {pct(r.variacao_dia)} no dia</span>"
    st.markdown(
        f"<div class='heroi'><div class='nome'>{escape(nome)} · {escape(ticker)}</div>"
        f"<div class='sub'>Último pregão {r.data_ultimo:%d/%m/%Y} · {moeda} · Yahoo Finance</div>"
        f"<div class='linha'><span class='preco'>{dinheiro(r.preco_atual, moeda)}</span>{var}"
        f"<span class='pill' style='background:{cor}26;color:{cor}'>{r.sinal}</span></div></div>",
        unsafe_allow_html=True,
    )


def bloco_faixa(r: Resultado, moeda):
    """Régua de 52 semanas: onde o preço está em relação aos pontos."""
    lo, hi = r.minimo_1a, r.maximo_1a
    largura = (hi - lo) or 1

    def pos(v):
        return max(0.0, min(100.0, (v - lo) / largura * 100))

    c, m, v, p = pos(r.ponto_compra), pos(r.ponto_medio), pos(r.ponto_venda), pos(r.preco_atual)
    fundo = (f"linear-gradient(90deg,{VERDE}55 0%,{VERDE}55 {c:.1f}%,#2a3650 {c:.1f}%,"
             f"#2a3650 {v:.1f}%,{VERMELHO}55 {v:.1f}%,{VERMELHO}55 100%)")
    st.markdown(
        f"<div class='faixa'><div class='trilho' style='background:{fundo}'>"
        f"<i style='left:{c:.1f}%;background:{VERDE}'></i><i style='left:{m:.1f}%;background:{AMBAR}'></i>"
        f"<i style='left:{v:.1f}%;background:{VERMELHO}'></i>"
        f"<em style='left:{min(max(p, 8), 92):.1f}%'>Preço {num(r.preco_atual)}</em><u style='left:{p:.1f}%'></u></div>"
        f"<div class='pontas'><span>Mín. 52 sem. {num(lo)}</span><span>Máx. 52 sem. {num(hi)}</span></div>"
        f"<div class='legenda'><span style='--c:{VERDE}'>Compra {num(r.ponto_compra)}</span>"
        f"<span style='--c:{AMBAR}'>Médio {num(r.ponto_medio)}</span>"
        f"<span style='--c:{VERMELHO}'>Venda {num(r.ponto_venda)}</span></div></div>",
        unsafe_allow_html=True,
    )


def bloco_tabela(r: Resultado):
    colunas = ["1 ano", "Média 52 sem.", "30 dias", "Média 30 dias"]
    linhas = [
        ("Mínimo", r.minimo_1a, r.media_minimas, r.minimo_30d, r.media_min_30d),
        ("Máximo", r.maximo_1a, r.media_maximas, r.maximo_30d, r.media_max_30d),
        ("Fechamento", r.fechamento_1a, r.media_fechamentos, r.fechamento_30d, r.media_fech_30d),
        ("Ponto médio", r.medio_1a, r.ponto_medio, r.medio_30d, r.medio_media_30d),
    ]
    cab = "".join(f"<th>{c}</th>" for c in colunas)
    corpo = "".join(
        f"<tr><td>{nome}</td>{''.join(f'<td>{num(v)}</td>' for v in vals)}</tr>"
        for nome, *vals in linhas
    )
    st.markdown(
        f"<div class='rolagem'><table class='t'><thead><tr><th></th>{cab}</tr></thead>"
        f"<tbody>{corpo}</tbody></table></div>",
        unsafe_allow_html=True,
    )


def _estilo(fig, altura):
    fig.update_layout(
        template="plotly_dark", height=altura, showlegend=False,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, system-ui, sans-serif", color=SUAVE, size=12),
        margin=dict(l=8, r=8, t=16, b=8), dragmode=False,
    )
    fig.update_xaxes(gridcolor="#26314755", zeroline=False)
    fig.update_yaxes(gridcolor="#26314799", zeroline=False)
    return fig


def grafico_preco(hist: pd.DataFrame, r: Resultado):
    h = hist.copy()
    if getattr(h.index, "tz", None) is not None:
        h.index = h.index.tz_localize(None)
    h = h[h.index > h.index[-1] - pd.DateOffset(years=1)]
    fig = go.Figure(
        go.Candlestick(
            x=h.index, open=h["Open"], high=h["High"], low=h["Low"], close=h["Close"],
            increasing_line_color=VERDE, decreasing_line_color=VERMELHO,
            increasing_fillcolor=VERDE, decreasing_fillcolor=VERMELHO, name="Preço",
        )
    )
    # rótulos em cantos diferentes: os três pontos costumam ficar próximos
    for y, nome, cor, canto in ((r.ponto_venda, "Venda", VERMELHO, "top left"),
                                (r.ponto_medio, "Médio", AMBAR, "top right"),
                                (r.ponto_compra, "Compra", VERDE, "bottom left")):
        fig.add_hline(y=y, line_color=cor, line_dash="dash", line_width=1.3,
                      annotation_text=f"{nome} {num(y)}", annotation_position=canto,
                      annotation_font=dict(color=cor, size=11))
    fig.update_layout(xaxis_rangeslider_visible=False)
    return _estilo(fig, 420)


def grafico_escada(r: Resultado):
    pares = [(l, v) for l, v in (("1 ano", r.retorno_1a), ("3 anos", r.retorno_3a),
                                 ("5 anos", r.retorno_5a)) if v is not None]
    x, y = [p[0] for p in pares], [p[1] for p in pares]
    fig = go.Figure()
    fig.add_bar(x=x, y=y, marker_color=[VERDE if v >= 0 else VERMELHO for v in y],
                marker_line_width=0, opacity=0.9, text=[pct(v) for v in y],
                textposition="outside", textfont=dict(color=TEXTO, size=14), width=0.98,
                cliponaxis=False)
    fig.add_hline(y=0, line_color=SUAVE, line_width=1)
    fig.update_layout(bargap=0.02, yaxis_ticksuffix="%")
    fig.update_yaxes(rangemode="tozero")
    return _estilo(fig, 330).update_layout(margin=dict(l=8, r=8, t=40, b=8))


# ------------------------------------------------------------ painel
def painel(ticker: str):
    with st.spinner(f"Buscando {ticker}..."):
        hist, divs, info, lpa_tri = baixar(ticker)
    r = calcular(hist, divs)
    moeda = info.get("currency") or ("BRL" if ticker.endswith(".SA") else "USD")
    pl, pl_medio, metodo, lpa, acoes, div, dy = fundamentos(info, r, lpa_tri)
    nome = info.get("longName") or info.get("shortName") or ticker
    cfg = {"displayModeBar": False}

    def dist(v):
        return f"{pct((v / r.preco_atual - 1) * 100)} do preço atual"

    bloco_heroi(nome, ticker, moeda, r)

    secao("Pontos de compra e venda", "base: médias de 52 semanas")
    grade(
        kpi("Ponto de compra", dinheiro(r.ponto_compra, moeda), dist(r.ponto_compra), "compra"),
        kpi("Ponto médio", dinheiro(r.ponto_medio, moeda), dist(r.ponto_medio), "medio"),
        kpi("Ponto de venda", dinheiro(r.ponto_venda, moeda), dist(r.ponto_venda), "venda"),
        classe="tres",
    )
    bloco_faixa(r, moeda)

    secao("Mínimo, máximo e fechamento", f"valores em {SIMBOLO.get(moeda, moeda)}")
    bloco_tabela(r)
    st.write("")
    grade(
        kpi(f"Máxima de {r.data_ultimo.year}", dinheiro(r.maxima_ano, moeda)),
        kpi(f"Mínima de {r.data_ultimo.year}", dinheiro(r.minima_ano, moeda)),
    )

    secao("Preço em 12 meses")
    st.plotly_chart(grafico_preco(hist, r), width="stretch", key=f"preco_{ticker}",
                    theme=None, config=cfg)

    secao("Indicadores")
    nota_pl = ""
    if pl and pl_medio:
        dif = (pl / pl_medio - 1) * 100
        nota_pl = f"{pct(dif)} vs. média de 12m"
    nota_medio = {"trimestral": "com o LPA de cada trimestre",
                  "simplificado": "preço médio ÷ LPA atual"}.get(metodo, "")
    grade(
        kpi("P/L atual", num(pl), nota_pl),
        kpi("P/L médio 12 meses", num(pl_medio), nota_medio),
        kpi("LPA básico", dinheiro(lpa, moeda) if lpa is not None else "—", "últimos 12 meses"),
        kpi("Dividendo anual", dinheiro(div, moeda), "pago em 12 meses"),
        kpi("Dividend yield", f"{num(dy)}%"),
        kpi("Ações em circulação", quantidade(acoes)),
    )

    secao("Retorno acumulado", "com dividendos")
    st.plotly_chart(grafico_escada(r), width="stretch", key=f"escada_{ticker}",
                    theme=None, config=cfg)

    with st.expander("Como os números são calculados"):
        st.markdown(
            f"""
- **Média de 52 semanas**: mínima, máxima e fechamento de cada uma das últimas 52 semanas,
  e a média de cada uma.
- **30 dias**: mínima, máxima e fechamento dos últimos 30 dias corridos.
  **Média 30 dias**: média das mínimas, máximas e fechamentos diários do período.
- **Ponto médio** de cada coluna = (mínimo + máximo) ÷ 2.
- **Ponto de compra** = (média das mínimas + média dos fechamentos de 52 semanas) ÷ 2
- **Ponto de venda** = (média das máximas + média dos fechamentos de 52 semanas) ÷ 2
- **Sinal**: preço ≤ ponto de compra → zona de compra; preço ≥ ponto de venda → zona de venda.
- **P/L atual** = preço ÷ lucro por ação dos últimos 12 meses.
- **P/L médio 12 meses**: média do P/L de cada pregão do último ano, usando o lucro por ação
  já divulgado em cada data. Quando o Yahoo não traz o histórico de lucros, uso o preço médio
  do ano ÷ LPA atual (o cartão indica qual método foi usado).
- **Retornos** usam o preço ajustado (inclui dividendos e desdobramentos).
- **Dividendo anual** = soma dos proventos pagos nos últimos 12 meses.
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
            hist, divs, info, lpa_tri = baixar(t)
            r = calcular(hist, divs)
            pl, pl_medio, _, lpa, acoes, div, dy = fundamentos(info, r, lpa_tri)
            linhas.append({
                "Ticker": t, "Preço": r.preco_atual, "Compra": r.ponto_compra,
                "Médio": r.ponto_medio, "Venda": r.ponto_venda, "Sinal": r.sinal,
                "P/L": pl, "P/L médio": pl_medio, "DY %": dy, "Ret. 1a %": r.retorno_1a,
                "Ret. 3a %": r.retorno_3a, "Ret. 5a %": r.retorno_5a,
            })
        except Exception as e:
            linhas.append({"Ticker": t, "Sinal": f"Erro: {e}"})
    df = pd.DataFrame(linhas).set_index("Ticker")
    st.dataframe(df.style.format(precision=2, na_rep="—"), width="stretch")


# ------------------------------------------------------------ página
st.markdown(CSS, unsafe_allow_html=True)
st.markdown(
    "<div class='marca'><b>FINT<i>AI</i></b><span>Ações do Brasil e dos EUA em um só painel</span></div>",
    unsafe_allow_html=True,
)

entrada = st.text_input(
    "Tickers", value="PETR4, AAPL", key="tickers",
    help="Separe por vírgula. Brasileiras podem ir sem o .SA (PETR4, ITUB4, BOVA11); americanas como AAPL, MSFT.",
    placeholder="PETR4, AAPL, MSFT",
)
tickers = list(dict.fromkeys(normalizar_ticker(t) for t in entrada.split(",") if t.strip()))

if not tickers:
    st.info("Digite pelo menos um ticker.")
    st.stop()

if len(tickers) > 1:
    secao("Comparativo")
    resumo(tickers)

abas = st.tabs(tickers)
for aba, t in zip(abas, tickers):
    with aba:
        try:
            painel(t)
        except Exception as e:
            st.error(f"{t}: {e}")

st.markdown("<div class='rodape'>Dados do Yahoo Finance, com possível atraso. "
            "Ferramenta de estudo, não é recomendação de investimento.</div>",
            unsafe_allow_html=True)
