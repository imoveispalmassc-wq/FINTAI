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
