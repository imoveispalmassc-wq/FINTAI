"""Monta, a partir dos dados do Yahoo Finance, o pacote único que a tela de detalhes lê.

Fonte única de verdade: cada indicador é calculado uma vez aqui e todas as seções da tela
usam o mesmo valor. O que faltar vai como None e a tela mostra "Dados indisponíveis".
"""
from __future__ import annotations

import json
from pathlib import Path

import math

import pandas as pd

from calculos import (Resultado, crescimento_lpa, dy_atual_e_medio, lpa_contabil_ttm, media_no_periodo, pl_medio_12m, pl_medio_contabil,
                      graham_duas_versoes, pl_medio_longo, preco_justo_graham, preco_teto_bazin,
                      teto_valuation_conservador)
from utils.lynch import crescimento_anual, peg, preco_lynch, regra_prejuizo, veredito
from utils.override import guidance as guidance_oficial
from utils.override import guidance_inicial
from utils.percentile import percentil_na_faixa, zonas
from utils.signals import (backtest_percentil, decidir_estado, decidir_estado_conservador,
                           fundamento_quebrou, selo_backtest)
from utils.simons import SELO as SELO_SIMONS
from utils.simons import JANELA, classificar, historico, leitura, melhor_linha, queda_desde_topo, timing

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
        "10d": _serie(h.tail(11), "dia", "em 10 dias", soPreco=True),
        "hoje": _serie(intraday.get("hoje"), "hora", "no dia", base=anterior),
        "1s": _serie(intraday.get("1s"), "dia", "em 7 dias"),
        "1m": _serie(intraday.get("1m"), "dia", "em 30 dias"),
        "1a": _serie(um_ano, "mes", "em 12 meses", casas=1, soPreco=True),
        "5a": _serie(cinco, "ano", "em 5 anos", base=cinco_d["Close"].iloc[0]),
        "max": _serie(tudo, "ano", "em todo o histórico"),
    }


def ultimo_balanco(lpa_tri) -> dict | None:
    """Data do último balanço divulgado (datas de resultado do Yahoo com lucro informado)."""
    if lpa_tri is None or not len(lpa_tri.dropna()):
        return None
    return {"data": f"{_sem_fuso(lpa_tri.dropna()).index.max():%d/%m/%Y}"}


ARQ_CONTABIL_SEC = Path(__file__).resolve().parent.parent / "utils" / "contabil_sec.json"
ARQ_OUTLOOK_TRI = Path(__file__).resolve().parent.parent / "utils" / "guidance_trimestral_eua.json"


def proximo_anuncio_info(info: dict) -> str | None:
    """Próxima data de divulgação de resultados (Yahoo Finance), a partir do "info" que o app já
    busca pra qualquer ticker (campo earningsTimestamp/earningsTimestampStart, em epoch UTC) - sem
    nenhuma chamada extra de rede, por isso mais confiável do que buscar à parte (ex.: calendário
    do yfinance, que pode falhar sozinho por instabilidade da própria Yahoo). None quando o Yahoo
    não tiver esse campo pro ticker (nem toda empresa anuncia a data com antecedência)."""
    import datetime as dt

    ts = info.get("earningsTimestampStart") or info.get("earningsTimestamp")
    if not ts:
        return None
    try:
        return f"{dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc):%d/%m/%Y}"
    except (TypeError, ValueError, OSError):
        return None


def _com_proximo_anuncio(ot: dict | None, info: dict) -> dict | None:
    """Preenche/atualiza "proximoAnuncio" no outlook trimestral com o do "info" (sem rede extra,
    ver proximo_anuncio_info), que é mais confiável do que o gravado pelo robô ou buscado ao vivo
    (ambos dependem de uma chamada à parte que pode falhar). Sem nada no "info", mantém o que já
    veio (robô/ao vivo) como alternativa. ot=None (sem guidance trimestral achado) não muda nada."""
    if ot is None:
        return None
    return {**ot, "proximoAnuncio": proximo_anuncio_info(info) or ot.get("proximoAnuncio") or ""}


