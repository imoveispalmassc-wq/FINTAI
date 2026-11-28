"""FINTAI: análise de ações do Brasil e dos EUA.

Rodar:  streamlit run app.py
"""
from __future__ import annotations

import base64
import concurrent.futures as cf
import datetime as dt
import hashlib
import importlib
import json
import subprocess
import time
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import streamlit as st
import yfinance as yf

import calculos
import components.lpa_chart
import components.retorno_chart
import tela.dados
import utils.benchmarks
import utils.dados_fixos
import utils.fetch_guidance
import utils.formato
import utils.lynch
import utils.override
import utils.percentile
import utils.seo
import utils.signals
import utils.simons

# O Streamlit Cloud pode manter versões antigas dos módulos na memória depois de uma
# atualização; recarregar (na ordem das dependências) mantém tudo na mesma versão.
# utils.fetch_guidance vem ANTES de utils.dados_fixos: ele importa várias funções de lá
# (from utils.fetch_guidance import ...) e, sem recarregar fetch_guidance primeiro, o
# dados_fixos recarregado ia importar de uma versão antiga do módulo ainda em memória -
# ImportError pra qualquer nome novo adicionado lá depois do último reload (issue #33).
for _modulo in (utils.formato, utils.percentile, utils.signals, utils.benchmarks, utils.lynch, utils.override,
                utils.simons, utils.fetch_guidance, utils.dados_fixos, components.lpa_chart,
                components.retorno_chart, calculos, tela.dados):
    importlib.reload(_modulo)

from calculos import calcular, normalizar_ticker, retorno_periodo
from tela.dados import montar
from utils.benchmarks import retornos_brasil
from utils.percentile import zonas

LOGO = Path(__file__).parent / "assets" / "logo.png"
st.set_page_config(page_title="FINTAI", page_icon=str(LOGO), layout="wide")
# Preview do link no WhatsApp/Telegram/Twitter: o st.set_page_config acima só muda o <title> depois
# que o JavaScript do Streamlit termina de carregar - o WhatsApp nunca executa JavaScript, então lê
# sempre o HTML estático original (<title>Streamlit</title>, sem nenhuma meta tag). Ver utils/seo.py
# para a explicação completa e a limitação (ajuste no arquivo estático do pacote streamlit, não uma
# configuração oficial do Streamlit; não foi possível confirmar o preview real do WhatsApp daqui).
utils.seo.aplicar_meta_og()

def _versao_deploy() -> str:
    """Branch e commit curto da implantação em execução, só para diagnóstico (comparar 2
    implantações do MESMO repositório que podem divergir por estarem em branches/commits
    diferentes - ver CLAUDE.md, 'segunda conta' da Lista de Quinta). Nunca derruba o app: sem
    git/.git disponível no ambiente de deploy (alguns provedores não copiam o histórico), devolve
    'desconhecido' em vez de erro."""
    try:
        raiz = Path(__file__).parent
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=raiz, capture_output=True,
                             text=True, timeout=3).stdout.strip()
        branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=raiz,
                                capture_output=True, text=True, timeout=3).stdout.strip()
        return f"{branch}@{sha}" if sha else "desconhecido"
    except Exception:  # noqa: BLE001
        return "desconhecido"


VERSAO_DEPLOY = _versao_deploy()
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
/* puxa o bloco "Lucro por ação - Evolução" um pouco pra cima, encostando mais perto do card
   "Lucro por ação" logo acima (fim do 1º componente da tela) - pedido do usuário, 27/11/2026. */
