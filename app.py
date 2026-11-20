"""FINTAI: análise de ações do Brasil e dos EUA.

Rodar:  streamlit run app.py
"""
from __future__ import annotations

import base64
import concurrent.futures as cf
import hashlib
import importlib
import json
import time
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

LOGO = Path(__file__).parent / "assets" / "logo.png"
st.set_page_config(page_title="FINTAI", page_icon=str(LOGO), layout="wide")

MAX_TICKERS = 20          # limite de ações no comparativo, para manter a busca rápida
COTACOES_TTL = 60         # segundos de cache da cotação em lote (session_state)

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Space+Grotesk:wght@600;700&display=swap');
.stApp { font-family: 'Inter', system-ui, sans-serif; }
.block-container { padding-top: 2.2rem; max-width: 1150px; }
#MainMenu, footer { visibility: hidden; }
[data-testid='stToolbarActions'], [data-testid='stMainMenu'], [data-testid='stAppDeployButton'] { display:none !important; }
.marca { display:flex; align-items:center; gap:.7rem; flex-wrap:wrap; margin-bottom:.4rem; }
.marca img { height:2.8rem; width:2.8rem; border-radius:22%; }
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


@st.cache_data(ttl=60, show_spinner=False)   # mesmo ritmo do fragment de painel(): cotação mais dinâmica
def baixar(ticker: str) -> dict:
    tk = yf.Ticker(ticker)
    hist = tk.history(period="max", interval="1d", auto_adjust=False)
    if hist is None or hist.empty:
        raise ValueError(f"Não encontrei dados para {ticker}. Confira o código.")
    d = {"hist": hist, "info": {}, "lpa_tri": None, "lucro_tri": None, "lpa_anual": None, "intraday": {},
         "receita_anual": None, "receita_tri": None, "est_lucro": None, "est_receita": None, "est_cresc": None}

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
    d["receita_tri"] = tentar(lambda: _linha(tk.quarterly_income_stmt, ["Total Revenue", "Operating Revenue"]))
    # estimativas dos analistas (modo Lynch)
    d["est_lucro"] = tentar(lambda: tk.earnings_estimate)
    d["est_receita"] = tentar(lambda: tk.revenue_estimate)
    d["est_cresc"] = tentar(lambda: tk.growth_estimates)
    for chave, periodo, intervalo in (("hoje", "1d", "5m"), ("1s", "5d", "30m"), ("1m", "1mo", "60m")):
        d["intraday"][chave] = tentar(lambda: tk.history(period=periodo, interval=intervalo, auto_adjust=False))
    return d


@st.cache_data(ttl=900, show_spinner=False)   # mesmo ritmo da cotação da ação (atraso de ~15 min)
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


def _extrair_precos(bruto: pd.DataFrame | None, tickers: list[str]) -> dict[str, dict]:
    """Preço e variação % do dia de cada ticker a partir de um só DataFrame do yf.download.

    Função pura (sem rede, sem Streamlit): fácil de testar e reaproveitar. Um ticker que não
    aparece no resultado, ou vem com histórico vazio, fica com erro=True — nunca derruba os outros."""
    dados = {t: {"preco": None, "variacao": None, "erro": True} for t in tickers}
    if bruto is None or bruto.empty:
        return dados
    multi = isinstance(bruto.columns, pd.MultiIndex)
    for t in tickers:
        try:
            fechamentos = (bruto[t]["Close"] if multi else bruto["Close"]).dropna()
            if fechamentos.empty:
                continue
            preco = float(fechamentos.iloc[-1])
            variacao = round((preco / float(fechamentos.iloc[-2]) - 1) * 100, 2) if len(fechamentos) >= 2 else None
            dados[t] = {"preco": preco, "variacao": variacao, "erro": False}
        except (KeyError, IndexError, ValueError, TypeError):
            continue   # este ticker fica "Cotação indisponível"; os demais seguem normalmente
    return dados


