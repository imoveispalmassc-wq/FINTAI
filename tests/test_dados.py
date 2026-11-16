import numpy as np
import pandas as pd
import pytest

from calculos import calcular
from tela.dados import series_do_grafico


def _hist():
    idx = pd.bdate_range("2019-01-01", "2026-11-13", tz="America/New_York")
    c = pd.Series(50 * np.exp(np.cumsum(np.random.default_rng(4).normal(0.0006, 0.02, len(idx)))), idx)
    return pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c, "Adj Close": c,
                         "Volume": 1000, "Dividends": 0.0, "Stock Splits": 0.0})


def test_grafico_1a_e_retorno_usam_a_mesma_base():
    """A variação do gráfico em 1A tem de ser igual ao retorno só preço de 1 ano."""
    h = _hist()
    r = calcular(h, None)
    s = series_do_grafico(h, {})["1a"]
    variacao = (s["c"][-1] / s["c"][0] - 1) * 100
    assert variacao == pytest.approx(r.retorno_preco_1a, abs=0.01)


def test_grafico_5a_usa_a_base_do_retorno_de_5_anos():
    h = _hist()
    r = calcular(h, None)
    s = series_do_grafico(h, {})["5a"]
    assert (s["c"][-1] / s["base"] - 1) * 100 == pytest.approx(r.retorno_preco_5a, abs=0.01)


def test_series_sem_intraday_ficam_nulas():
    s = series_do_grafico(_hist(), {"hoje": pd.DataFrame(), "1s": None})
    assert s["hoje"] is None and s["1s"] is None and s["1m"] is None and s["1a"] is not None


def test_consenso_traz_numero_de_analistas_e_faixa():
    from tela.dados import modo_lynch
    est = pd.DataFrame({"avg": [2.0, 176.5], "low": [1.8, 150.0], "high": [2.3, 210.0],
                        "numberOfAnalysts": [20, 28], "growth": [0.1, 1.34]}, index=["0q", "0y"])
    rec = pd.DataFrame({"growth": [0.3], "numberOfAnalysts": [25]}, index=["+1y"])
    d = {"info": {}, "lpa_anual": None, "receita_anual": None, "est_lucro": est,
         "est_receita": rec, "est_cresc": None}
    L = modo_lynch(d, 10.0, {"status": "ok"})
    f = L["futuro"]
    assert (f["lpaEsteAno"], f["lpaBaixa"], f["lpaAlta"], f["analistas"]) == (176.5, 150.0, 210.0, 28)
    assert f["analistasReceita"] == 25 and f["lucroLongo"] is None
    # sem crescimento de longo prazo, diz exatamente o que falta
    assert L["veredito"]["titulo"] == "Sem PEG - Yahoo não tem o crescimento de longo prazo deste ativo"


def test_sem_estimativa_nenhuma_mantem_o_aviso_geral():
    from tela.dados import modo_lynch
    d = {"info": {}, "lpa_anual": None, "receita_anual": None, "est_lucro": None,
         "est_receita": None, "est_cresc": None}
    assert modo_lynch(d, 10.0, {"status": "ok"})["veredito"]["titulo"] == "Sem PEG - Sem estimativa no Yahoo para este ativo"


def test_faixa_acompanha_o_periodo_do_grafico():
    from tela.dados import faixas_por_periodo
    h = _hist()
    fx = faixas_por_periodo(h, float(h["Close"].iloc[-1]), compra_validada_52=True, quebrou=False,
                            motivo="", simbolo="R$", tendencia="Alta")
    assert set(fx) == {"1a", "5a", "max"}
    hh = h.copy(); hh.index = hh.index.tz_localize(None)
    fim = hh.index[-1]
    for chave, anos in (("1a", 1), ("5a", 5)):
        jan = hh[hh.index > fim - pd.DateOffset(years=anos)]
        assert fx[chave]["min"] == pytest.approx(jan["Low"].min(), abs=1e-3)
        assert fx[chave]["max"] == pytest.approx(jan["High"].max(), abs=1e-3)
        amp = fx[chave]["max"] - fx[chave]["min"]
        assert fx[chave]["zOport"] == pytest.approx(fx[chave]["min"] + 0.3 * amp, abs=1e-3)
        assert fx[chave]["zCara"] == pytest.approx(fx[chave]["min"] + 0.7 * amp, abs=1e-3)
    assert fx["max"]["min"] <= fx["5a"]["min"] <= fx["1a"]["min"]
    assert fx["1a"]["rotulo"] == "Últimas 52 semanas" and fx["5a"]["rotulo"] == "Últimas 260 semanas (5 anos)"
    # só a faixa de 52 semanas tem teste histórico
    assert fx["1a"]["testada"] and not fx["5a"]["testada"] and not fx["max"]["testada"]
    assert "Ponto de oportunidade em R$" in fx["5a"]["decisao"]["texto"]