.st-key-lpa_evolucao_bloco { margin-top: -1.75rem; }
</style>
"""

# Tela de detalhes: dividida em 2 componentes (27/11/2026) pra encaixar o gráfico nativo de LPA
# (components/lpa_chart.py, st.bar_chart) logo abaixo do card "Lucro por ação", sem ficar só no
# fim da tela - um widget nativo do Streamlit não pode ficar embutido no meio do HTML/JS de UM
# componente só. O corte foi feito na costura que já existia entre "bloco de cada modo" e
# "fundamentos" (tela/detalhe.html) - nunca no meio de um card. tela_detalhe = cabeçalho fixo +
# Visão geral + Faixa/Tendência/Mínimo-máximo/bloco de cada modo (cabeçalho e scroll ficam 100%
# aqui, intocados); tela_detalhe_fundo = Fundamentos/Indicadores/Retorno acumulado (tela/
# detalhe_fundo.html/.js, novo). As 2 metades compartilham o mesmo CSS (detalhe.css).
_PASTA = Path(__file__).parent / "tela"
_CSS_DETALHE = (_PASTA / "detalhe.css").read_text(encoding="utf-8")
tela_detalhe = st.components.v2.component(
    "fintai_detalhe",
    html=(_PASTA / "detalhe.html").read_text(encoding="utf-8"),
    css=_CSS_DETALHE,
    js=(_PASTA / "detalhe.js").read_text(encoding="utf-8"),
)
tela_detalhe_fundo = st.components.v2.component(
    "fintai_detalhe_fundo",
    html=(_PASTA / "detalhe_fundo.html").read_text(encoding="utf-8"),
    css=_CSS_DETALHE,
    js=(_PASTA / "detalhe_fundo.js").read_text(encoding="utf-8"),
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


def comparadores(ticker: str, fim: pd.Timestamp, info: dict) -> tuple[dict, str, dict]:
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
    # Issue #47 (item 16): nunca misturar moeda no gráfico de retorno. Ticker da B3 só mostra
    # comparadores em R$ (Ibovespa, IPCA, Poupança); ticker dos EUA só em US$ (S&P 500, Nasdaq).
    # Sem conversão BCB/Fed implementada ainda, um índice em moeda diferente simplesmente não
    # entra (nunca mistura sem converter) - ver CLAUDE.md, item 16, para a limitação conhecida.
    # CDI/Selic (BR) saem do grupo de índices: vão em "Renda fixa", separado (item 16), já que são
    # outro tipo de investimento, não um índice de bolsa.
    if ticker.endswith(".SA"):
        ordem = ["ibov", "ipca", "poupanca"]
    else:
        bolsa = f"{info.get('exchange', '')} {info.get('fullExchangeName', '')}".lower()
        ordem = ["nasdaq", "sp500"] if ("nasdaq" in bolsa or info.get("exchange") in ("NMS", "NGM", "NCM")) else ["sp500", "nasdaq"]
    padrao = ordem[0]
    # Renda fixa (BR): CDI e Selic, com a etiqueta de "outro tipo de investimento" na tela. Para
    # tickers dos EUA não há hoje fonte equivalente (Fed Funds/T-Bill) integrada - fica vazio,
    # nunca inventado (ver limitação no CLAUDE.md).
    renda_fixa = {k: todos[k] for k in ("cdi", "selic")} if ticker.endswith(".SA") else {}
    return {k: todos[k] for k in ordem}, padrao, renda_fixa


@st.cache_data(ttl=86400, show_spinner=False)   # lista de ~10 mil tickers da SEC: a mesma pra
def _tickers_sec_cache(cab: dict) -> dict:      # qualquer ticker, baixa 1x por dia (não a cada ticker digitado)
    import utils.fetch_guidance as fg
    try:
        return fg.tickers_sec(cab)
    except Exception:
        return {}


@st.cache_data(ttl=86400, show_spinner=False)   # 10-K/10-Q não mudam mais que 1x por trimestre
def lpa_anual_eua(ticker: str) -> tuple[list[dict], str]:
    """Histórico anual de LPA diluído (GAAP), direto da SEC (10-K) — qualquer ticker dos EUA, sem
    precisar estar cadastrado em utils/guidance_tickers.json. Substitui o income_stmt do Yahoo, que
    costuma trazer só ~4 anos; a SEC é a fonte primária e tem o histórico completo de 10-K. Lista
    vazia: ticker da B3, sem o Secret SEC_CONTACT_EMAIL no Streamlit Cloud, ou a SEC sem o dado —
    nesses casos a tela cai de volta no Yahoo, como antes (nunca trava, nunca inventa). O segundo
    valor é o motivo (diagnóstico), pra mostrar na tela por que caiu no Yahoo em vez da SEC."""
    if ticker.endswith(".SA"):
        return [], "ticker da B3"
    email = (st.secrets.get("SEC_CONTACT_EMAIL") or "").strip() if hasattr(st, "secrets") else ""
    if not email or "@" not in email:
        return [], "SEC sem e-mail configurado (Secret SEC_CONTACT_EMAIL do app no Streamlit Cloud)"
    import utils.fetch_guidance as fg

    cab = {"User-Agent": f"fintai/1.0 (contato: {email})", "Accept-Encoding": "gzip, deflate"}
    try:
        mapa = _tickers_sec_cache(cab)
        if not mapa:
            return [], "SEC sem a lista de tickers (tente de novo mais tarde)"
        empresa = fg.cik_do_ticker(ticker, cab, mapa=mapa)
        if not empresa:
            return [], "SEC não encontrou esse ticker"
        fatos = fg._get_sec(f"{fg.SEC_DADOS}/api/xbrl/companyfacts/CIK{empresa[0]}.json", cab).json()
        anos = fg.converter_lpa_anual_para_usd(fg.lpa_anual_sec(fatos))
        return anos, ("SEC OK" if anos else "SEC sem o dado de lucro por ação pra esse ticker")
    except Exception as e:
        return [], f"SEC falhou ({e})"


@st.cache_data(ttl=86400, show_spinner=False)   # earnings release não muda mais que 1x por trimestre
def outlook_trimestral_eua(ticker: str, max_docs: int = 3) -> dict | None:
    """Guidance TRIMESTRAL (receita, margem, LPA do próximo trimestre) na hora, direto da SEC —
    qualquer ticker dos EUA, sem depender do robô noturno nem de estar cadastrado em
    guidance_tickers.json/queue_nao_validado.json (esses continuam existindo para o robô, que tem
    mais tempo e API do Claude para o guidance ANUAL). Essa busca é só regex (mesma função do robô,
    extrair_outlook_trimestral_eua), sem API do Claude e sem as 4 travas - não precisa, é informativo
    e nunca inventa: sem achar um formato reconhecido no documento, devolve None e o card não
    aparece. None também sem o Secret SEC_CONTACT_EMAIL, ticker não encontrado ou B3."""
    if ticker.endswith(".SA"):
        return None
    email = (st.secrets.get("SEC_CONTACT_EMAIL") or "").strip() if hasattr(st, "secrets") else ""
    if not email or "@" not in email:
        return None
    import utils.fetch_guidance as fg

    cab = {"User-Agent": f"fintai/1.0 (contato: {email})", "Accept-Encoding": "gzip, deflate"}
    try:
        mapa = _tickers_sec_cache(cab)
        if not mapa:
            return None
        empresa = fg.cik_do_ticker(ticker, cab, mapa=mapa)
        if not empresa:
            return None
        cik, nome = empresa
        for doc in fg.documentos_sec(cik, cab)[:max_docs]:
            anexo = fg.anexo_sec(doc, cab)
            if not anexo:
                continue
            link, texto = anexo
            dados = fg.extrair_outlook_trimestral_eua(texto)
            if dados and dados.get("moeda") == "EUR":
                data_doc = fg._data(doc["data"])
                taxas = fg.taxa_cambio_historica_eur_usd([data_doc]) if data_doc else {}
                if data_doc not in taxas:
                    continue   # nunca mostra valor em euro como se fosse dólar
                taxa, data_taxa = taxas[data_doc]
                dados = fg.converter_outlook_para_usd(dados, taxa, data_taxa)
            if dados:
                return {**dados, "fonte": f"{nome}, Form {doc['form']} Exhibit 99.1 de {fg._data_br(doc['data'])} (SEC)",
                        "data": fg._data_br(doc["data"]), "url": link,
                        "atualizado_em": dt.datetime.now(fg.BRASILIA).strftime("%d/%m %H:%M"),
                        "proximo_anuncio": fg.proximo_anuncio_eua(ticker)}
        return None
    except Exception:
        return None


@st.cache_data(ttl=86400, show_spinner=False)   # ações/lucro/dividendo só mudam com balanço novo
def dados_fixos_fonte(ticker: str) -> dict:
    """Fundamentos fixos (Issue #29, utils/dados_fixos.py): ações, lucro e dividendo de 12 meses,
    SÓ da fonte oficial (release/ITR/DFP na CVM ou SEC EDGAR - nunca Yahoo). Lista sob demanda:
    ticker novo busca 1x e grava em utils/dados_fixos.json; ticker já salvo só é lido daqui -
    cotacao=None pra essa função nunca recalcular com o preço do dia (isso é feito em
    tela.dados.montar, com a cotação já buscada pela tela). ttl de 1 dia: evita bater na CVM/SEC
    de novo a cada refresh de página (o próprio dados_fixos.json já cacheia entre reinícios)."""
    try:
        return utils.dados_fixos.obter(ticker, dt.date.today(), None)
    except Exception as e:  # noqa: BLE001 - nunca derruba a tela por falha na fonte oficial
        return {"status": "nao_encontrado", "mensagem": utils.dados_fixos.MENSAGEM_NAO_ENCONTRADO, "motivo": str(e)}


@st.cache_data(ttl=60, show_spinner=False)   # mesmo ritmo de baixar() e do fragment: cotação mais dinâmica
def pacote(ticker: str, versao: str = "") -> dict:
    """Tudo o que a tela de um ticker precisa, calculado uma única vez."""
    d = baixar(ticker)
    sec_anual, sec_motivo = lpa_anual_eua(ticker)
    if sec_anual:
        # troca a série do Yahoo pela da SEC: todo mundo que usa d["lpa_anual"] (Graham, médias,
        # Faixa do Conservador, "cresceu de X para Y") passa a usar o dado verificado, sem misturar
        is_20f = any(x.get("form", "").startswith("20-F") for x in sec_anual)
        convertido = any(x.get("taxa_cambio") for x in sec_anual)
        fonte = ("SEC 20-F, lucro por ação diluído (GAAP)" + (" - convertido de euro pelo câmbio da data do anúncio de cada ano, Yahoo Finance" if convertido else ""))\
            if is_20f else "SEC 10-K, lucro por ação diluído (GAAP)"
        d = {**d, "lpa_anual": pd.Series({pd.to_datetime(x["fim"], format="%d/%m/%Y"): x["lpa"] for x in sec_anual}),
            "lpa_anual_fonte": fonte}
    elif not ticker.endswith(".SA"):
        # SEC não foi usada pra esse ticker dos EUA: mostra o motivo na tela, pra diagnosticar sem
        # precisar olhar o código (ex.: Secret SEC_CONTACT_EMAIL do app ainda não configurado)
        d = {**d, "lpa_anual_sec_motivo": sec_motivo}
    hist = d["hist"]
    proventos = hist["Dividends"][hist["Dividends"] > 0] if "Dividends" in hist else None
    r = calcular(hist, proventos)
    comps, padrao, renda_fixa = comparadores(ticker, r.data_ultimo, d["info"])
    fixos = dados_fixos_fonte(ticker)
    dados = montar(ticker, d, r, comps, padrao, dados_fixos=fixos, renda_fixa=renda_fixa)
    if not dados.get("outlookTrimestral"):
        # o robô ainda não gravou (ticker novo, ou travado no anual e ainda não reprocessado):
        # busca na hora, pra não depender do próximo ciclo do workflow noturno
        ao_vivo = outlook_trimestral_eua(ticker)
        if ao_vivo:
            dados = {**dados, "outlookTrimestral": {
                "periodo": ao_vivo.get("periodo"), "receitaMin": ao_vivo.get("receita_min"), "receitaMax": ao_vivo.get("receita_max"),
                "margemBruta": ao_vivo.get("margem_bruta"), "lpaMin": ao_vivo.get("lpa_min"), "lpaMax": ao_vivo.get("lpa_max"),
                "fonte": ao_vivo.get("fonte") or "", "data": ao_vivo.get("data") or "", "url": ao_vivo.get("url") or "",
                "moedaOriginal": ao_vivo.get("moeda_original") or "", "taxaCambio": ao_vivo.get("taxa_cambio"),
                "taxaCambioData": ao_vivo.get("taxa_cambio_data") or "",
                "atualizacao": tela.dados.atualizacao_contabil(ao_vivo),
                "proximoAnuncio": tela.dados.proximo_anuncio_info(d["info"]) or ao_vivo.get("proximo_anuncio") or ""}}
    return dados


# ------------------------------------------------------------ fila pública de tickers novos
ARQ_GUIDANCE_TICKERS = Path(__file__).parent / "utils" / "guidance_tickers.json"
ARQ_NAO_VALIDADO = Path(__file__).parent / "utils" / "queue_nao_validado.json"
ARQ_OUTLOOK_TRI = Path(__file__).parent / "utils" / "guidance_trimestral_eua.json"


@st.cache_data(ttl=900, show_spinner=False)   # mesmo ritmo do robô: recarrega a cada deploy/restart
def _estado_fila() -> tuple[set[str], set[str], set[str]]:
    """(tickers já cadastrados, tickers já tentados e não validados, tickers com guidance TRIMESTRAL
    verificado) — os três arquivos são gravados só pelo robô via GitHub Actions; o app só lê."""
    def ler(caminho, padrao):
        try:
            return json.loads(caminho.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return padrao
    registrados = {t.upper() for t in ler(ARQ_GUIDANCE_TICKERS, [])}
    nao_validados = {t.upper() for t in ler(ARQ_NAO_VALIDADO, {})}
    com_trimestral = {t.upper() for t in ler(ARQ_OUTLOOK_TRI, {})}
    return registrados, nao_validados, com_trimestral


@st.cache_data(ttl=3600, show_spinner=False)   # 1 pedido por ticker novo por hora (por instância do app)
def _pedir_na_fila(ticker_curto: str) -> bool:
    import utils.fila_github as fila
    token = st.secrets.get("GITHUB_QUEUE_TOKEN") if hasattr(st, "secrets") else None
    return fila.pedir_ticker(ticker_curto, token)


def aviso_guidance_pendente(ticker: str) -> str | None:
    """Ticker com preço válido do Yahoo, mas ainda fora de guidance_tickers.json e de
    queue_nao_validado.json: registra o pedido na fila (Issues do GitHub) — uma vez só por ticker
    por sessão, e no máximo uma chamada à API por hora por instância do app — e devolve o texto do
    aviso (do guidance ANUAL), para a tela mostrar perto do card "Lucro por ação". Ticker já travado
    (sem guidance anual) mas com guidance TRIMESTRAL verificado: devolve uma nota explicando (não é
    um dado pendente, é a empresa que só dá guidance trimestral). Nada a avisar: None."""
    curto_t = curto(ticker)
    registrados, nao_validados, com_trimestral = _estado_fila()
    if curto_t in registrados:
        return None
    if curto_t in nao_validados:
        if curto_t in com_trimestral:
            return (f"Guidance ANUAL de {curto_t} não encontrado nos comunicados oficiais — a empresa só dá "
                    "guidance trimestral. Guidance trimestral verificado abaixo.")
        return None
    pedidos = st.session_state.setdefault("_fila_pedidos", set())
    if curto_t not in pedidos:
        pedidos.add(curto_t)
        _pedir_na_fila(curto_t)
    return f"Guidance ANUAL de {curto_t} ainda não verificado — vamos checar hoje à noite."


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


def _pontos_lpa_grafico(dados: dict) -> list[dict]:
    """Pontos pro gráfico nativo "Lucro por ação - Evolução" (components/lpa_chart.py) - mesmos
    anos/guidance que o card de texto "Lucro por ação" (dentro de `tela_detalhe`) já mostra, sem
    recalcular nada: só lê o que `tela.dados.montar()` já colocou em `dados`. Vale pra qualquer
    ticker, B3 ou EUA - nenhuma lógica específica de um ativo aqui."""
    lpa_anos = dados.get("lpaAnos") or []
    pontos = [{"ano": str(a["ano"]), "valor": a["lpa"]} for a in lpa_anos if a.get("lpa") is not None]

    guia = dados.get("guidance")
    ano_proj = (guia or {}).get("periodo") or (str(int(lpa_anos[-1]["ano"]) + 1) if lpa_anos else None)
    lpa_ttm = dados.get("lpa")
    lpa_ini = (dados.get("guidanceInicial") or {}).get("lpa")
    # 2 barras SEPARADAS (nunca uma só empilhada) pra estimativa do início do ano x TTM já realizado.
    # Nome da barra autoexplicativo (27/11/2026, follow-up) - sem caption embaixo do gráfico, que o
    # usuário pediu pra tirar: o próprio rótulo já diz o que cada uma é.
    if ano_proj and lpa_ini is not None and lpa_ini > 0:
        pontos.append({"ano": f"{ano_proj} Inicial (Est. início ano)", "valor": lpa_ini})
    if ano_proj and lpa_ttm is not None:
        pontos.append({"ano": f"{ano_proj} Atual (TTM Realizado)", "valor": lpa_ttm})

    proj = ((dados.get("lynch") or {}).get("futuro") or {}).get("lpaEsteAno")
    if ano_proj and proj is not None:
        pontos.append({"ano": f"{ano_proj}E ({'Guidance' if guia else 'Projeção'})", "valor": proj})

    return pontos


_NOME_CURTO_COMPARADOR = {"S&P 500": "S&P", "S&P 500 (sem dividendos)": "S&P s/div",
                          "Ibovespa": "Ibov", "Poupança": "Poup."}


def _ret_fmt(v) -> str:
    """Mesma regra de casas decimais do `ret()` em tela/detalhe.js: 0 casas acima de 100%, 1 abaixo."""
    if v is None:
        return "—"
    return utils.formato.pct(v, 0 if abs(v) >= 100 else 1)


def _retorno_bloco(dados: dict, ticker: str) -> None:
    """Card "Retorno acumulado" - gráfico nativo (components/retorno_chart.py), MESMA regra do
    gráfico de LPA (27/11/2026): nenhuma barra desenhada com div/CSS. Saiu de dentro de
    `tela_detalhe_fundo` pelo mesmo motivo do gráfico de LPA - um widget nativo do Streamlit não
    pode ficar embutido no HTML/JS de um componente customizado. Período (1/3/5 anos) e
    reinvestir dividendos, antes botões client-side (instantâneos, sem round-trip), viram
    controles nativos do Streamlit - o `@st.fragment` de `painel()` escopa o rerun só a este
    bloco, sem perder a rolagem da página nem recarregar a tela inteira."""
    st.subheader("Retorno acumulado")
    retorno = dados.get("retorno") or {}
    periodos = retorno.get("periodos") or []
    total = retorno.get("total") or []
    preco = retorno.get("preco") or []
    idx = [i for i in range(len(periodos)) if i < len(total) and total[i] is not None]
    if not idx:
        st.caption("Histórico curto demais para calcular retornos.")
        return

    comparadores = dados.get("comparadores") or {}
    moeda = dados.get("moeda") or ""
    nome_ticker = dados.get("ticker") or ticker

    key_per, key_rein = f"retorno_per_{ticker}", f"retorno_reinveste_{ticker}"
    st.session_state.setdefault(key_rein, True)
    if key_per not in st.session_state or st.session_state[key_per] not in idx:
        st.session_state[key_per] = idx[0]
    col1, col2 = st.columns([3, 2])
    with col2:
        reinveste = st.toggle("Reinvestindo dividendos", key=key_rein)
    with col1:
        per = st.segmented_control("Período", options=idx, format_func=lambda i: periodos[i], key=key_per)
    if per is None:
        per = st.session_state[key_per]

    vals = total if reinveste else preco
    p_sel = periodos[per]
    dif_p = (total[per] - preco[per]) if (per < len(total) and per < len(preco)
                                          and total[per] is not None and preco[per] is not None) else None
    recebido = dados.get("dividendo") if per == 0 else dados.get("dividendos5Anos") if per == 2 else None
    if reinveste:
        if dif_p is None:
            texto = "Retorno com os dividendos reinvestidos em mais ações."
        elif dif_p < 1:
            texto = (f"Quase nenhuma diferença em {p_sel}. Reinvestir ou não muda "
                     f"{utils.formato.num(max(dif_p, 0), 1)} ponto no seu retorno.")
        else:
            abertura = "Grande diferença" if dif_p >= 10 else "Faz diferença"
            texto = (f"{abertura}. Em {p_sel}, reinvestir os dividendos faz seu retorno ir de "
                     f"{_ret_fmt(preco[per])} para {_ret_fmt(total[per])}, porque você compra mais "
                     f"ações com o dividendo.")
    else:
        texto = (f"Você recebeu {moeda} {utils.formato.num(recebido)} por ação em dividendos em "
                 f"{p_sel}, em dinheiro, e não recomprou." if recebido is not None and recebido > 0
                 else f"Você recebeu os dividendos de {p_sel} em dinheiro e não recomprou.")
        if dif_p is not None and dif_p >= 10:
            texto += f" Deixou de ganhar {utils.formato.num(dif_p, 1)} pontos do efeito bola de neve."
    st.caption(texto)

    v_sel = vals[per] if per < len(vals) else None
    linhas = [{"nome": nome_ticker, "valor": v_sel, "rotulo": _ret_fmt(v_sel)}]
    for o in comparadores.values():
        v = o.get("v") or []
        vv = v[per] if per < len(v) else None
        linhas.append({"nome": _NOME_CURTO_COMPARADOR.get(o.get("nome"), o.get("nome")),
                       "valor": vv, "rotulo": _ret_fmt(vv)})
    linhas[1:] = sorted(linhas[1:], key=lambda l: l["valor"] if l["valor"] is not None else float("inf"))
    components.retorno_chart.render_retorno_chart(linhas)

    def _tem_dado(chave):
        c = comparadores.get(chave)
        return bool(c and any(v is not None for v in c.get("v") or []))
    padrao = dados.get("comparadorPadrao")
    comp_chave = padrao if _tem_dado(padrao) else next((k for k in comparadores if _tem_dado(k)), None)
    comp = comparadores.get(comp_chave) if comp_chave else None
    with st.container(border=True):
        if v_sel is None:
            st.markdown(f"**Retorno acumulado: Dados indisponíveis em {p_sel}**")
        else:
            cab = f"**{nome_ticker}: {_ret_fmt(v_sel)} em {p_sel}**" + ("" if reinveste else " (só preço)")
            comp_v = (comp.get("v") or [None])[per] if comp and per < len(comp.get("v") or []) else None
            if comp is None or comp_v is None:
                st.markdown(f"{cab}  \n{comp.get('nome') if comp else '—'}: Dados indisponíveis")
            else:
                dif = v_sel - comp_v
                casas = 0 if abs(dif) >= 100 else 1
                sinal, lado = ("+", "acima") if dif >= 0 else ("-", "abaixo")
                st.markdown(f"{cab}  \n{comp.get('nome')}: {_ret_fmt(comp_v)} | Diferença: "
                            f"{sinal}{utils.formato.num(abs(dif), casas)} pontos {lado} "
                            f"{comp.get('artigo', '')}")
                with st.popover("O que são pontos percentuais?"):
                    st.caption(f"p.p. = pontos percentuais. É só a conta: {utils.formato.num(v_sel, 1)}% - "
                               f"{utils.formato.num(comp_v, 1)}% = {utils.formato.num(abs(dif), casas)} pontos. "
                               f"Não é {utils.formato.num(abs(dif), casas)}%.")

    renda_fixa = dados.get("rendaFixa") or {}
    linhas_rf = [o for o in renda_fixa.values()
                 if o.get("taxaAno") is not None or any(v is not None for v in (o.get("v") or []))]
    if linhas_rf:
        with st.container(border=True):
            st.markdown("**Renda fixa** *[Outro tipo de investimento]*")
            for o in linhas_rf:
                v = (o.get("v") or [None])[per] if per < len(o.get("v") or []) else None
                taxa = f" ({utils.formato.num(o['taxaAno'])}% a.a. hoje)" if o.get("taxaAno") is not None else ""
                valor_txt = _ret_fmt(v) if v is not None else "Dados indisponíveis"
                st.markdown(f"{o.get('nome')}{taxa}: **{valor_txt} em {p_sel}**")
            st.caption("CDI e Selic são renda fixa, não um índice de bolsa - ficam fora do gráfico "
                       "de retorno acima de propósito.")

    t3 = total[1] if len(total) > 1 else None
    t5 = total[2] if len(total) > 2 else None
    porque = ""
    if per == 2 and t3 is not None and t5 is not None and t3 > t5:
        queda = abs((1 + t5 / 100) / (1 + t3 / 100) - 1) * 100
        porque = (f"Por que 3 anos ({_ret_fmt(t3)}) rendeu mais que 5 anos ({_ret_fmt(t5)})? Porque "
                  f"entre 5 e 3 anos atrás a ação caiu {utils.formato.num(queda, 0)}%. O ganho veio "
                  f"todo nos últimos 3 anos. ")
    st.caption(f"{porque}Retorno passado não garante retorno futuro.")
    st.caption(f"Fonte: Yahoo Finance - Dados até {dados.get('data', '')}.")


# ------------------------------------------------------------ telas
@st.fragment(run_every=60)   # atualiza a cotação sozinho a cada 60s, sem recarregar a página (mantém a rolagem)
def painel(ticker: str):
    with st.spinner(f"Buscando {ticker}..."):
        dados = pacote(ticker, VERSAO_CALCULO)
    barra_de_acoes(ticker)
    aviso = aviso_guidance_pendente(ticker)   # ticker novo (fora da lista do robô): avisa e entra na fila
    if aviso:
        dados = {**dados, "avisoGuidanceAnual": aviso}
    tela_detalhe(data={"dados": dados}, key=f"tela_{ticker}")
    # Gráfico nativo de LPA (components/lpa_chart.py, st.bar_chart) colado logo abaixo do card
    # "Lucro por ação" (27/11/2026, a pedido do usuário) - entra exatamente na costura entre as 2
    # metades da tela (tela_detalhe/tela_detalhe_fundo, ver comentário onde elas são criadas acima).
    # Aparece nos 3 modos (Conservador/Crescimento/Quantitativo), não só Conservador: Python não
    # sabe qual aba está ativa (a troca é só client-side, dentro de tela_detalhe) - mesmo padrão já
    # aceito no projeto pro card de guidance trimestral, que também aparece nos 3 modos.
    pontos_lpa = _pontos_lpa_grafico(dados)
    if pontos_lpa:
        # container com key (.st-key-lpa_evolucao_bloco no CSS acima) pra puxar o bloco um pouco
        # pra cima, diminuindo o espaço vazio entre o card "Lucro por ação" (fim do 1º componente)
        # e este título - pedido do usuário, 27/11/2026.
        with st.container(key="lpa_evolucao_bloco"):
            st.subheader("Lucro por ação - Evolução")
            components.lpa_chart.render_lpa_chart(pontos_lpa)
    tela_detalhe_fundo(data={"dados": dados}, key=f"tela_fundo_{ticker}")
    # Retorno acumulado (components/retorno_chart.py) - saiu daqui de dentro pelo mesmo motivo do
    # gráfico de LPA (27/11/2026): mesma regra, gráfico nativo, nenhuma barra em div/CSS.
    _retorno_bloco(dados, ticker)


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

st.markdown(f"<div class='rodape'>Ferramenta de estudo, não é recomendação de investimento."
            f"<br><small>Versão: {VERSAO_DEPLOY}</small></div>", unsafe_allow_html=True)