def outlook_trimestral_eua(ticker: str) -> dict | None:
    """Guidance TRIMESTRAL (receita, margem, LPA do próximo trimestre) gravado pelo robô, direto do
    earnings release na SEC - só informativo (não participa do P/L nem do selo GUIDANCE OFICIAL,
    que são do guidance ANUAL). None pra B3 ou quando o robô não achou nada pro ticker."""
    if ticker.endswith(".SA"):
        return None
    c = _ler(ARQ_OUTLOOK_TRI).get(ticker.upper())
    if not c:
        return None
    return {"periodo": c.get("periodo"), "receitaMin": _n(c.get("receita_min"), 2), "receitaMax": _n(c.get("receita_max"), 2),
            "margemBruta": _n(c.get("margem_bruta"), 2), "lpaMin": _n(c.get("lpa_min"), 4), "lpaMax": _n(c.get("lpa_max"), 4),
            "fonte": c.get("fonte") or "", "data": c.get("data") or "", "url": c.get("url") or "",
            "moedaOriginal": c.get("moeda_original") or "", "taxaCambio": _n(c.get("taxa_cambio"), 4),
            "taxaCambioData": c.get("taxa_cambio_data") or "", "atualizacao": atualizacao_contabil(c),
            "proximoAnuncio": c.get("proximo_anuncio") or ""}


ARQ_CONTABIL_BR = Path(__file__).resolve().parent.parent / "utils" / "contabil_br.json"
ARQ_CONTABIL_BR_CFG = Path(__file__).resolve().parent.parent / "utils" / "contabil_br_config.json"