def test_faixa_de_5_anos_com_historico_curto_diz_quanto_cobre():
    from tela.dados import faixas_por_periodo
    h = _hist().tail(600)          # pouco mais de 2 anos de pregões
    fx = faixas_por_periodo(h, float(h["Close"].iloc[-1]), compra_validada_52=False, quebrou=False,
                            motivo="", simbolo="R$", tendencia="Alta")
    assert fx["5a"]["rotulo"].startswith("Últimos 2,") and "histórico disponível" in fx["5a"]["rotulo"]


# ------------------------------------------------------------ Graham em duas versões
from calculos import graham_duas_versoes


def test_graham_usa_o_menor_dos_dois():
    g = graham_duas_versoes(74.33, 27.91, 122.35)          # lucro atual acima da média
    assert g["atual"] == pytest.approx(452.35, abs=0.01)
    assert g["media"] == pytest.approx(277.19, abs=0.01)
    assert g["usado"] == g["media"] and g["base"] == "media" and not g["aviso"]


def test_graham_com_lucro_caindo_usa_o_atual_e_avisa():
    g = graham_duas_versoes(2.40, 4.08, 30.0)
    assert g["base"] == "atual" and g["usado"] == g["atual"]
    assert g["aviso"]                                        # 2,40 < 60% de 4,08 (2,448)


def test_graham_sem_lucro_atual_usa_so_a_media():
    g = graham_duas_versoes(-1.0, 4.08, 30.0)
    assert g["atual"] is None and g["base"] == "media" and g["usado"] == g["media"]


def test_graham_sem_media_usa_so_o_atual_e_sem_nada_nao_calcula():
    g = graham_duas_versoes(2.40, None, 30.0)
    assert g["media"] is None and g["base"] == "atual" and not g["aviso"]
    vazio = graham_duas_versoes(None, None, 30.0)
    assert vazio["usado"] is None and vazio["base"] is None


def test_aviso_no_limite_de_60_por_cento():
    assert not graham_duas_versoes(6.0, 10.0, 30.0)["aviso"]
    assert graham_duas_versoes(5.99, 10.0, 30.0)["aviso"]


# ------------------------------------------------------------ P/L médio na mesma base do P/L atual
from calculos import pl_medio_12m


def _fech_ano(preco=15.10):
    idx = pd.bdate_range("2025-11-17", "2026-11-13")
    return pd.Series(np.linspace(24.0, preco, len(idx)), idx)


def _lpa_trimestral(valores):
    datas = pd.to_datetime(["2024-11-13", "2025-02-19", "2025-05-15", "2025-08-14", "2025-11-12",
                            "2026-02-11", "2026-05-13", "2026-08-11", "2026-11-11"])
    return pd.Series(valores, datas)


def test_serie_ajustada_com_lpa_contabil_nao_mistura_bases():
    # caso real BBAS3: LPA trimestral do Yahoo é o AJUSTADO (soma 2,56) e o LPA de 12 meses é o CONTÁBIL (1,93)
    serie = _lpa_trimestral([1.66, 1.67, 1.29, 0.67, 0.66, 1.06, 0.60, 0.68, 0.22])
    valor, metodo = pl_medio_12m(_fech_ano(), serie, 1.93)
    assert metodo == "simplificado"                      # preço médio do ano ÷ LPA atual, mesma base
    assert valor == pytest.approx(_fech_ano().mean() / 1.93)


