"""Monta, a partir dos dados do Yahoo Finance, o pacote único que a tela de detalhes lê.

Fonte única de verdade: cada indicador é calculado uma vez aqui e todas as seções da tela
usam o mesmo valor. O que faltar vai como None e a tela mostra "Dados indisponíveis".
"""
from __future__ import annotations

import math

import pandas as pd

from calculos import (Resultado, crescimento_lpa, dy_atual_e_medio, pl_medio_12m,
                      graham_duas_versoes, pl_medio_longo, preco_justo_graham, preco_teto_bazin)
from utils.lynch import crescimento_anual, peg, regra_prejuizo, veredito
from utils.override import guidance as guidance_oficial
from utils.percentile import percentil_na_faixa, zonas
from utils.signals import (backtest_percentil, decidir_estado, fundamento_quebrou,
                           selo_backtest)
from utils.simons import SELO as SELO_SIMONS
from utils.simons import leitura, sequencia_de_quedas

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


def ultimo_balanco(lucro_tri, lpa_tri) -> dict | None:
    """Último trimestre divulgado (ex.: 3T26) e a data de divulgação, quando o Yahoo informa."""
    if lucro_tri is None or not len(lucro_tri):
        return None
    fim = pd.Timestamp(_sem_fuso(lucro_tri.dropna()).index.max())
    rotulo = f"{(fim.month - 1) // 3 + 1}T{fim.year % 100:02d}"
    data = None
    if lpa_tri is not None and len(lpa_tri):
        datas = [t for t in _sem_fuso(lpa_tri.dropna()).index if fim < t <= fim + pd.Timedelta(days=120)]
        if datas:
            data = f"{min(datas):%d/%m/%Y}"
    return {"trimestre": rotulo, "data": data}


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

    balanco = ultimo_balanco(d["lucro_tri"], lpa_tri)
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
        dl_ebitda=dl_ebitda, balanco=balanco,
        lucros=d["lucro_tri"] if d["lucro_tri"] is not None else lpa_tri,
    )


def _pontos_anuais(serie) -> list[tuple[int, float]]:
    """Série anual do Yahoo -> [(ano, valor)], do mais antigo ao mais novo (até 4 anos)."""
    if serie is None or not len(serie):
        return []
    s = serie.dropna().sort_index()
    return [(int(ts.year), float(v)) for ts, v in s.items()][-4:]


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
    lpas, receitas = _pontos_anuais(d.get("lpa_anual")), _pontos_anuais(d.get("receita_anual"))
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


def modo_simons(hist: pd.DataFrame) -> dict:
    fech = _sem_fuso(hist)["Close"].dropna()
    dias, queda = sequencia_de_quedas(fech)
    janela = fech.tail(11)   # de -10 pregões até hoje
    return {"dias": dias, "queda": _n(queda, 2), **leitura(dias), "selo": SELO_SIMONS,
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


def montar(ticker: str, d: dict, r: Resultado, comparadores: dict, padrao: str) -> dict:
    """Pacote completo da tela para um ticker."""
    info, hist = d["info"], d["hist"]
    cod = info.get("currency") or ("BRL" if ticker.endswith(".SA") else "USD")
    moeda = SIMBOLO.get(cod, cod)
    curto = ticker[:-3] if ticker.endswith(".SA") else ticker
    f = fundamentos(d, r)

    bt5, btmax = _backtest(hist, 5, curto), _backtest(hist, None, curto)
    quebrou, motivo = fundamento_quebrou(f["lucros"], f["dl_ebitda"])
    # direção da tendência: só a posição do preço em relação à média de 200 dias
    direcao = "—" if r.mm200 is None else ("Alta" if r.preco_atual > r.mm200 else "Baixa")
    lpa_anos = _pontos_anuais(d.get("lpa_anual"))[-3:]
    regra = regra_prejuizo([v for _, v in lpa_anos])
    lpa_media_3a = regra["media"] if regra["status"] in ("ok", "excluido") else None
    graham = graham_duas_versoes(f["lpa"], lpa_media_3a, f["vpa"])
    estado = decidir_estado(
        r.percentil, r.minimo_1a, r.maximo_1a,
        compra_validada=bool(bt5 and bt5["compraValidada"]),
        venda_validada=bool(bt5 and bt5["vendaValidada"]),
        quebrou=quebrou, motivo_quebra=motivo, simbolo=moeda,
        preco=r.preco_atual, tendencia=direcao)

    faixa = zonas(r.minimo_1a, r.maximo_1a)

    # guidance oficial da empresa (OVERRIDE) ganha do consenso do Yahoo no LPA projetado
    lynch = modo_lynch(d, f["pl"], regra)
    g = guidance_oficial(curto, acoes_padrao=f["acoes"])
    guia = None
    if g:
        lynch["futuro"].update({"lpaEsteAno": _n(g["lpa"], 4), "lpaBaixa": _n(g["lpaMin"], 4),
                                "lpaAlta": _n(g["lpaMax"], 4), "analistas": None})
        guia = {"lpa": _n(g["lpa"], 4), "lpaMin": _n(g["lpaMin"], 4), "lpaMax": _n(g["lpaMax"], 4),
                "dividendo": _n(g["dividendo"], 4), "payout": _n(g["payout"], 4),
                "lucroMin": _n(g["lucroMin"], 0), "lucroMax": _n(g["lucroMax"], 0),
                "acoes": _n(g["acoes"], 0), "fonte": g["fonte"], "data": g["data"],
                "url": g["url"] if g["url"].startswith("https://") else "", "metodo": g["metodo"],
                "acoesFonte": g["acoesFonte"], "lucroTipo": g["lucroTipo"]}

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
        "lpaAnos": [{"ano": a, "lpa": _n(v, 4)} for a, v in lpa_anos],
        "regra": {"status": regra["status"], "media": _n(regra["media"], 4), "mensagem": regra["mensagem"]},
        "lynch": lynch,
        "guidance": guia,
        "simons": modo_simons(hist),
        "pl": _n(f["pl"], 4), "plMedio12": _n(f["pl_medio"], 4), "precoMedio12": _n(float(r.fechamentos_1a.mean()), 4) if len(r.fechamentos_1a) else None, "plMetodo": f["metodo"],
        "lpa": _n(f["lpa"], 4), "lpaAgora": _n(f["lpa_agora"], 4), "lpa12Atras": _n(f["lpa_antes"], 4),
        "baseLpa": f["base_lpa"], "balanco": f["balanco"],
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
