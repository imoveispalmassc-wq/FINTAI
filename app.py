"""FINTAI: dashboard de ações (EUA e Brasil).

Rodar:  streamlit run app.py
"""
from __future__ import annotations

import importlib
from html import escape
from urllib.parse import quote

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

import calculos
import utils.formato
import utils.percentile
import utils.signals

# O Streamlit Cloud pode manter versões antigas dos módulos na memória depois de uma
# atualização; recarregar (na ordem das dependências) mantém tudo na mesma versão.
for _modulo in (utils.formato, utils.percentile, utils.signals, calculos):
    importlib.reload(_modulo)

from calculos import (Resultado, calcular, crescimento_lpa, dy_atual_e_medio,
                      normalizar_ticker, pl_medio_12m, pl_medio_longo, preco_justo_graham,
                      preco_teto_bazin, retorno_periodo)
from utils.formato import num, pct
from utils.percentile import P_CARO, P_COMPRA, P_OPORTUNIDADE, nome_da_zona, zonas
from utils.signals import (avaliar_criterio, backtest_percentil, decidir_estado,
                           fundamento_quebrou, selo_backtest)

st.set_page_config(page_title="FINTAI", page_icon="📈", layout="wide")

VERDE, VERMELHO, AZUL, AMBAR = "#2fbf8a", "#f06a6a", "#5b8def", "#f2b84b"
TEXTO, SUAVE, BORDA, ARDOSIA = "#e8edf5", "#8c99b0", "#263147", "#4a5875"
SIMBOLO = {"BRL": "R$", "USD": "US$", "EUR": "€", "GBP": "£"}
COR_ESTADO = {"COMPRAR": VERDE, "AGUARDAR": SUAVE, "CARO": AMBAR, "VENDER": VERMELHO}
COR_STATUS = {"Favorável": VERDE, "Neutro": AMBAR, "Desfavorável": VERMELHO, "Sem dados": SUAVE}

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Space+Grotesk:wght@600;700&display=swap');
:root {{ --verde:{VERDE}; --vermelho:{VERMELHO}; --azul:{AZUL}; --ambar:{AMBAR};
  --texto:{TEXTO}; --suave:{SUAVE}; --borda:{BORDA}; --cartao:#161e2e; --cartao2:#1b2538; }}
.stApp {{ font-family: 'Inter', system-ui, sans-serif; }}
.block-container {{ padding-top: 2.2rem; max-width: 1150px; }}
#MainMenu, footer {{ visibility: hidden; }}
[data-testid='stToolbarActions'], [data-testid='stMainMenu'], [data-testid='stAppDeployButton'] {{ display:none !important; }}
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
.kpi.oport {{ border-top:3px solid var(--verde); }} .kpi.neutra {{ border-top:3px solid #4a5875; }}
.kpi.cara {{ border-top:3px solid var(--ambar); }}
.faixa {{ background:var(--cartao); border:1px solid var(--borda); border-radius:14px; padding:1rem 1.1rem 0.9rem; margin-top:.7rem; }}
.trilho {{ position:relative; height:12px; border-radius:999px; margin:1.8rem .4rem .5rem; }}
.trilho i {{ position:absolute; top:-5px; width:2px; height:22px; transform:translateX(-1px); border-radius:2px; }}
.trilho u {{ position:absolute; top:-9px; width:16px; height:16px; transform:translate(-8px,6px); border-radius:50%;
  background:var(--texto); border:3px solid var(--azul); box-shadow:0 0 0 4px #5b8def33; }}
.trilho em {{ position:absolute; top:-1.6rem; transform:translateX(-50%); font-style:normal; font-size:.7rem;
  font-weight:700; letter-spacing:.04em; color:var(--azul); white-space:nowrap; }}
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
table.t tr:last-child td {{ border-bottom:none; }}
table.t.destaque tr:last-child td, table.t.destaque tr:last-child td:first-child {{ font-weight:700; color:var(--ambar); }}
table.t.bt tr:last-child td {{ color:var(--suave); }}
.chips {{ display:flex; gap:.5rem; flex-wrap:wrap; margin-top:.8rem; }}
.chip {{ border:1px solid var(--borda); border-radius:999px; padding:.25rem .7rem; font-size:.78rem; color:var(--suave); }}
.chip b {{ color:var(--texto); font-weight:600; }}
.nota {{ color:var(--suave); font-size:.82rem; margin:.7rem .2rem 0; line-height:1.5; }}
.nota b {{ color:var(--texto); }}
@media (max-width: 560px) {{
  .grade.tres {{ grid-template-columns:1fr; gap:.5rem; }}
  .grade.tres .kpi {{ display:grid; grid-template-columns:1fr auto; align-items:center; column-gap:.8rem;
    border-top:none; border-left:3px solid var(--borda); padding:.7rem .9rem; }}
  .grade.tres .kpi.oport {{ border-left-color:var(--verde); }} .grade.tres .kpi.neutra {{ border-left-color:#4a5875; }}
  .grade.tres .kpi.cara {{ border-left-color:var(--ambar); }}
  .grade.tres .kpi .v {{ font-size:1.05rem; }}
  .grade.tres .kpi .v {{ grid-column:2; grid-row:1 / span 2; margin:0; }}
  .grade.tres .kpi .n {{ grid-column:1; }}
  table.t {{ font-size:.82rem; }}
  table.t th, table.t td {{ padding:.6rem .45rem; }}
  table.t thead th {{ white-space:normal; font-size:.66rem; vertical-align:bottom; }}
  table.t.bt td:first-child, table.t.bt th:first-child {{ white-space:normal; min-width:6.5rem; }}
  .heroi .preco {{ font-size:2.1rem; }}
}}
.estado {{ color:var(--texto); font-size:.92rem; line-height:1.5; margin-top:.8rem; }}
.eventos {{ background:var(--cartao); border:1px solid var(--borda); border-radius:14px; padding:.3rem 1rem; }}
.evento {{ display:grid; grid-template-columns:5.2rem 1fr; gap:.8rem; padding:.7rem 0; border-bottom:1px solid #26314766; }}
.evento:last-child {{ border-bottom:none; }}
.evento .d {{ color:var(--suave); font-size:.78rem; font-variant-numeric:tabular-nums; padding-top:.1rem; }}
.evento .t {{ color:var(--suave); font-size:.7rem; letter-spacing:.05em; text-transform:uppercase; }}
.evento .x {{ color:var(--texto); font-size:.9rem; line-height:1.4; overflow-wrap:anywhere; }}
.evento a {{ color:var(--azul); text-decoration:none; }}
.crit {{ background:var(--cartao); border:1px solid var(--borda); border-radius:14px; padding:.9rem 1rem; min-width:0; }}
.crit .topo {{ display:flex; justify-content:space-between; align-items:center; gap:.6rem; flex-wrap:wrap; }}
.crit .nome {{ color:var(--texto); font-weight:600; font-size:.95rem; }}
.crit .st {{ font-size:.78rem; font-weight:600; white-space:nowrap; }}
.crit .vals {{ display:grid; grid-template-columns:repeat(3,1fr); gap:.5rem; margin:.7rem 0 .6rem; }}
.crit .vals span {{ display:block; color:var(--suave); font-size:.68rem; letter-spacing:.04em; text-transform:uppercase; }}
.crit .vals b {{ color:var(--texto); font-size:1.02rem; font-variant-numeric:tabular-nums; }}
.crit .n {{ color:var(--suave); font-size:.8rem; line-height:1.45; }}
.grade.larga {{ grid-template-columns:repeat(auto-fit,minmax(250px,1fr)); }}
.selo {{ display:inline-block; padding:.25rem .7rem; border-radius:999px; font-size:.72rem; font-weight:700; letter-spacing:.04em; }}
.selo.ok {{ background:#2fbf8a26; color:var(--verde); }} .selo.nao {{ background:#f06a6a26; color:var(--vermelho); }}
.bench {{ background:var(--cartao); border:1px solid var(--borda); border-radius:14px; padding:.4rem 1rem; }}
.bench div {{ padding:.55rem 0; border-bottom:1px solid #26314766; color:var(--suave); font-size:.86rem; line-height:1.5;
  font-variant-numeric:tabular-nums; }}
.bench div:last-child {{ border-bottom:none; }}
.bench b {{ color:var(--texto); }}
.rodape {{ color:var(--suave); font-size:.76rem; margin-top:1.5rem; text-align:center; }}
</style>
"""



# ------------------------------------------------------------ formatação
def dinheiro(v, moeda):
    return "—" if v is None else f"{SIMBOLO.get(moeda, moeda)} {num(v)}"


def quantidade(v):
    if not v:
        return "—"
    for lim, suf in ((1e12, "tri"), (1e9, "bi"), (1e6, "mi")):
        if abs(v) >= lim:
            return f"{num(v / lim)} {suf}"
    return num(v, 0)


def curto(ticker: str) -> str:
    """PETR4.SA -> PETR4 (como o usuário digita)."""
    return ticker[:-3] if ticker.endswith(".SA") else ticker


def kpi(rotulo, valor, nota="", classe=""):
    nota_html = f"<div class='n'>{nota}</div>" if nota else ""
    return f"<div class='kpi {classe}'><div class='r'>{rotulo}</div><div class='v'>{valor}</div>{nota_html}</div>"


def grade(*cartoes, classe=""):
    st.markdown(f"<div class='grade {classe}'>{''.join(cartoes)}</div>", unsafe_allow_html=True)


def secao(titulo, detalhe=""):
    extra = f"<small>{detalhe}</small>" if detalhe else ""
    st.markdown(f"<div class='sec'>{titulo}{extra}</div>", unsafe_allow_html=True)


def nota(html):
    st.markdown(f"<div class='nota'>{html}</div>", unsafe_allow_html=True)


# ------------------------------------------------------------ dados
def _linha(df, nomes):
    """Primeira linha existente de um demonstrativo do Yahoo, como série por data."""
    if df is None or getattr(df, "empty", True):
        return None
    for n in nomes:
        if n in df.index:
            s = df.loc[n].dropna()
            if len(s):
                s.index = pd.to_datetime(s.index)
                return s.sort_index().astype(float)
    return None


def _noticias(tk) -> list[dict]:
    """Manchetes do Yahoo Finance para o ativo (o formato muda entre versões do yfinance)."""
    saida = []
    for item in (tk.news or [])[:5]:
        c = item.get("content") or item
        titulo = c.get("title")
        if not titulo:
            continue
        quando = c.get("pubDate") or c.get("displayTime") or c.get("providerPublishTime")
        try:
            data = (pd.to_datetime(quando, unit="s") if isinstance(quando, (int, float))
                    else pd.to_datetime(quando))
            data = data.tz_localize(None) if data.tzinfo else data
        except Exception:
            continue
        link = (c.get("canonicalUrl") or {}).get("url") or (c.get("clickThroughUrl") or {}).get("url") \
            or c.get("link") or ""
        fonte = (c.get("provider") or {}).get("displayName") or c.get("publisher") or ""
        saida.append({"titulo": str(titulo), "data": data, "link": str(link), "fonte": str(fonte)})
    return saida


@st.cache_data(ttl=900, show_spinner=False)
def baixar(ticker: str) -> dict:
    tk = yf.Ticker(ticker)
    hist = tk.history(period="10y", interval="1d", auto_adjust=False)
    if hist is None or hist.empty:
        raise ValueError(f"Não encontrei dados para {ticker}. Confira o código.")
    d = {"hist": hist, "info": {}, "divs": pd.Series(dtype=float), "lpa_tri": None,
         "lucro_tri": None, "lpa_anual": None, "noticias": []}

    def tentar(chave, funcao):
        try:
            valor = funcao()
            if valor is not None:
                d[chave] = valor
        except Exception:
            pass

    tentar("info", lambda: dict(tk.info or {}))
    tentar("divs", lambda: tk.dividends)
    # LPA divulgado a cada trimestre
    tentar("lpa_tri", lambda: tk.get_earnings_dates(limit=28)["Reported EPS"].dropna())
    tentar("lucro_tri", lambda: _linha(tk.quarterly_income_stmt, ["Net Income", "Net Income Common Stockholders"]))
    tentar("lpa_anual", lambda: _linha(tk.income_stmt, ["Basic EPS", "Diluted EPS"]))
    tentar("noticias", lambda: _noticias(tk))
    return d


@st.cache_data(ttl=3600, show_spinner=False)
def baixar_indice(simbolos: tuple[str, ...]):
    """Fechamentos do índice de referência (tenta os símbolos na ordem)."""
    for s in simbolos:
        try:
            h = yf.Ticker(s).history(period="10y", interval="1d", auto_adjust=False)
            if h is not None and not h.empty:
                c = h["Close"].dropna()
                if c.index.tz is not None:
                    c.index = c.index.tz_localize(None)
                return c
        except Exception:
            continue
    return None


def indice_de(ticker: str):
    """Ibovespa para ações da B3; S&P 500 (com dividendos) para as demais."""
    if ticker.endswith(".SA"):
        return "Ibovespa", baixar_indice(("^BVSP",))
    return "S&P 500", baixar_indice(("^SP500TR", "^GSPC"))


def fundamentos(d: dict, r: Resultado) -> dict:
    info, hist, lpa_tri = d["info"], d["hist"], d["lpa_tri"]
    lpa = info.get("trailingEps") or info.get("epsTrailingTwelveMonths")
    pl = info.get("trailingPE")
    if pl is None and lpa and lpa > 0:
        pl = r.preco_atual / lpa
    splits = hist["Stock Splits"] if "Stock Splits" in hist else None
    pl_medio, metodo = pl_medio_12m(r.fechamentos_1a, lpa_tri, lpa, splits)
    pl_5a, anos_5a = pl_medio_longo(hist["Close"], lpa_tri, lpa, splits)
    acoes = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding")
    div, dy = r.dividendo_12m, r.dividend_yield
    if not div and info.get("dividendRate"):  # sem histórico, usa o informado
        div = float(info["dividendRate"])
        dy = div / r.preco_atual * 100
    dy_hoje, dy_medio = dy_atual_e_medio(hist)
    lpa_agora, lpa_antes, base_lpa = crescimento_lpa(lpa_tri, d["lpa_anual"])

    # ---- preço justo (referência)
    inicio = hist.index[0].tz_localize(None) if hist.index.tz is not None else hist.index[0]
    proventos = hist["Dividends"][hist["Dividends"] > 0] if "Dividends" in hist else None
    bazin, div_medio = preco_teto_bazin(proventos, inicio, r.data_ultimo)
    vpa = info.get("bookValue")
    if pl_5a:
        pl_ref, rotulo_ref = pl_5a, f"P/L médio de {num(anos_5a, 1)} anos"
    elif metodo == "trimestral":
        pl_ref, rotulo_ref = pl_medio, "P/L médio de 12 meses"
    else:
        pl_ref, rotulo_ref = None, ""

    # ---- saúde financeira (para o estado VENDER)
    divida, caixa, ebitda = info.get("totalDebt"), info.get("totalCash"), info.get("ebitda")
    dl_ebitda = (divida - (caixa or 0)) / ebitda if divida is not None and ebitda and ebitda > 0 else None
    lucros = d["lucro_tri"] if d["lucro_tri"] is not None else lpa_tri

    return dict(
        pl=pl, pl_medio=pl_medio, metodo=metodo, lpa=lpa, acoes=acoes, div=div, dy=dy,
        dy_hoje=dy_hoje if dy_hoje is not None else dy, dy_medio=dy_medio,
        lpa_agora=lpa_agora, lpa_antes=lpa_antes, base_lpa=base_lpa,
        vpa=vpa, bazin=bazin, div_medio=div_medio, graham=preco_justo_graham(lpa, vpa),
        pl_ref=pl_ref, rotulo_ref=rotulo_ref,
        justo_pl=pl_ref * lpa if pl_ref and lpa and lpa > 0 else None,
        dl_ebitda=dl_ebitda, lucros=lucros,
    )


def analisar(ticker: str, d: dict, r: Resultado, f: dict, moeda: str) -> dict:
    """Junta teste histórico, selos e fundamentos e decide o estado do ativo."""
    try:
        bt = backtest_percentil(d["hist"])
    except Exception:
        vazio = {"casos": 0, "retorno_6m": None, "retorno_12m": None, "acerto_12m": None}
        bt = {"compra": vazio, "venda": vazio, "referencia": vazio, "anos": 0.0}
    ref = bt["referencia"]["retorno_12m"]
    nome = curto(ticker)
    selo_c = selo_backtest("compra", bt["compra"]["acerto_12m"], bt["compra"]["retorno_12m"],
                           ref, bt["compra"]["casos"], nome)
    selo_v = selo_backtest("venda", bt["venda"]["acerto_12m"], bt["venda"]["retorno_12m"],
                           ref, bt["venda"]["casos"], nome)
    quebrou, motivo = fundamento_quebrou(f["lucros"], f["dl_ebitda"])
    estado = decidir_estado(r.percentil, r.minimo_1a, r.maximo_1a,
                            compra_validada=selo_c.validado, venda_validada=selo_v.validado,
                            quebrou=quebrou, motivo_quebra=motivo,
                            simbolo=SIMBOLO.get(moeda, moeda))
    return {"bt": bt, "selo_compra": selo_c, "selo_venda": selo_v, "estado": estado}


def eventos(d: dict, moeda: str) -> list[dict]:
    """Até 3 eventos recentes, só com dados que o app realmente tem."""
    ev = []
    lpa_tri = d["lpa_tri"]
    if lpa_tri is not None and len(lpa_tri):
        e = lpa_tri.sort_index()
        if e.index.tz is not None:
            e.index = e.index.tz_localize(None)
        texto = f"LPA de {dinheiro(float(e.iloc[-1]), moeda)} no trimestre"
        if len(e) >= 5:
            texto += f" ({dinheiro(float(e.iloc[-5]), moeda)} um ano antes)"
        ev.append({"data": e.index[-1], "tipo": "Resultado trimestral", "texto": texto, "link": ""})
    elif d["lucro_tri"] is not None and len(d["lucro_tri"]):
        l = d["lucro_tri"]
        sinal = "Lucro líquido" if l.iloc[-1] >= 0 else "Prejuízo"
        ev.append({"data": l.index[-1], "tipo": "Resultado trimestral",
                   "texto": f"{sinal} de {SIMBOLO.get(moeda, moeda)} {quantidade(abs(float(l.iloc[-1])))} "
                            "no trimestre encerrado nesta data", "link": ""})
    hist = d["hist"]
    if "Dividends" in hist:
        p = hist["Dividends"][hist["Dividends"] > 0]
        if len(p):
            data = p.index[-1].tz_localize(None) if p.index.tz is not None else p.index[-1]
            ev.append({"data": data, "tipo": "Provento",
                       "texto": f"Provento de {dinheiro(float(p.iloc[-1]), moeda)} por ação", "link": ""})
    for n in d["noticias"][:1 if ev else 3]:
        fonte = f" · {n['fonte']}" if n["fonte"] else ""
        ev.append({"data": n["data"], "tipo": f"Notícia{fonte}", "texto": n["titulo"], "link": n["link"]})
    return sorted(ev, key=lambda x: x["data"], reverse=True)[:3]


# ------------------------------------------------------------ lista e compartilhar
def alternar_lista(ticker: str):
    lista = st.session_state["lista"]
    if ticker in lista:
        lista.remove(ticker)
    else:
        lista.append(ticker)
    if lista:
        st.query_params["w"] = ",".join(curto(t) for t in lista)
    elif "w" in st.query_params:
        del st.query_params["w"]


def abrir_lista():
    st.session_state["tickers"] = ", ".join(curto(t) for t in st.session_state["lista"])


def endereco_do_app() -> str:
    try:
        return st.context.url.split("?")[0]
    except Exception:
        return ""


def barra_de_acoes(ticker: str):
    salvo = ticker in st.session_state["lista"]
    with st.container(horizontal=True):
        st.button("Na minha lista" if salvo else "Salvar na lista",
                  icon=":material/bookmark_added:" if salvo else ":material/bookmark_add:",
                  key=f"lista_{ticker}", on_click=alternar_lista, args=(ticker,),
                  type="primary" if salvo else "secondary")
        with st.popover("Compartilhar", icon=":material/share:"):
            base = endereco_do_app()
            if base:
                link = f"{base}?t={quote(curto(ticker))}"
                st.caption("Link direto para esta ação:")
                st.code(link, language=None)
                st.link_button("Enviar por WhatsApp", icon=":material/send:",
                               url="https://wa.me/?text=" + quote(f"{curto(ticker)} no FINTAI: {link}"))
            else:
                st.caption(f"Copie o endereço desta página e acrescente ?t={curto(ticker)} ao final.")


# ------------------------------------------------------------ blocos visuais
def bloco_heroi(nome, ticker, moeda, r: Resultado, a: dict):
    estado = a["estado"]
    cor = COR_ESTADO[estado.codigo]
    var = ""
    if r.variacao_dia is not None:
        cv = VERDE if r.variacao_dia >= 0 else VERMELHO
        seta = "▲" if r.variacao_dia >= 0 else "▼"
        var = f"<span class='var' style='color:{cv}'>{seta} {pct(r.variacao_dia)} no dia</span>"
    chips = (f"<div class='chips'><span class='chip'>Percentil <b>{round(r.percentil)}</b></span>"
             f"<span class='chip'>Zona <b>{nome_da_zona(r.percentil).lower()}</b></span>"
             f"<span class='chip'>Tendência <b>{r.tendencia}</b></span></div>")
    st.markdown(
        f"<div class='heroi'><div class='nome'>{escape(nome)} · {escape(ticker)}</div>"
        f"<div class='sub'>Último pregão {r.data_ultimo:%d/%m/%Y} · {moeda} · Yahoo Finance</div>"
        f"<div class='linha'><span class='preco'>{dinheiro(r.preco_atual, moeda)}</span>{var}"
        f"<span class='pill' style='background:{cor}26;color:{cor}'>{estado.rotulo}</span></div>"
        f"<div class='estado'>{escape(estado.texto)}</div>{chips}</div>",
        unsafe_allow_html=True,
    )


def bloco_eventos(d: dict, moeda: str):
    ev = eventos(d, moeda)
    if not ev:
        st.markdown("<div class='eventos'><div class='evento'><div class='d'>—</div><div><div class='x'>"
                    "Sem eventos recentes nas fontes de dados do app.</div></div></div></div>",
                    unsafe_allow_html=True)
        return
    linhas = ""
    for e in ev:
        texto = escape(e["texto"])
        if e["link"].startswith("https://"):
            texto = f"<a href='{escape(e['link'], quote=True)}' target='_blank' rel='noopener'>{texto}</a>"
        linhas += (f"<div class='evento'><div class='d'>{e['data']:%d/%m/%Y}</div><div>"
                   f"<div class='t'>{escape(e['tipo'])}</div><div class='x'>{texto}</div></div></div>")
    st.markdown(f"<div class='eventos'>{linhas}</div>", unsafe_allow_html=True)


def bloco_faixa(r: Resultado, moeda):
    """Zonas de preço pelo percentil da faixa de 52 semanas."""
    z = zonas(r.minimo_1a, r.maximo_1a)
    grade(
        kpi("Zona de oportunidade", f"até {dinheiro(z.oportunidade_ate, moeda)}",
            f"até o percentil {P_OPORTUNIDADE}", "oport"),
        kpi("Zona neutra", f"{num(z.oportunidade_ate)} a {num(z.cara_acima)}",
            f"percentil {P_OPORTUNIDADE} a {P_CARO}", "neutra"),
        kpi("Zona cara", f"acima de {dinheiro(z.cara_acima, moeda)}",
            f"acima do percentil {P_CARO}", "cara"),
        classe="tres",
    )
    p = r.percentil
    fundo = (f"linear-gradient(90deg,{VERDE}66 0%,{VERDE}66 {P_OPORTUNIDADE}%,#2a3650 {P_OPORTUNIDADE}%,"
             f"#2a3650 {P_CARO}%,{AMBAR}66 {P_CARO}%,{AMBAR}66 100%)")
    st.markdown(
        f"<div class='faixa'><div class='trilho' style='background:{fundo}'>"
        f"<i style='left:{P_OPORTUNIDADE}%;background:{VERDE}'></i><i style='left:{P_CARO}%;background:{AMBAR}'></i>"
        f"<em style='left:{min(max(p, 24), 76):.1f}%'>VOCÊ ESTÁ AQUI ({round(p)}%)</em>"
        f"<u style='left:{p:.1f}%'></u></div>"
        f"<div class='pontas'><span>Mín. 52 sem. {num(r.minimo_1a)}</span><span>Máx. 52 sem. {num(r.maximo_1a)}</span></div>"
        f"<div class='legenda'><span style='--c:{VERDE}'>Oportunidade até {num(z.oportunidade_ate)}</span>"
        f"<span style='--c:{ARDOSIA}'>Neutra</span>"
        f"<span style='--c:{AMBAR}'>Cara acima de {num(z.cara_acima)}</span></div></div>",
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
        f"<div class='rolagem'><table class='t destaque'><thead><tr><th></th>{cab}</tr></thead>"
        f"<tbody>{corpo}</tbody></table></div>",
        unsafe_allow_html=True,
    )


def bloco_tendencia(r: Resultado, moeda):
    if r.mm200 is None:
        nota("Histórico curto demais para calcular a média de 200 dias.")
        return
    cor = {"Alta": VERDE, "Baixa": VERMELHO}.get(r.tendencia, TEXTO)
    incl = "" if r.inclinacao_mm200 is None else f"média de 200 dias {pct(r.inclinacao_mm200)} em 3 meses"
    if r.ifr is None:
        leitura = ""
    elif r.ifr >= 70:
        leitura = "Subiu rápido demais. Pressão de compra forte, pode corrigir."
    elif r.ifr <= 30:
        leitura = "Caiu rápido demais. Pressão de venda forte, pode repicar."
    else:
        leitura = "Neutro. Sem pressão de compra nem de venda."
    grade(
        kpi("Tendência", f"<span style='color:{cor}'>{r.tendencia}</span>", incl),
        kpi("Média de 200 dias", dinheiro(r.mm200, moeda),
            f"preço {pct((r.preco_atual / r.mm200 - 1) * 100)} da média"),
        kpi("IFR 14 dias", num(r.ifr, 0), leitura),
        classe="tres",
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
    mm200 = h["Close"].rolling(200).mean()
    h = h[h.index > h.index[-1] - pd.DateOffset(years=1)]
    mm200 = mm200.reindex(h.index)
    fig = go.Figure(
        go.Candlestick(
            x=h.index, open=h["Open"], high=h["High"], low=h["Low"], close=h["Close"],
            increasing_line_color=VERDE, decreasing_line_color=VERMELHO,
            increasing_fillcolor=VERDE, decreasing_fillcolor=VERMELHO, name="Preço",
        )
    )
    z = zonas(r.minimo_1a, r.maximo_1a)
    for y, nome, cor, canto in ((z.cara_acima, "Cara acima de", AMBAR, "top left"),
                                (z.oportunidade_ate, "Oportunidade até", VERDE, "bottom left")):
        fig.add_hline(y=y, line_color=cor, line_dash="dash", line_width=1.3,
                      annotation_text=f"{nome} {num(y)}", annotation_position=canto,
                      annotation_font=dict(color=cor, size=11))
    fig.add_scatter(x=mm200.index, y=mm200, mode="lines", name="MM200",
                    line=dict(color=AZUL, width=2), hoverinfo="skip")
    fig.update_layout(xaxis_rangeslider_visible=False)
    return _estilo(fig, 420)


def grafico_escada(pares, nome_indice):
    """pares: [(rótulo, retorno da ação, retorno do índice ou None)]."""
    x = [p[0] for p in pares]
    y = [p[1] for p in pares]
    fig = go.Figure()
    fig.add_bar(x=x, y=y, name="Ação", marker_color=[VERDE if v >= 0 else VERMELHO for v in y],
                marker_line_width=0, opacity=0.92, text=[pct(v, 0) for v in y],
                textposition="outside", textfont=dict(color=TEXTO, size=13), cliponaxis=False)
    if any(p[2] is not None for p in pares):
        yi = [p[2] for p in pares]
        fig.add_bar(x=x, y=yi, name=nome_indice, marker_color=ARDOSIA, marker_line_width=0,
                    text=[pct(v, 0) if v is not None else "" for v in yi], textposition="outside",
                    textfont=dict(color=SUAVE, size=12), cliponaxis=False)
    fig.add_hline(y=0, line_color=SUAVE, line_width=1)
    fig.update_layout(barmode="group", bargap=0.18, bargroupgap=0.04, yaxis_ticksuffix="%")
    fig.update_yaxes(rangemode="tozero")
    return _estilo(fig, 330).update_layout(margin=dict(l=8, r=8, t=40, b=8))


def bloco_retorno(ticker: str, r: Resultado):
    nome_indice, serie = indice_de(ticker)
    pares = []
    for rotulo, anos, ret in (("1 ano", 1, r.retorno_1a), ("3 anos", 3, r.retorno_3a),
                              ("5 anos", 5, r.retorno_5a)):
        if ret is None:
            continue
        ri = None
        if serie is not None and len(serie):
            try:
                ri = retorno_periodo(serie, anos)
            except Exception:
                ri = None
        pares.append((rotulo, ret, ri))
    if not pares:
        nota("Histórico curto demais para calcular retornos.")
        return
    st.plotly_chart(grafico_escada(pares, nome_indice), width="stretch", key=f"escada_{ticker}",
                    theme=None, config={"displayModeBar": False})
    linhas = ""
    for rotulo, ret, ri in pares:
        if ri is None:
            linhas += (f"<div><b>Retorno acumulado: {pct(ret, 0)} em {rotulo}</b><br>"
                       f"{nome_indice}: sem dados para o período</div>")
            continue
        dif = ret - ri
        cor = VERDE if dif >= 0 else VERMELHO
        onde = "acima" if dif >= 0 else "abaixo"
        linhas += (f"<div><b>Retorno acumulado: {pct(ret, 0)} em {rotulo}</b><br>"
                   f"{nome_indice}: {pct(ri, 0)} em {rotulo} | Diferença: "
                   f"<b style='color:{cor}'>{'+' if dif >= 0 else '-'}{num(abs(dif), 0)} p.p. {onde} do índice</b></div>")
    st.markdown(f"<div class='bench'>{linhas}</div>", unsafe_allow_html=True)


# ------------------------------------------------------------ fundamentos
TEXTO_CRITERIO = {
    "pl": {
        "Favorável": "A ação está mais barata em relação ao lucro do que na média do último ano.",
        "Neutro": "O preço em relação ao lucro está perto da média do último ano.",
        "Desfavorável": "A ação está mais cara em relação ao lucro do que na média do último ano.",
        "Sem dados": "O Yahoo Finance não traz o lucro por ação deste ativo.",
    },
    "dy": {
        "Favorável": "Os dividendos rendem mais sobre o preço de hoje do que na média do último ano.",
        "Neutro": "O rendimento dos dividendos está perto da média do último ano.",
        "Desfavorável": "Os dividendos rendem menos sobre o preço de hoje do que na média do último ano.",
        "Sem dados": "Sem histórico de proventos suficiente para comparar.",
    },
    "lpa": {
        "Favorável": "O lucro por ação cresceu em relação a 12 meses atrás.",
        "Neutro": "O lucro por ação está perto do nível de 12 meses atrás.",
        "Desfavorável": "O lucro por ação caiu em relação a 12 meses atrás.",
        "Sem dados": "O Yahoo Finance não traz o histórico de lucros deste ativo.",
    },
}


def cartao_criterio(chave, nome, atual, referencia, rotulo_ref, maior_e_melhor, fmt, extra=""):
    av = avaliar_criterio(atual, referencia, maior_e_melhor=maior_e_melhor)
    cor = COR_STATUS[av.status]
    return (
        f"<div class='crit'><div class='topo'><span class='nome'>{nome}</span>"
        f"<span class='st' style='color:{cor}'>{av.icone} {av.status}</span></div>"
        f"<div class='vals'><div><span>Atual</span><b>{fmt(atual)}</b></div>"
        f"<div><span>{rotulo_ref}</span><b>{fmt(referencia)}</b></div>"
        f"<div><span>Diferença</span><b style='color:{cor}'>{pct(av.diferenca, 0)}</b></div></div>"
        f"<div class='n'>{TEXTO_CRITERIO[chave][av.status]}{extra}</div></div>"
    )


@st.dialog("Como calculamos")
def modal_formulas():
    st.markdown(
        """
**Preço vs Lucro**
P/L atual = preço ÷ lucro por ação (LPA) dos últimos 12 meses.
P/L médio 12m = média do P/L de cada pregão do último ano, usando o LPA já divulgado em cada data.
Sem histórico de lucros, a média é estimada: preço médio do ano ÷ LPA atual.

**Dividendos**
DY atual = proventos pagos nos últimos 12 meses ÷ preço de hoje.
DY médio 12m = média do DY de cada pregão do último ano.

**Crescimento de Lucro**
LPA atual = soma dos 4 últimos trimestres divulgados.
LPA 12m atrás = soma dos 4 trimestres anteriores.
Sem 8 trimestres de dados, compara os dois últimos anos fiscais.

**Diferença e status**
Diferença = (atual − referência) ÷ referência.
Até 5% para qualquer lado: ⚠️ Neutro. Além disso: ✅ Favorável ou ❌ Desfavorável.
P/L menor é melhor; DY e LPA maiores são melhores.
Sem o dado no Yahoo Finance: ➖ Sem dados (o app não estima).
"""
    )


def bloco_fundamentos(ticker: str, f: dict, moeda: str):
    with st.expander("Fundamentos: os 3 critérios, um a um", expanded=True):
        estimado = " Média estimada pelo preço médio do ano." if f["metodo"] == "simplificado" else ""
        base = f" Base: {f['base_lpa']}." if f["base_lpa"] else ""
        grade(
            cartao_criterio("pl", "Preço vs Lucro (P/L)", f["pl"], f["pl_medio"], "Média 12m", False,
                            lambda v: num(v, 1), estimado),
            cartao_criterio("dy", "Dividendos (DY)", f["dy_hoje"], f["dy_medio"], "Média 12m", True,
                            lambda v: "—" if v is None else f"{num(v, 1)}%"),
            cartao_criterio("lpa", "Crescimento de Lucro (LPA)", f["lpa_agora"], f["lpa_antes"],
                            "12m atrás", True, lambda v: dinheiro(v, moeda), base),
            classe="larga",
        )
        st.write("")
        if st.button("Ver como calculamos", icon=":material/calculate:", key=f"calc_{ticker}"):
            modal_formulas()


def bloco_preco_justo(r: Resultado, f: dict, moeda):
    def cartao(rotulo, valor, base):
        if not valor:
            return kpi(rotulo, "—", "sem dados suficientes")
        margem = (valor / r.preco_atual - 1) * 100
        cor = VERDE if margem >= 0 else VERMELHO
        situacao = "de desconto" if margem >= 0 else "acima do justo"
        return kpi(rotulo, dinheiro(valor, moeda),
                   f"<span style='color:{cor};font-weight:600'>{num(abs(margem), 0)}% {situacao}</span><br>{base}")

    grade(
        cartao("Preço-teto Bazin", f["bazin"],
               f"dividendo médio {num(f['div_medio'])} ÷ 6%" if f["div_medio"] else ""),
        cartao("Preço justo Graham", f["graham"],
               f"LPA {num(f['lpa'])} · VPA {num(f['vpa'])}" if f["graham"] else ""),
        cartao("Justo pelo P/L histórico", f["justo_pl"],
               f"{f['rotulo_ref']}: {num(f['pl_ref'])}" if f["pl_ref"] else ""),
    )


# ------------------------------------------------------------ teste histórico
def bloco_backtest(a: dict):
    bt = a["bt"]
    if bt["anos"] < 1:
        nota("Histórico curto demais para testar os sinais.")
        return
    ref = bt["referencia"]

    def cartao(titulo, dados, selo, rotulo_acerto):
        classe = "ok" if selo.validado else "nao"
        acerto = "—" if dados["acerto_12m"] is None else f"{num(dados['acerto_12m'], 0)}%"
        return (
            f"<div class='crit'><div class='topo'><span class='nome'>{titulo}</span>"
            f"<span class='selo {classe}'>{selo.rotulo}</span></div>"
            f"<div class='vals'><div><span>Semanas</span><b>{dados['casos']}</b></div>"
            f"<div><span>Retorno 12m</span><b>{pct(dados['retorno_12m'], 0)}</b></div>"
            f"<div><span>{rotulo_acerto}</span><b>{acerto}</b></div></div>"
            f"<div class='n' style='color:{TEXTO}'>{escape(selo.texto)}</div></div>"
        )

    sc, sv = a["selo_compra"], a["selo_venda"]
    grade(
        cartao(f"{'Sinal de compra' if sc.validado else 'Preço baixo'} (percentil ≤ {P_COMPRA})",
               bt["compra"], sc, "Subiu em"),
        cartao(f"{'Sinal de venda' if sv.validado else 'Preço alto'} (percentil ≥ {P_CARO})",
               bt["venda"], sv, "Caiu em"),
        classe="larga",
    )
    positivo = "—" if ref["acerto_12m"] is None else f"{num(ref['acerto_12m'], 0)}%"
    nota(f"<b>Referência:</b> comprar em uma semana qualquer rendeu em média "
         f"<b>{pct(ref['retorno_12m'], 0)}</b> em 12 meses (subiu em {positivo} das vezes). "
         f"Teste com {num(bt['anos'], 1)} anos de histórico, semana a semana, usando só os dados "
         "disponíveis em cada data. Retornos com dividendos. Resultado passado não garante resultado futuro.")


# ------------------------------------------------------------ painel
def painel(ticker: str):
    with st.spinner(f"Buscando {ticker}..."):
        d = baixar(ticker)
    hist, info = d["hist"], d["info"]
    r = calcular(hist, d["divs"])
    moeda = info.get("currency") or ("BRL" if ticker.endswith(".SA") else "USD")
    f = fundamentos(d, r)
    a = analisar(ticker, d, r, f, moeda)
    nome = info.get("longName") or info.get("shortName") or ticker

    barra_de_acoes(ticker)
    bloco_heroi(nome, ticker, moeda, r, a)

    secao("O que mudou?", "últimos eventos")
    bloco_eventos(d, moeda)

    secao("Faixa de preço", "percentil das últimas 52 semanas")
    bloco_faixa(r, moeda)

    secao("Tendência e força")
    bloco_tendencia(r, moeda)

    secao("Mínimo, máximo e fechamento", f"valores em {SIMBOLO.get(moeda, moeda)}")
    bloco_tabela(r)
    st.write("")
    grade(
        kpi(f"Máxima de {r.data_ultimo.year}", dinheiro(r.maxima_ano, moeda)),
        kpi(f"Mínima de {r.data_ultimo.year}", dinheiro(r.minima_ano, moeda)),
    )

    secao("Preço em 12 meses", "linha azul: média de 200 dias")
    st.plotly_chart(grafico_preco(hist, r), width="stretch", key=f"preco_{ticker}",
                    theme=None, config={"displayModeBar": False})

    secao("Fundamentos")
    bloco_fundamentos(ticker, f, moeda)

    secao("Preço justo", "referência")
    bloco_preco_justo(r, f, moeda)

    secao("Indicadores")
    pl, pl_medio = f["pl"], f["pl_medio"]
    nota_pl = f"{pct((pl / pl_medio - 1) * 100)} vs. média de 12m" if pl and pl_medio else ""
    nota_medio = {"trimestral": "com o LPA de cada trimestre",
                  "simplificado": "preço médio ÷ LPA atual"}.get(f["metodo"], "")
    grade(
        kpi("P/L atual", num(pl), nota_pl),
        kpi("P/L médio 12 meses", num(pl_medio), nota_medio),
        kpi("LPA básico", dinheiro(f["lpa"], moeda) if f["lpa"] is not None else "—", "últimos 12 meses"),
        kpi("Dividendo anual", dinheiro(f["div"], moeda), "pago em 12 meses"),
        kpi("Dividend yield", f"{num(f['dy'])}%"),
        kpi("Ações em circulação", quantidade(f["acoes"])),
    )

    secao("Retorno acumulado", "com dividendos, comparado ao índice")
    bloco_retorno(ticker, r)

    secao("Os sinais funcionaram no passado?", "teste com até 10 anos de histórico")
    bloco_backtest(a)

    with st.expander("Como os números são calculados"):
        st.markdown(
            f"""
- **Percentil** = (preço − mínima de 52 semanas) ÷ (máxima − mínima). 0 é a mínima do ano,
  100 é a máxima.
- **Zonas**: oportunidade até o percentil {P_OPORTUNIDADE}, neutra de {P_OPORTUNIDADE} a {P_CARO},
  cara acima de {P_CARO}.
- **Estados**:
  - **COMPRAR**: preço até o percentil {P_COMPRA} e sinal de compra validado no histórico do ativo.
  - **AGUARDAR**: preço entre os percentis {P_COMPRA} e {P_CARO}, ou preço baixo sem validação.
  - **CARO**: preço no percentil {P_CARO} ou acima. Não é sinal de venda.
  - **VENDER**: só com preço na zona cara e sinal de venda validado no histórico, ou quando o
    fundamento quebrou (2 trimestres seguidos de prejuízo, ou dívida líquida ÷ EBITDA acima de 4).
- **Sinal validado**: nos 12 meses seguintes, acerto acima de 60% e retorno melhor do que a
  referência (comprar em uma semana qualquer), com pelo menos 8 semanas de casos. Na compra,
  acerto = vezes em que a ação subiu; na venda, vezes em que caiu.
- **Média de 52 semanas**: mínima, máxima e fechamento de cada uma das últimas 52 semanas,
  e a média de cada uma. **30 dias**: os mesmos números para os últimos 30 dias corridos.
- **Tendência**: *Alta* quando a média de 200 dias subiu mais de 1% em 3 meses e o preço está
  acima dela; *Baixa* quando caiu mais de 1% e o preço está abaixo; senão *Lateral*.
- **Preço-teto Bazin** = média dos dividendos anuais (até 3 anos) ÷ 6%.
  **Graham** = raiz de (22,5 × LPA × valor patrimonial por ação).
  **Justo pelo P/L histórico** = P/L médio da própria empresa × LPA atual.
- **Retornos** usam o preço ajustado (inclui dividendos e desdobramentos).
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
            d = baixar(t)
            r = calcular(d["hist"], d["divs"])
            moeda = d["info"].get("currency") or ("BRL" if t.endswith(".SA") else "USD")
            f = fundamentos(d, r)
            a = analisar(t, d, r, f, moeda)
            z = zonas(r.minimo_1a, r.maximo_1a)
            linhas.append({
                "Ticker": t, "Preço": r.preco_atual, "Estado": a["estado"].codigo,
                "Percentil": round(r.percentil), "Oportunidade até": z.oportunidade_ate,
                "Cara acima de": z.cara_acima, "Tendência": r.tendencia,
                "P/L": f["pl"], "DY %": f["dy"], "Ret. 1a %": r.retorno_1a,
                "Ret. 3a %": r.retorno_3a, "Ret. 5a %": r.retorno_5a,
            })
        except Exception as e:
            linhas.append({"Ticker": t, "Estado": f"Erro: {e}"})
    df = pd.DataFrame(linhas).set_index("Ticker")
    st.dataframe(df.style.format(precision=2, na_rep="—"), width="stretch")


# ------------------------------------------------------------ página
st.markdown(CSS, unsafe_allow_html=True)
st.markdown(
    "<div class='marca'><b>FINT<i>AI</i></b><span>Ações do Brasil e dos EUA em um só painel</span></div>",
    unsafe_allow_html=True,
)

if "lista" not in st.session_state:
    salvos = st.query_params.get("w", "")
    st.session_state["lista"] = list(dict.fromkeys(
        normalizar_ticker(t) for t in salvos.split(",") if t.strip()))
if "tickers" not in st.session_state:
    st.session_state["tickers"] = st.query_params.get("t", "PETR4, AAPL")

entrada = st.text_input(
    "Tickers", key="tickers",
    help="Separe por vírgula. Brasileiras podem ir sem o .SA (PETR4, ITUB4, BOVA11); americanas como AAPL, MSFT.",
    placeholder="PETR4, AAPL, MSFT",
)
tickers = list(dict.fromkeys(normalizar_ticker(t) for t in entrada.split(",") if t.strip()))

if st.session_state["lista"]:
    st.button("Abrir minha lista: " + ", ".join(curto(t) for t in st.session_state["lista"]),
              icon=":material/bookmarks:", on_click=abrir_lista, key="abrir_lista")

if not tickers:
    st.info("Digite pelo menos um ticker.")
    st.stop()

st.query_params["t"] = ",".join(curto(t) for t in tickers)

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