def test_serie_na_mesma_base_usa_o_lpa_de_cada_trimestre():
    serie = _lpa_trimestral([1.66, 1.67, 1.29, 0.67, 0.66, 1.06, 0.60, 0.68, 0.22])
    _, metodo = pl_medio_12m(_fech_ano(), serie, 2.56)
    assert metodo == "trimestral"


def test_ultimo_balanco_data_de_divulgacao():
    import pandas as pd
    from tela.dados import ultimo_balanco
    datas = pd.to_datetime(["2026-08-12", "2026-11-11"]).tz_localize("America/Sao_Paulo")
    assert ultimo_balanco(pd.Series([0.4, 0.2], index=datas)) == {"data": "11/11/2026"}
    assert ultimo_balanco(None) is None


def _bb_contabil():
    import pandas as pd
    acoes = 5.709e9
    tri = {"2025-06-30": 0.49, "2025-09-30": 0.39, "2025-12-31": 0.92, "2026-03-31": 0.42, "2026-06-30": 0.42}
    lucro = pd.Series({pd.Timestamp(k): v * acoes for k, v in tri.items()})
    anual = pd.Series({pd.Timestamp("2025-12-31"): 2.40, pd.Timestamp("2024-12-31"): 2.9})
    datas = pd.to_datetime(["2025-08-13", "2025-11-12", "2026-02-11", "2026-05-13", "2026-08-12", "2026-11-11"]).tz_localize("America/Sao_Paulo")
    return lucro, anual, acoes, datas


def test_lpa_contabil_de_cada_balanco_completa_trimestres_pelo_anual_e_pelo_ttm():
    import pandas as pd
    from calculos import lpa_contabil_ttm
    lucro, anual, acoes, datas = _bb_contabil()
    s = lpa_contabil_ttm(lucro, anual, acoes, 1.93, datas)
    assert [f"{t:%d/%m/%Y}" for t in s.index] == ["11/02/2026", "13/05/2026", "12/08/2026", "11/11/2026"]
    assert [round(v, 2) for v in s] == [2.40, 2.22, 2.15, 1.93]


def test_lpa_contabil_recusa_base_diferente_do_lpa_atual():
    from calculos import lpa_contabil_ttm
    lucro, anual, acoes, datas = _bb_contabil()
    # sem o 3T26 derivável (sem data de divulgação), o último TTM (2,15) não bate com 1,93 em 10%
    assert lpa_contabil_ttm(lucro, anual, acoes, 1.93, datas[:-1]) is None


def test_pl_medio_contabil_usa_o_lucro_de_cada_epoca():
    import pandas as pd
    from calculos import lpa_contabil_ttm, pl_medio_contabil
    lucro, anual, acoes, datas = _bb_contabil()
    s = lpa_contabil_ttm(lucro, anual, acoes, 1.93, datas)
    dias = pd.bdate_range("2025-11-14", "2026-11-13")
    r = pl_medio_contabil(pd.Series(20.0, index=dias), s)
    assert r["desde"] == pd.Timestamp("2026-02-11") and 8.5 < r["meses"] < 9.5
    # P/L entre 20/2,40 = 8,33 e 20/1,93 = 10,36, menor que o simplificado (10,36)
    assert 8.33 < r["pl"] < 10.36 and r["preco_medio"] == 20.0
    assert pl_medio_contabil(pd.Series(20.0, index=dias), s, minimo=0.9) is None


def test_receita_media_no_ultimo_ano_com_cada_balanco():
    import pandas as pd
    from calculos import lpa_contabil_ttm, media_no_periodo
    lucro, anual, acoes, datas = _bb_contabil()
    receita_tri = lucro / acoes * 1e10          # mesma forma, em "receita"
    receita_anual = anual * 1e10
    s = lpa_contabil_ttm(receita_tri, receita_anual, 1.0, 1.93e10, datas)
    dias = pd.bdate_range("2025-11-14", "2026-11-13")
    m = media_no_periodo(pd.Series(1.0, index=dias), s)
    assert 1.93e10 < m < 2.40e10
    assert media_no_periodo(pd.Series(1.0, index=dias), None) is None