def get_cotacoes(tickers: list[str]) -> dict[str, dict]:
    """Preço e variação % do dia de vários tickers num ÚNICO request em lote ao Yahoo Finance
    (yf.download com threads=True — nunca um loop de 1 request por ticker), com timeout curto,
    cache de 60s em st.session_state (não rebusca a cada clique) e spinner enquanto carrega.

    Devolve {ticker: {"preco": float|None, "variacao": float|None, "erro": bool}}. Se o Yahoo
    falhar ou demorar, os tickers afetados voltam com erro=True ("Cotação indisponível") em vez
    de travar a tela."""
    tickers = list(dict.fromkeys(tickers))[:MAX_TICKERS]
    if not tickers:
        return {}
    cache = st.session_state.setdefault("_cotacoes_cache", {})
    chave = ",".join(sorted(tickers))
    agora = time.monotonic()
    guardado = cache.get(chave)
    if guardado and agora - guardado["quando"] < COTACOES_TTL:
        return guardado["dados"]
    with st.spinner("Buscando cotações..."):
        try:
            bruto = yf.download(tickers=tickers, period="5d", interval="1d", group_by="ticker",
                                threads=True, timeout=8, progress=False, auto_adjust=False)
        except Exception:
            bruto = None
        dados = _extrair_precos(bruto, tickers)
    cache[chave] = {"quando": agora, "dados": dados}
    return dados


# muda quando o código dos cálculos muda: um deploy novo não reaproveita resultado antigo do cache
VERSAO_CALCULO = hashlib.md5(b"".join(open(m.__file__, "rb").read() for m in (
    calculos, tela.dados, utils.lynch, utils.override, utils.benchmarks, utils.simons, utils.signals,
    utils.percentile, utils.formato)) + open(__file__, "rb").read()).hexdigest()[:10]


@st.cache_data(ttl=86400, show_spinner=False)
def brasil(dia: str, versao: str = "") -> dict:
    """CDI, Selic, IPCA e Poupança acumulados em 1, 3 e 5 anos (cache diário).

    Se algum indicador falhar, levanta exceção: o Streamlit não guarda erro no cache e a próxima
    abertura tenta de novo (o resultado parcial vai na exceção)."""
    r = retornos_brasil(pd.Timestamp(dia))
    if r.get("falhas"):
        raise BrasilIncompleto(r)
    return r


class BrasilIncompleto(Exception):
    pass