def _ler(arq: Path) -> dict:
    try:
        d = json.loads(arq.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _contabil_b3(curto: str, lpa_yahoo: float | None, tabela_br: dict | None) -> tuple[float | None, str, dict | None]:
    """B3: release de resultados da empresa (robô, CVM) para os tickers configurados; senão Yahoo."""
    if curto not in _ler(ARQ_CONTABIL_BR_CFG):
        return lpa_yahoo, "Yahoo Finance", None
    c = (tabela_br if tabela_br is not None else _ler(ARQ_CONTABIL_BR)).get(curto)
    if not c or c.get("status") != "ok" or c.get("lpa_12m") is None:
        return lpa_yahoo, "Yahoo - pendente (release de resultados ainda não lido)", c
    return float(c["lpa_12m"]), c.get("fonte") or "Divulgação de Resultados", c


def atualizacao_contabil(c: dict | None, agora=None) -> dict | None:
    """Indicador de atualização do contábil gravado pelo robô ("17/11 18:32", Brasília).

    Devolve o texto e a hora em ISO (com o ano) para a tela calcular a idade e a cor da bolinha."""
    import datetime as dt

    if not c or not c.get("atualizado_em"):
        return None
    brasilia = dt.timezone(dt.timedelta(hours=-3))
    agora = agora or dt.datetime.now(brasilia)
    try:
        quando = dt.datetime.strptime(f"{c['atualizado_em']}/{agora.year}", "%d/%m %H:%M/%Y").replace(tzinfo=brasilia)
    except ValueError:
        return None
    if quando > agora + dt.timedelta(days=1):           # gravado em dezembro, lido em janeiro
        quando = quando.replace(year=agora.year - 1)
    return {"em": c["atualizado_em"], "iso": quando.isoformat(),
            "tri": c.get("trimestre_ref"), "triData": c.get("trimestre_data")}


def contabil_12m(ticker: str | None, lpa_yahoo: float | None, tabela: dict | None = None,
                 tabela_br: dict | None = None) -> tuple[float | None, str, dict | None]:
    """LPA contábil de 12 meses: SEC (robô, soma dos 4 últimos trimestres de LPA diluído) se estiver completa;
    senão o Yahoo, com o motivo. Devolve (lpa, fonte, detalhe da SEC)."""
    if tabela is None:
        try:
            tabela = json.loads(ARQ_CONTABIL_SEC.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            tabela = {}
    if not ticker:
        return lpa_yahoo, "Yahoo Finance", None
    if ticker.upper().endswith(".SA"):
        return _contabil_b3(ticker.upper()[:-3], lpa_yahoo, tabela_br)
    c = tabela.get(ticker.upper())
    if not c:
        return lpa_yahoo, "Yahoo - SEC ainda não lida pelo robô", None
    if c.get("status") != "ok" or c.get("lpa_12m") is None:
        return lpa_yahoo, "Yahoo - SEC incompleto", c
    return float(c["lpa_12m"]), c.get("fonte") or "SEC 10-Q/10-K, lucro por ação diluído (GAAP)", c


def fundamentos(d: dict, r: Resultado, ticker: str | None = None) -> dict:
    """Indicadores fundamentalistas, calculados uma única vez."""
    info, hist, lpa_tri = d["info"], _sem_fuso(d["hist"]), d["lpa_tri"]
    preco, fim = r.preco_atual, r.data_ultimo
    lpa, lpa_fonte, lpa_sec = contabil_12m(ticker, info.get("trailingEps") or info.get("epsTrailingTwelveMonths"))
    pl = preco / lpa if lpa and lpa > 0 else None       # sempre preço ÷ LPA, para as contas baterem
    splits = hist["Stock Splits"] if "Stock Splits" in hist else None
    pl_medio, metodo = pl_medio_12m(r.fechamentos_1a, lpa_tri, lpa, splits)
    preco_medio = float(r.fechamentos_1a.mean()) if len(r.fechamentos_1a) else None
    media_desde, media_meses = None, None
    if metodo == "simplificado":
        # série trimestral em outra base: tenta o lucro contábil de cada balanço (demonstrativos do Yahoo)
        acoes_ = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding")
        tem_split = splits is not None and (splits[splits.index > hist.index[-1] - pd.DateOffset(years=2)] != 0).any()
        if not tem_split:
            try:
                ttm = lpa_contabil_ttm(d["lucro_tri"], d["lpa_anual"], acoes_, lpa,
                                       lpa_tri.index if lpa_tri is not None else None)
                pc = pl_medio_contabil(r.fechamentos_1a, ttm)
            except Exception:
                pc = None
            if pc:
                pl_medio, metodo, preco_medio = pc["pl"], "contabil", pc["preco_medio"]
                media_desde, media_meses = f"{pc['desde']:%d/%m/%Y}", round(pc["meses"], 1)
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

    balanco = ultimo_balanco(lpa_tri)
    # receita de 12 meses: hoje (Yahoo), previsão do ano (consenso) e média no último ano (cada balanço)
    receita = info.get("totalRevenue")
    receita_media = None
    try:
        rec_ttm = lpa_contabil_ttm(d.get("receita_tri"), d.get("receita_anual"), 1.0, receita,
                                   lpa_tri.index if lpa_tri is not None else None)
        receita_media = media_no_periodo(r.fechamentos_1a, rec_ttm)
    except Exception:
        pass
    er = d.get("est_receita")
    receita_prev, analistas_rec = None, None
    if er is not None and not getattr(er, "empty", True) and "0y" in er.index:
        receita_prev = _n(er.loc["0y", "avg"]) if "avg" in er.columns else None
        analistas_rec = _n(er.loc["0y", "numberOfAnalysts"], 0) if "numberOfAnalysts" in er.columns else None
    divida, caixa, ebitda = info.get("totalDebt"), info.get("totalCash"), info.get("ebitda")
    dl_ebitda = (divida - (caixa or 0)) / ebitda if divida is not None and ebitda and ebitda > 0 else None
    return dict(
        pl=pl, pl_medio=pl_medio, metodo=metodo, lpa=lpa, lpa_fonte=lpa_fonte, lpa_sec=lpa_sec, preco_medio=preco_medio,
        media_desde=media_desde, media_meses=media_meses,
        lpa_agora=lpa_agora, lpa_antes=lpa_antes, base_lpa=base_lpa,
        div=div12, div_antes=div12_antes, dy=dy, dy_medio=dy_medio,
        div5=soma(5, 0) if cobre_5 else None,
        acoes=info.get("sharesOutstanding") or info.get("impliedSharesOutstanding"),
        vpa=vpa, graham=preco_justo_graham(lpa, vpa), bazin=bazin, div_medio5=div_medio5,
        pl_hist=pl_hist, anos_hist=anos_hist,
        justo_pl=pl_hist * lpa if pl_hist and lpa and lpa > 0 else None,
        dl_ebitda=dl_ebitda, balanco=balanco, receita=receita, receita_media=receita_media,
        receita_prev=receita_prev, analistas_rec=analistas_rec,
        lucros=d["lucro_tri"] if d["lucro_tri"] is not None else lpa_tri,
    )


def _pontos_anuais(serie) -> list[tuple[int, float]]:
    """Série anual -> [(ano, valor)], do mais antigo ao mais novo, sem cortar: o Yahoo já costuma
    trazer só ~4 anos por conta própria, mas a SEC (LPA anual dos EUA, ver app.lpa_anual_eua) pode
    trazer bem mais - cortar aqui também travaria "Média 5/10 anos" em "Sem dado" mesmo com a SEC
    tendo o histórico completo."""
    if serie is None or not len(serie):
        return []
    s = serie.dropna().sort_index()
    return [(int(ts.year), float(v)) for ts, v in s.items()]


def _media_n_anos(pontos: list[tuple[int, float]], n: int) -> float | None:
    """Média simples do LPA dos últimos n anos; None se o Yahoo não tiver os n anos (nunca estende
    com menos anos do que o pedido, nem mistura com dado trimestral)."""
    if len(pontos) < n:
        return None
    return sum(v for _, v in pontos[-n:]) / n


def _estimativa(df, linhas, coluna):
    """Crescimento estimado pelos analistas (fração no Yahoo -> %). Devolve (valor, linha usada)."""
    if df is None or getattr(df, "empty", True) or coluna not in df.columns:
        return None, None
    for linha in linhas:
        if linha in df.index:
            v = _n(df.loc[linha, coluna])
            if v is not None:
                return v * 100, linha
    return None, None


def modo_lynch(d: dict, pl, regra: dict) -> dict:
    """Passado (demonstrativos anuais), futuro (estimativas de analistas no Yahoo) e PEG do futuro."""
    info = d["info"]
    # crescimento recente (não o histórico todo, que a SEC pode estender bem além de ~4 anos -
    # mudaria o sentido do indicador, de "crescimento recente" pra um CAGR de décadas)
    lpas, receitas = _pontos_anuais(d.get("lpa_anual"))[-4:], _pontos_anuais(d.get("receita_anual"))[-4:]
    lucro_pass, anos_lucro = (None, 0) if regra["status"] == "recorrente" else \
        crescimento_anual(lpas, excluir_negativos=regra["status"] == "excluido")
    rec_pass, anos_rec = crescimento_anual(receitas)
    # Futuro: só o que o Yahoo realmente fornece, cada linha com a sua base
    lucro_fut, _ = _estimativa(d.get("est_cresc"), ["LTG"], "stockTrend")      # longo prazo, ao ano
    rec_fut, _ = _estimativa(d.get("est_receita"), ["+1y"], "growth")          # próximo ano fiscal
    # LPA estimado do ano fiscal em curso: média do consenso, faixa e número de analistas
    lpa_este_ano = baixa = alta = analistas = None
    est = d.get("est_lucro")
    if est is not None and not getattr(est, "empty", True) and "avg" in est.columns and "0y" in est.index:
        linha = est.loc["0y"]
        lpa_este_ano = _n(linha.get("avg"), 4)
        baixa, alta = _n(linha.get("low"), 4), _n(linha.get("high"), 4)
        analistas = _n(linha.get("numberOfAnalysts"), 0)
    analistas_rec = None
    er = d.get("est_receita")
    if er is not None and not getattr(er, "empty", True) and "+1y" in er.index and "numberOfAnalysts" in er.columns:
        analistas_rec = _n(er.loc["+1y", "numberOfAnalysts"], 0)
    peg_futuro = None if regra["status"] == "recorrente" else peg(pl, lucro_fut)
    receita = rec_fut if rec_fut is not None else rec_pass
    fracao = lambda chave: None if info.get(chave) is None else _n(info[chave] * 100, 2)
    return {
        "passado": {"lucro": _n(lucro_pass, 2), "anosLucro": anos_lucro,
                    "receita": _n(rec_pass, 2), "anosReceita": anos_rec},
        "futuro": {"lucroLongo": _n(lucro_fut, 2), "receitaProx": _n(rec_fut, 2), "lpaEsteAno": lpa_este_ano,
                   "lpaBaixa": baixa, "lpaAlta": alta, "analistas": analistas, "analistasReceita": analistas_rec},
        "pegFuturo": _n(peg_futuro, 4),
        "pegYahoo": _n(info.get("trailingPegRatio") or info.get("pegRatio"), 4),
        "lucroTrimestre": fracao("earningsGrowth"), "receitaTrimestre": fracao("revenueGrowth"),
        "veredito": _veredito_com_fonte(peg_futuro, receita, regra["status"], lucro_fut,
                                        tem_estimativa=any(v is not None for v in (rec_fut, lpa_este_ano))),
    }


def _veredito_com_fonte(peg_futuro, receita, status, lucro_fut, tem_estimativa: bool) -> dict:
    """Sem PEG: diz qual dado falta no Yahoo, em vez de afirmar que não há estimativa nenhuma."""
    v = veredito(peg_futuro, receita, status, lucro_fut)
    if v["cor"] == "cinza" and tem_estimativa:
        v = {**v, "titulo": "Sem PEG - Yahoo não tem o crescimento de longo prazo deste ativo"}
    return v


def modo_simons(hist: pd.DataFrame, r: Resultado | None = None, faixa=None) -> dict:
    fech = _sem_fuso(hist)["Close"].dropna()
    q = queda_desde_topo(fech)
    janela = fech.tail(JANELA + 1)   # de -10 pregões até hoje
    topo_pos = q["topo_pos"] - (len(fech.tail(JANELA + 1)) - len(janela))
    hist_n = historico(fech)
    atual = hist_n.get(q["dias"]) if q["dias"] else None
    passo = {}
    if r is not None and faixa is not None:
        c = classificar(r.preco_atual, r.mm200, r.inclinacao_mm200, faixa.oportunidade_ate, faixa.cara_acima)
        t = timing(c["classe"], q["dias"], c["conservador"])
        passo = {"mm200": _n(r.mm200, 4), "distMM200": _n(c["distMM200"], 2), "mm200Caindo": c["mm200Caindo"], "mm200Incl": _n(r.inclinacao_mm200, 2),
                 "classe": c["classe"], "zona52": c["subzona"], "subzona": c["subzona"], "bemAbaixoAte": _n(c["bemAbaixoAte"], 4), "conservador": c["conservador"],
                 "parte": t["parte"], "entrada": t["acao"], "entradaDetalhe": t["detalhe"],
                 "oportunidadeAte": _n(c["oportunidadeAte"], 4), "caraAcima": _n(c["caroAcima"], 4),
                 "caraAcima52": _n(faixa.cara_acima, 4), "pelaMM200": c["pelaMM200"],
                 "min52": _n(faixa.minimo, 4), "max52": _n(faixa.maximo, 4)}
    return {**passo, "dias": q["dias"], "queda": _n(q["queda"], 2), "altas": q["altas"],
            **leitura(q["dias"], JANELA), "maximo": JANELA, "selo": SELO_SIMONS,
            "topo": _n(janela.iloc[topo_pos], 4) if q["dias"] else None,
            "topoData": f"{janela.index[topo_pos]:%d/%m/%Y}" if q["dias"] else None,
            "historico": [{"dias": n, "vezes": v["vezes"], "altas": v["altas"], "pct": _n(v["pct"], 1)} for n, v in hist_n.items()],
            "histAtual": None if not atual else {"vezes": atual["vezes"], "pct": _n(atual["pct"], 1)},
            "melhor": {k: (_n(v, 1) if isinstance(v, float) else v) for k, v in melhor_linha(hist_n).items()},
            "histDesde": f"{fech[fech.index > fech.index[-1] - pd.DateOffset(years=5)].index[0]:%d/%m/%Y}",
            "janelaDe": f"{janela.index[0]:%d/%m/%Y}", "janelaAte": f"{janela.index[-1]:%d/%m/%Y}",
            "pregoes": len(janela) - 1,
            "variacao10": _n((janela.iloc[-1] / janela.iloc[0] - 1) * 100, 2)}


def faixas_por_periodo(hist: pd.DataFrame, preco: float, *, compra_validada_52: bool,
                       quebrou: bool, motivo: str, simbolo: str, tendencia: str) -> dict:
    """Zonas e decisão calculadas com a mínima e a máxima de cada período do gráfico.

    "1a": últimas 52 semanas (padrão; é a faixa que o teste histórico valida).
    "5a": últimas 260 semanas. "max": todo o histórico.
    A mesma regra vale para todos: oportunidade = mínima + 30% da amplitude; fim da neutra = mínima + 70%.
    """
    h = _sem_fuso(hist).dropna(subset=["High", "Low", "Close"])
    fim = h.index[-1]
    periodos = {
        "1a": (h[h.index > fim - pd.DateOffset(years=1)], "Últimas 52 semanas", "52 semanas"),
        "5a": (h[h.index > fim - pd.DateOffset(years=5)], "Últimas 260 semanas (5 anos)", "5 anos"),
        "max": (h, f"Todo o histórico (desde {h.index[0]:%Y})", "todo o histórico"),
    }
    saida = {}
    for chave, (janela, rotulo, curto) in periodos.items():
        if janela.empty:
            continue
        anos = (fim - janela.index[0]).days / 365.25
        if chave == "5a" and anos < 4.75:          # histórico menor que 5 anos: diz quanto cobre
            rotulo, curto = f"Últimos {anos:.1f} anos (histórico disponível)".replace(".", ","), f"{anos:.1f} anos".replace(".", ",")
        minimo, maximo = float(janela["Low"].min()), float(janela["High"].max())
        z = zonas(minimo, maximo)
        e = decidir_estado(percentil_na_faixa(preco, minimo, maximo), minimo, maximo,
                           compra_validada=compra_validada_52 if chave == "1a" else False,
                           quebrou=quebrou, motivo_quebra=motivo, simbolo=simbolo,
                           preco=preco, tendencia=tendencia)
        saida[chave] = {"min": _n(minimo, 4), "max": _n(maximo, 4),
                        "zOport": _n(z.oportunidade_ate, 4), "zCara": _n(z.cara_acima, 4),
                        "rotulo": rotulo, "curto": curto, "testada": chave == "1a",
                        "decisao": {"codigo": e.codigo, "rotulo": e.rotulo, "texto": e.texto, "zona": e.zona,
                                    "validado": e.validado, "alerta": e.alerta}}
    return saida


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


def _inicial(curto: str, guia: dict | None, lpa_anos, r: Resultado, acoes) -> dict:
    """Projeção do início do ano (congelada) para o mesmo período do guidance atual."""
    ano = (guia or {}).get("periodo") or str(lpa_anos[-1][0] + 1 if lpa_anos else r.data_ultimo.year)
    g = guidance_inicial(curto, ano, acoes_padrao=acoes) or {}
    return {k: (_n(v, 4) if isinstance(v, float) else v) for k, v in g.items()}


def montar(ticker: str, d: dict, r: Resultado, comparadores: dict, padrao: str) -> dict:
    """Pacote completo da tela para um ticker."""
    info, hist = d["info"], d["hist"]
    cod = info.get("currency") or ("BRL" if ticker.endswith(".SA") else "USD")
    moeda = SIMBOLO.get(cod, cod)
    curto = ticker[:-3] if ticker.endswith(".SA") else ticker
    f = fundamentos(d, r, ticker)

    bt5, btmax = _backtest(hist, 5, curto), _backtest(hist, None, curto)
    quebrou, motivo = fundamento_quebrou(f["lucros"], f["dl_ebitda"])
    # direção da tendência: só a posição do preço em relação à média de 200 dias
    direcao = "—" if r.mm200 is None else ("Alta" if r.preco_atual > r.mm200 else "Baixa")
    pontos_lpa = _pontos_anuais(d.get("lpa_anual"))
    lpa_anos = pontos_lpa[-3:]
    regra = regra_prejuizo([v for _, v in lpa_anos])
    lpa_media_3a = regra["media"] if regra["status"] in ("ok", "excluido") else None
    graham = graham_duas_versoes(f["lpa"], lpa_media_3a, f["vpa"])
    # médias de 5 e 10 anos: mesma fonte anual (Yahoo, ou SEC quando disponível - ver
    # app.lpa_anual_eua), sem estender com dado trimestral; "Sem dado" quando a fonte não tem os
    # anos pedidos (o Yahoo sozinho costuma trazer só ~4 anos; a SEC, bem mais)
    lpa_media_5a, lpa_media_10a = _media_n_anos(pontos_lpa, 5), _media_n_anos(pontos_lpa, 10)
    pl_conservador = r.preco_atual / lpa_media_10a if lpa_media_10a and lpa_media_10a > 0 and r.preco_atual else None
    teto_conservador = lpa_media_10a * 15 if lpa_media_10a and lpa_media_10a > 0 else None
    # Faixa de preço do modo Conservador: valuation (âncora = preço médio dos últimos 1 ano), não
    # a faixa de preço histórica de 52 semanas. Sem 1 ano de histórico de preço: fica None, e a
    # tela usa a faixa de 52 semanas como alternativa visual (nunca inventa o teto).
    teto_v = teto_valuation_conservador(r.media_fechamentos, r.media_fech_3a, r.media_fech_5a)
    faixa = zonas(r.minimo_1a, r.maximo_1a)   # faixa de 52 semanas: usada abaixo também por modo_simons/zOport/zCara
    conservador_faixa = None
    if teto_v["teto"] is not None:
        # zona neutra alargada: 30% acima da âncora, não trava em "Cara" assim que passa do teto
        caro_acima = teto_v["teto"] * 1.30
        oportunidade_ate = teto_v["teto"] * 0.70
        estado_c = decidir_estado_conservador(r.preco_atual, teto_v["teto"], caro_acima,
                                              quebrou=quebrou, motivo_quebra=motivo, simbolo=moeda)
        conservador_faixa = {
            "ancora1a": _n(teto_v["ancora1a"], 4), "teto": _n(teto_v["teto"], 4),
            "oportunidadeAte": _n(oportunidade_ate, 4), "caroAcima": _n(caro_acima, 4),
            # referência extra (não trava a decisão, só marcada na própria barra): limite de 3 anos
            # (margem de 40%), de 5 anos (margem de 50%) e a média de 200 dias
            "limite3a": _n(teto_v["limite3a"], 4), "limite5a": _n(teto_v["limite5a"], 4),
            "mm200": _n(r.mm200, 4),
            "decisao": {"codigo": estado_c.codigo, "rotulo": estado_c.rotulo, "texto": estado_c.texto,
                       "zona": estado_c.zona, "validado": estado_c.validado, "alerta": estado_c.alerta},
        }
    estado = decidir_estado(
        r.percentil, r.minimo_1a, r.maximo_1a,
        compra_validada=bool(bt5 and bt5["compraValidada"]),
        venda_validada=bool(bt5 and bt5["vendaValidada"]),
        quebrou=quebrou, motivo_quebra=motivo, simbolo=moeda,
        preco=r.preco_atual, tendencia=direcao)

    # guidance oficial da empresa (OVERRIDE) ganha do consenso do Yahoo no LPA projetado
    lynch = modo_lynch(d, f["pl"], regra)
    pl_ = preco_lynch(r.preco_atual, r.mm200, moeda)
    lynch["preco"] = None if not pl_ else {**pl_, "dist": _n(pl_["dist"], 2), "mm200": _n(r.mm200, 4),
                                           **{k: _n(pl_[k], 4) for k in ("bemAbaixoAte", "oportunidadeAte", "caroAcima")}}
    g = guidance_oficial(curto, acoes_padrao=f["acoes"])
    guia = None
    # consenso do Yahoo para o ano em curso, guardado antes do guidance substituir (card de P/L mostra os dois)
    fu = lynch["futuro"]
    consenso_ano = {"lpa": fu["lpaEsteAno"], "analistas": fu["analistas"], "baixa": fu["lpaBaixa"], "alta": fu["lpaAlta"]}
    if g:
        lynch["futuro"].update({"lpaEsteAno": _n(g["lpa"], 4), "lpaBaixa": _n(g["lpaMin"], 4),
                                "lpaAlta": _n(g["lpaMax"], 4), "analistas": None})
        guia = {"lpa": _n(g["lpa"], 4), "lpaMin": _n(g["lpaMin"], 4), "lpaMax": _n(g["lpaMax"], 4),
                "dividendo": _n(g["dividendo"], 4), "payout": _n(g["payout"], 4),
                "lucroMin": _n(g["lucroMin"], 0), "lucroMax": _n(g["lucroMax"], 0),
                "acoes": _n(g["acoes"], 0), "fonte": g["fonte"], "data": g["data"],
                "url": g["url"] if g["url"].startswith("https://") else "", "metodo": g["metodo"],
                "acoesFonte": g["acoesFonte"], "lucroTipo": g["lucroTipo"], "porLpa": g.get("porLpa", False),
                "periodo": g.get("periodo", ""), "dividendoFonte": g.get("dividendoFonte", ""),
                "bases": g.get("bases", [])}

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
        "mm200": _n(r.mm200, 4), "tendencia": direcao, "forca": _n(r.ifr, 0),
        "dist200d7d": _n(r.dist_mm200_7d, 2), "forca7d": _n(r.ifr_7d, 0),
        "lpaAnos": [{"ano": a, "lpa": _n(v, 4)} for a, v in lpa_anos],
        "lpaAnualFonte": d.get("lpa_anual_fonte") or "",
        "lpaAnualSecMotivo": d.get("lpa_anual_sec_motivo") or "",
        "outlookTrimestral": _com_proximo_anuncio(outlook_trimestral_eua(ticker), info),
        "regra": {"status": regra["status"], "media": _n(regra["media"], 4), "mensagem": regra["mensagem"]},
        "lpaMedia5a": _n(lpa_media_5a, 4), "lpaMedia10a": _n(lpa_media_10a, 4),
        "plConservador": _n(pl_conservador, 2), "tetoConservador": _n(teto_conservador, 2),
        "conservadorFaixa": conservador_faixa,
        "lynch": lynch,
        "guidance": guia, "consensoAno": consenso_ano,
        "guidanceInicial": _inicial(curto, guia, lpa_anos, r, f["acoes"]),
        "simons": modo_simons(hist, r, faixa),
        "pl": _n(f["pl"], 4), "plMedio12": _n(f["pl_medio"], 4), "precoMedio12": _n(f["preco_medio"], 4), "mediaDesde": f["media_desde"], "mediaMeses": f["media_meses"], "plMetodo": f["metodo"],
        "lpa": _n(f["lpa"], 4), "lpaAgora": _n(f["lpa_agora"], 4), "lpa12Atras": _n(f["lpa_antes"], 4),
        "baseLpa": f["base_lpa"], "balanco": f["balanco"], "lpaFonte": f["lpa_fonte"], "lpaSec": f["lpa_sec"],
        "atualizacao": atualizacao_contabil(f["lpa_sec"]),
        "receita": _n(f["receita"], 0), "receitaMedia": _n(f["receita_media"], 0),
        "receitaPrev": _n(f["receita_prev"], 0), "analistasReceitaAno": f["analistas_rec"],
        "dividendo": _n(f["div"], 4), "dividendo12Atras": _n(f["div_antes"], 4),
        "dyMedio12": _n(f["dy_medio"], 4), "dividendos5Anos": _n(f["div5"], 4),
        "acoes": _n(f["acoes"], 0), "vpa": _n(f["vpa"], 4),
        "plHistorico": _n(f["pl_hist"], 4), "plHistAnos": _n(f["anos_hist"], 1),
        "graham": _n(graham["usado"], 4), "grahamAtual": _n(graham["atual"], 4),
        "grahamMedia": _n(graham["media"], 4), "grahamBase": graham["base"], "grahamAviso": graham["aviso"],
        "lpaMedio3a": _n(lpa_media_3a, 4),
        "justoPL": _n(f["justo_pl"], 4),
        "bazin": _n(f["bazin"], 4), "divMedio5": _n(f["div_medio5"], 4),
        "retorno": {"periodos": ROTULO_PERIODOS,
                    "total": [_n(x, 2) for x in (r.retorno_1a, r.retorno_3a, r.retorno_5a)],
                    "preco": [_n(x, 2) for x in (r.retorno_preco_1a, r.retorno_preco_3a, r.retorno_preco_5a)]},
        "preco1AnoAtras": um_ano["c"][0] if um_ano else None,
        "data1AnoAtras": f"{pd.Timestamp(um_ano['t'][0], unit='ms'):%d/%m/%Y}" if um_ano else None,
        "comparadores": comparadores, "comparadorPadrao": padrao,
        "backtest": {"5a": bt5, "max": btmax},
        "decisao": {"codigo": estado.codigo, "rotulo": estado.rotulo, "texto": estado.texto, "zona": estado.zona,
                    "validado": estado.validado, "alerta": estado.alerta},
        "zOport": _n(faixa.oportunidade_ate, 4), "zCara": _n(faixa.cara_acima, 4),
        "faixas": faixas_por_periodo(hist, r.preco_atual, compra_validada_52=bool(bt5 and bt5["compraValidada"]),
                                     quebrou=quebrou, motivo=motivo, simbolo=moeda, tendencia=direcao),
        "series": series,
    }
