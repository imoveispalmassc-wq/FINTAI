"""FINTAI: análise de ações do Brasil e dos EUA.

Rodar:  streamlit run app.py
"""
from __future__ import annotations

import hashlib
import importlib
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import streamlit as st
import yfinance as yf

import calculos
import tela.dados
import utils.benchmarks
import utils.formato
import utils.lynch
import utils.override
import utils.percentile
import utils.signals
import utils.simons

# O Streamlit Cloud pode manter versões antigas dos módulos na memória depois de uma
# atualização; recarregar (na ordem das dependências) mantém tudo na mesma versão.
for _modulo in (utils.formato, utils.percentile, utils.signals, utils.benchmarks, utils.lynch, utils.override,
                utils.simons, calculos, tela.dados):
    importlib.reload(_modulo)

from calculos import calcular, normalizar_ticker, retorno_periodo
from tela.dados import montar
from utils.benchmarks import retornos_brasil
from utils.percentile import zonas

st.set_page_config(page_title="FINTAI", page_icon="📈", layout="wide")

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Space+Grotesk:wght@600;700&display=swap');
.stApp { font-family: 'Inter', system-ui, sans-serif; }
.block-container { padding-top: 2.2rem; max-width: 1150px; }
#MainMenu, footer { visibility: hidden; }
[data-testid='stToolbarActions'], [data-testid='stMainMenu'], [data-testid='stAppDeployButton'] { display:none !important; }
.marca { display:flex; align-items:baseline; gap:.7rem; flex-wrap:wrap; margin-bottom:.4rem; }
.marca b { font-family:'Space Grotesk',sans-serif; font-size:2rem; letter-spacing:.04em; color:#e8edf5; }
.marca b i { font-style:normal; color:#5b8def; }
.marca span { color:#8c99b0; font-size:.95rem; }
.rodape { color:#8c99b0; font-size:.76rem; margin-top:1.5rem; text-align:center; }
</style>
"""

# Tela de detalhes: um componente só, montado com o pacote de dados de cada ticker.
_PASTA = Path(__file__).parent / "tela"
tela_detalhe = st.components.v2.component(
    "fintai_detalhe",
    html=(_PASTA / "detalhe.html").read_text(encoding="utf-8"),
    css=(_PASTA / "detalhe.css").read_text(encoding="utf-8"),
    js=(_PASTA / "detalhe.js").read_text(encoding="utf-8"),
)


def curto(ticker: str) -> str:
    """PETR4.SA -> PETR4 (como o usuário digita)."""
    return ticker[:-3] if ticker.endswith(".SA") else ticker


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


@st.cache_data(ttl=900, show_spinner=False)
def baixar(ticker: str) -> dict:
    tk = yf.Ticker(ticker)
    hist = tk.history(period="max", interval="1d", auto_adjust=False)
    if hist is None or hist.empty:
        raise ValueError(f"Não encontrei dados para {ticker}. Confira o código.")
    d = {"hist": hist, "info": {}, "lpa_tri": None, "lucro_tri": None, "lpa_anual": None, "intraday": {},
         "receita_anual": None, "est_lucro": None, "est_receita": None, "est_cresc": None}

    def tentar(funcao):
        try:
            return funcao()
        except Exception:
            return None

    d["info"] = tentar(lambda: dict(tk.info or {})) or {}
    d["lpa_tri"] = tentar(lambda: tk.get_earnings_dates(limit=28)["Reported EPS"].dropna())
    d["lucro_tri"] = tentar(lambda: _linha(tk.quarterly_income_stmt, ["Net Income", "Net Income Common Stockholders"]))
    d["lpa_anual"] = tentar(lambda: _linha(tk.income_stmt, ["Basic EPS", "Diluted EPS"]))
    d["receita_anual"] = tentar(lambda: _linha(tk.income_stmt, ["Total Revenue", "Operating Revenue"]))
    # estimativas dos analistas (modo Lynch)
    d["est_lucro"] = tentar(lambda: tk.earnings_estimate)
    d["est_receita"] = tentar(lambda: tk.revenue_estimate)
    d["est_cresc"] = tentar(lambda: tk.growth_estimates)
    for chave, periodo, intervalo in (("hoje", "1d", "5m"), ("1s", "5d", "30m"), ("1m", "1mo", "60m")):
        d["intraday"][chave] = tentar(lambda: tk.history(period=periodo, interval=intervalo, auto_adjust=False))
    return d


@st.cache_data(ttl=3600, show_spinner=False)
def baixar_indice(simbolos: tuple[str, ...]):
    """Fechamentos do índice de referência (tenta os símbolos na ordem). Devolve (série, símbolo usado)."""
    for s in simbolos:
        try:
            h = yf.Ticker(s).history(period="10y", interval="1d", auto_adjust=False)
            if h is not None and not h.empty:
                c = h["Close"].dropna()
                if c.index.tz is not None:
                    c.index = c.index.tz_localize(None)
                return c, s
        except Exception:
            continue
    return None, None


# muda quando o código dos cálculos muda: um deploy novo não reaproveita resultado antigo do cache
VERSAO_CALCULO = hashlib.md5(b"".join(open(m.__file__, "rb").read() for m in (
    calculos, tela.dados, utils.lynch, utils.override, utils.benchmarks)) + open(__file__, "rb").read()).hexdigest()[:10]


@st.cache_data(ttl=86400, show_spinner=False)
def brasil(dia: str, versao: str = "") -> dict:
    """CDI, Selic, IPCA e Poupança acumulados em 1, 3 e 5 anos (cache diário)."""
    return retornos_brasil(pd.Timestamp(dia))


def comparadores(ticker: str, fim: pd.Timestamp, info: dict) -> tuple[dict, str]:
    usados = {}

    def do_indice(simbolos):
        serie, usados[simbolos[0]] = baixar_indice(simbolos)
        if serie is None or serie.empty:
            return [None, None, None]
        # mesma data final da ação (índice de outra bolsa pode ter pregão a mais ou a menos)
        serie = serie[serie.index.normalize() <= pd.Timestamp(fim).normalize()]
        if serie.empty:
            return [None, None, None]
        saida = []
        for anos in (1, 3, 5):
            try:
                v = retorno_periodo(serie, anos)
                saida.append(None if v is None else round(float(v), 2))
            except Exception:
                saida.append(None)
        return saida

    br = brasil(f"{fim:%Y-%m-%d}", VERSAO_CALCULO)
    arred = lambda lista: [None if v is None else round(v, 2) for v in lista]
    todos = {
        "nasdaq": {"nome": "Nasdaq", "curto": "Nasdaq", "artigo": "do índice", "moeda": "US$", "v": do_indice(("^IXIC",))},
        "sp500": {"nome": "S&P 500", "curto": "S&P", "artigo": "do índice", "moeda": "US$", "v": do_indice(("^SP500TR", "^GSPC"))},
        "ibov": {"nome": "Ibovespa", "curto": "Ibovespa", "artigo": "do índice", "moeda": "R$", "v": do_indice(("^BVSP",))},
        "cdi": {"nome": "CDI", "curto": "CDI", "artigo": "do CDI", "moeda": "R$", "v": arred(br["cdi"])},
        "selic": {"nome": "Selic", "curto": "Selic", "artigo": "da Selic", "moeda": "R$", "v": arred(br["selic"])},
        "ipca": {"nome": "IPCA", "curto": "IPCA", "artigo": "do IPCA", "moeda": "R$", "v": arred(br["ipca"])},
        "poupanca": {"nome": "Poupança", "curto": "Poupança", "artigo": "da poupança", "moeda": "R$", "v": arred(br["poupanca"])},
    }
    # sem o S&P 500 com dividendos (^SP500TR), o ^GSPC é só preço: o nome avisa
    if usados.get("^SP500TR") == "^GSPC":
        todos["sp500"]["nome"] = "S&P 500 (sem dividendos)"
    # Bolsa da ação decide o primeiro comparador: B3 = Ibovespa, Nasdaq = Nasdaq, demais = S&P 500
    bolsa = f"{info.get('exchange', '')} {info.get('fullExchangeName', '')}".lower()
    if ticker.endswith(".SA"):
        ordem = ["ibov", "cdi", "selic", "ipca", "poupanca", "sp500", "nasdaq"]
    elif "nasdaq" in bolsa or info.get("exchange") in ("NMS", "NGM", "NCM"):
        ordem = ["nasdaq", "sp500", "ibov", "cdi", "selic", "ipca", "poupanca"]
    else:
        ordem = ["sp500", "nasdaq", "ibov", "cdi", "selic", "ipca", "poupanca"]
    padrao = ordem[0]
    return {k: todos[k] for k in ordem}, padrao


@st.cache_data(ttl=900, show_spinner=False)
def pacote(ticker: str, versao: str = "") -> dict:
    """Tudo o que a tela de um ticker precisa, calculado uma única vez."""
    d = baixar(ticker)
    hist = d["hist"]
    proventos = hist["Dividends"][hist["Dividends"] > 0] if "Dividends" in hist else None
    r = calcular(hist, proventos)
    comps, padrao = comparadores(ticker, r.data_ultimo, d["info"])
    return montar(ticker, d, r, comps, padrao)


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


# ------------------------------------------------------------ telas
def painel(ticker: str):
    with st.spinner(f"Buscando {ticker}..."):
        dados = pacote(ticker, VERSAO_CALCULO)
    barra_de_acoes(ticker)
    tela_detalhe(data={"dados": dados}, key=f"tela_{ticker}")


def resumo(tickers: list[str]):
    linhas = []
    for t in tickers:
        try:
            p = pacote(t, VERSAO_CALCULO)
            z = zonas(p["min52"], p["max52"])
            dy = p["dividendo"] / p["preco"] * 100 if p["dividendo"] is not None and p["preco"] else None
            linhas.append({
                "Ticker": t, "Preço": p["preco"], "Estado": p["decisao"]["codigo"], "Zona": p["decisao"]["zona"],
                "Oportunidade até": z.oportunidade_ate, "Cara acima de": z.cara_acima,
                "P/L": p["pl"], "DY %": dy, "Ret. 1a %": p["retorno"]["total"][0],
                "Ret. 3a %": p["retorno"]["total"][1], "Ret. 5a %": p["retorno"]["total"][2],
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
    st.subheader("Comparativo")
    resumo(tickers)

abas = st.tabs(tickers)
for aba, t in zip(abas, tickers):
    with aba:
        try:
            painel(t)
        except Exception as e:
            st.error(f"{t}: {e}")

st.markdown("<div class='rodape'>Ferramenta de estudo, não é recomendação de investimento.</div>",
            unsafe_allow_html=True)