def brasil_ou_parcial(dia: str) -> dict:
    try:
        return brasil(dia, VERSAO_CALCULO)
    except BrasilIncompleto as e:
        return e.args[0]


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

    def pontos_indice(simbolos):
        """Valor do índice no início e no fim de cada período, para conferir com outras fontes."""
        serie, _ = baixar_indice(simbolos)
        if serie is None or serie.empty:
            return [None, None, None]
        serie = serie[serie.index.normalize() <= pd.Timestamp(fim).normalize()]
        saida = []
        for anos in (1, 3, 5):
            base = serie[serie.index <= serie.index[-1] - pd.DateOffset(years=anos)]
            saida.append(None if base.empty or serie.empty else
                         f"{base.iloc[-1]:,.2f} em {base.index[-1]:%d/%m/%Y} → {serie.iloc[-1]:,.2f} em {serie.index[-1]:%d/%m/%Y}"
                         .replace(",", "X").replace(".", ",").replace("X", "."))
        return saida

    br = brasil_ou_parcial(f"{fim:%Y-%m-%d}")
    arred = lambda lista: [None if v is None else round(v, 2) for v in lista]
    todos = {
        "nasdaq": {"nome": "Nasdaq", "curto": "Nasdaq", "artigo": "do índice", "moeda": "US$", "v": do_indice(("^IXIC",)), "conta": pontos_indice(("^IXIC",))},
        "sp500": {"nome": "S&P 500", "curto": "S&P", "artigo": "do índice", "moeda": "US$", "v": do_indice(("^SP500TR", "^GSPC")), "conta": pontos_indice(("^SP500TR", "^GSPC"))},
        "ibov": {"nome": "Ibovespa", "curto": "Ibovespa", "artigo": "do índice", "moeda": "R$", "v": do_indice(("^BVSP",)), "conta": pontos_indice(("^BVSP",))},
        "cdi": {"nome": "CDI", "curto": "CDI", "artigo": "do CDI", "moeda": "R$", "v": arred(br["cdi"]), "conta": br.get("periodos", {}).get("cdi", [None, None, None]), "taxaAno": br.get("taxas", {}).get("cdi")},
        "selic": {"nome": "Selic", "curto": "Selic", "artigo": "da Selic", "moeda": "R$", "v": arred(br["selic"]), "conta": br.get("periodos", {}).get("selic", [None, None, None]), "taxaAno": br.get("taxas", {}).get("selic")},
        "ipca": {"nome": "IPCA", "curto": "IPCA", "artigo": "do IPCA", "moeda": "R$", "v": arred(br["ipca"]), "conta": br.get("periodos", {}).get("ipca", [None, None, None])},
        "poupanca": {"nome": "Poupança", "curto": "Poupança", "artigo": "da poupança", "moeda": "R$", "v": arred(br["poupanca"]), "conta": br.get("periodos", {}).get("poupanca", [None, None, None])},
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


@st.cache_data(ttl=86400, show_spinner=False)   # lista de ~10 mil tickers da SEC: a mesma pra
def _tickers_sec_cache(cab: dict) -> dict:      # qualquer ticker, baixa 1x por dia (não a cada ticker digitado)
    import utils.fetch_guidance as fg
    try:
        return fg.tickers_sec(cab)
    except Exception:
        return {}


@st.cache_data(ttl=86400, show_spinner=False)   # 10-K/10-Q não mudam mais que 1x por trimestre
def lpa_anual_eua(ticker: str) -> list[dict]:
    """Histórico anual de LPA diluído (GAAP), direto da SEC (10-K) — qualquer ticker dos EUA, sem
    precisar estar cadastrado em utils/guidance_tickers.json. Substitui o income_stmt do Yahoo, que
    costuma trazer só ~4 anos; a SEC é a fonte primária e tem o histórico completo de 10-K. Lista
    vazia: ticker da B3, sem o Secret SEC_CONTACT_EMAIL no Streamlit Cloud, ou a SEC sem o dado —
    nesses casos a tela cai de volta no Yahoo, como antes (nunca trava, nunca inventa)."""
    if ticker.endswith(".SA"):
        return []
    email = (st.secrets.get("SEC_CONTACT_EMAIL") or "").strip() if hasattr(st, "secrets") else ""
    if not email or "@" not in email:
        return []
    import utils.fetch_guidance as fg

    cab = {"User-Agent": f"fintai/1.0 (contato: {email})", "Accept-Encoding": "gzip, deflate"}
    try:
        mapa = _tickers_sec_cache(cab)
        if not mapa:
            return []
        empresa = fg.cik_do_ticker(ticker, cab, mapa=mapa)
        if not empresa:
            return []
        fatos = fg._get_sec(f"{fg.SEC_DADOS}/api/xbrl/companyfacts/CIK{empresa[0]}.json", cab).json()
        return fg.lpa_anual_sec(fatos)
    except Exception:
        return []


@st.cache_data(ttl=60, show_spinner=False)   # mesmo ritmo de baixar() e do fragment: cotação mais dinâmica
def pacote(ticker: str, versao: str = "") -> dict:
    """Tudo o que a tela de um ticker precisa, calculado uma única vez."""
    d = baixar(ticker)
    sec_anual = lpa_anual_eua(ticker)
    if sec_anual:
        # troca a série do Yahoo pela da SEC: todo mundo que usa d["lpa_anual"] (Graham, médias,
        # Faixa do Conservador, "cresceu de X para Y") passa a usar o dado verificado, sem misturar
        d = {**d, "lpa_anual": pd.Series({pd.to_datetime(x["fim"], format="%d/%m/%Y"): x["lpa"] for x in sec_anual}),
            "lpa_anual_fonte": "SEC 10-K, lucro por ação diluído (GAAP)"}
    hist = d["hist"]
    proventos = hist["Dividends"][hist["Dividends"] > 0] if "Dividends" in hist else None
    r = calcular(hist, proventos)
    comps, padrao = comparadores(ticker, r.data_ultimo, d["info"])
    return montar(ticker, d, r, comps, padrao)


# ------------------------------------------------------------ fila pública de tickers novos
ARQ_GUIDANCE_TICKERS = Path(__file__).parent / "utils" / "guidance_tickers.json"
ARQ_NAO_VALIDADO = Path(__file__).parent / "utils" / "queue_nao_validado.json"


@st.cache_data(ttl=900, show_spinner=False)   # mesmo ritmo do robô: recarrega a cada deploy/restart
def _estado_fila() -> tuple[set[str], set[str]]:
    """(tickers já cadastrados, tickers já tentados e não validados) — os dois arquivos são gravados
    só pelo robô via GitHub Actions; o app só lê."""
    def ler(caminho, padrao):
        try:
            return json.loads(caminho.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return padrao
    registrados = {t.upper() for t in ler(ARQ_GUIDANCE_TICKERS, [])}
    nao_validados = {t.upper() for t in ler(ARQ_NAO_VALIDADO, {})}
    return registrados, nao_validados


@st.cache_data(ttl=3600, show_spinner=False)   # 1 pedido por ticker novo por hora (por instância do app)
def _pedir_na_fila(ticker_curto: str) -> bool:
    import utils.fila_github as fila
    token = st.secrets.get("GITHUB_QUEUE_TOKEN") if hasattr(st, "secrets") else None
    return fila.pedir_ticker(ticker_curto, token)


def aviso_guidance_pendente(ticker: str) -> None:
    """Ticker com preço válido do Yahoo, mas ainda fora de guidance_tickers.json e de
    queue_nao_validado.json: mostra o aviso e registra o pedido na fila (Issues do GitHub) — uma
    vez só por ticker por sessão, e no máximo uma chamada à API por hora por instância do app."""
    curto_t = curto(ticker)
    registrados, nao_validados = _estado_fila()
    if curto_t in registrados or curto_t in nao_validados:
        return
    st.info(f"🕒 Guidance de {curto_t} ainda não verificado — vamos checar hoje à noite.", icon="🕒")
    pedidos = st.session_state.setdefault("_fila_pedidos", set())
    if curto_t not in pedidos:
        pedidos.add(curto_t)
        _pedir_na_fila(curto_t)


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
@st.fragment(run_every=60)   # atualiza a cotação sozinho a cada 60s, sem recarregar a página (mantém a rolagem)
def painel(ticker: str):
    with st.spinner(f"Buscando {ticker}..."):
        dados = pacote(ticker, VERSAO_CALCULO)
    barra_de_acoes(ticker)
    aviso_guidance_pendente(ticker)       # ticker novo (fora da lista do robô): avisa e entra na fila
    tela_detalhe(data={"dados": dados}, key=f"tela_{ticker}")


def resumo(tickers: list[str]):
    if not tickers:
        return
    cotacoes = get_cotacoes(tickers)      # preço rápido, em lote; cada ticker ainda confere no pacote()

    def calcular_linha(t: str) -> dict:
        try:
            p = pacote(t, VERSAO_CALCULO)
            z = zonas(p["min52"], p["max52"])
            cot = cotacoes.get(t, {})
            preco = cot["preco"] if not cot.get("erro", True) and cot.get("preco") is not None else p["preco"]
            dy = p["dividendo"] / preco * 100 if p["dividendo"] is not None and preco else None
            return {
                "Ticker": t, "Preço": preco, "Estado": p["decisao"]["codigo"], "Zona": p["decisao"]["zona"],
                "Oportunidade até": z.oportunidade_ate, "Cara acima de": z.cara_acima,
                "P/L": p["pl"], "DY %": dy, "Ret. 1a %": p["retorno"]["total"][0],
                "Ret. 3a %": p["retorno"]["total"][1], "Ret. 5a %": p["retorno"]["total"][2],
            }
        except Exception as e:
            return {"Ticker": t, "Estado": f"Erro: {e}"}

    # cada pacote(ticker) é I/O (Yahoo Finance) e independente dos outros: paralelo em vez de 1 por vez
    with st.spinner("Calculando o comparativo..."):
        with cf.ThreadPoolExecutor(max_workers=min(8, len(tickers))) as executor:
            linhas = list(executor.map(calcular_linha, tickers))
    df = pd.DataFrame(linhas).set_index("Ticker")
    st.dataframe(df.style.format(precision=2, na_rep="—"), width="stretch")


# ------------------------------------------------------------ página
st.markdown(CSS, unsafe_allow_html=True)
_logo_b64 = base64.b64encode(LOGO.read_bytes()).decode() if LOGO.exists() else ""
st.markdown(
    f"<div class='marca'>{f'<img src=\"data:image/png;base64,{_logo_b64}\" alt=\"FINTAI\">' if _logo_b64 else ''}"
    "<span>Ações do Brasil e dos EUA em um só painel</span></div>",
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
if len(tickers) > MAX_TICKERS:
    st.warning(f"Limite de {MAX_TICKERS} ações para manter rápido")
    tickers = tickers[:MAX_TICKERS]

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
