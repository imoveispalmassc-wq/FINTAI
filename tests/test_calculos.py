import numpy as np
import pandas as pd
import pytest

from calculos import calcular, normalizar_ticker


def test_normalizar_ticker_br_padrao_ganha_sa():
    for t in ("PETR4", "VALE3", "ITUB4", "WEGE3", "BBAS3", "BOVA11"):
        assert normalizar_ticker(t) == f"{t}.SA"


def test_normalizar_ticker_b3sa3_ganha_sa_mesmo_com_digito_no_meio_do_codigo():
    # B3 S.A. (a própria bolsa): o código tem um dígito dentro do nome (B3SA), não só no final
    assert normalizar_ticker("B3SA3") == "B3SA3.SA"
    assert normalizar_ticker("b3sa3") == "B3SA3.SA"


def test_normalizar_ticker_eua_nao_ganha_sa():
    for t in ("AAPL", "MSFT", "TGT", "XP", "PANW"):
        assert normalizar_ticker(t) == t


def test_normalizar_ticker_ja_com_sufixo_nao_duplica():
    assert normalizar_ticker("PETR4.SA") == "PETR4.SA"


def test_teto_valuation_conservador_ancora_e_a_media_de_1_ano():
    from calculos import teto_valuation_conservador
    r = teto_valuation_conservador(100.0, 80.0, 60.0)
    assert r["teto"] == pytest.approx(100.0) and r["ancora1a"] == pytest.approx(100.0)
    assert r["limite3a"] == pytest.approx(48.0)    # margem de 40%: 0,60 × 80
    assert r["limite5a"] == pytest.approx(30.0)    # margem de 50%: 0,50 × 60


def test_teto_valuation_conservador_sem_3a_5a_nao_trava_o_teto():
    """Limite de 3/5 anos é só referência - sem esse histórico, o teto (âncora de 1 ano)
    continua valendo normalmente."""
    from calculos import teto_valuation_conservador
    r = teto_valuation_conservador(100.0, None, None)
    assert r["teto"] == pytest.approx(100.0)
    assert r["limite3a"] is None and r["limite5a"] is None


def test_teto_valuation_conservador_sem_media_1a_e_sem_dado():
    from calculos import teto_valuation_conservador
    assert teto_valuation_conservador(None, 80.0, 60.0) == {"teto": None, "ancora1a": None, "limite3a": None, "limite5a": None}
    assert teto_valuation_conservador(0, 80.0, 60.0)["teto"] is None
    assert teto_valuation_conservador(-1, 80.0, 60.0)["teto"] is None


def _hist_longa():
    # quase 8 anos de pregões (cobre a janela de 5 anos usada em media_fech_5a)
    idx = pd.bdate_range("2019-01-01", "2026-11-13", tz="America/New_York")
    c = pd.Series(50 * np.exp(np.cumsum(np.random.default_rng(4).normal(0.0006, 0.02, len(idx)))), idx)
    return pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c, "Adj Close": c,
                         "Volume": 1000, "Dividends": 0.0, "Stock Splits": 0.0})


def test_calcular_media_fech_3a_5a_ficam_perto_da_media_simples_dos_fechamentos():
    r = calcular(_hist_longa(), None)
    hist = _hist_longa()
    fim = hist.index[-1]
    esperado_3a = hist.loc[hist.index > fim - pd.DateOffset(years=3), "Close"].mean()
    esperado_5a = hist.loc[hist.index > fim - pd.DateOffset(years=5), "Close"].mean()
    # média semanal (não diária) tem uma diferença pequena pro cálculo direto; tolerância de 5%
    assert r.media_fech_3a == pytest.approx(esperado_3a, rel=0.05)
    assert r.media_fech_5a == pytest.approx(esperado_5a, rel=0.05)


def test_calcular_media_fech_3a_5a_sem_historico_suficiente_e_none():
    idx = pd.bdate_range("2025-01-01", "2026-11-13", tz="America/New_York")   # menos de 2 anos
    c = pd.Series(50 * np.exp(np.cumsum(np.random.default_rng(1).normal(0.0006, 0.02, len(idx)))), idx)
    hist = pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c, "Adj Close": c,
                         "Volume": 1000, "Dividends": 0.0, "Stock Splits": 0.0})
    r = calcular(hist, None)
    assert r.media_fech_3a is None and r.media_fech_5a is None


def test_calcular_marcador_7_pregoes_bate_com_indicadores_de_7_pregoes_atras():
    """Marcador que mostra pra que lado a Força da tendência/Força (IFR) estão indo: o mesmo IFR e a
    mesma distância preço÷MM200 de 7 pregões atrás, não do dia de hoje."""
    from calculos import indicadores

    hist = _hist_longa()
    r = calcular(hist, None)
    ind = indicadores(hist)
    linha7 = ind.iloc[-8]   # 7 pregões antes do último (índice -1)
    assert r.ifr_7d == pytest.approx(linha7["ifr"])
    preco7 = float(hist["Close"].iloc[-8])
    esperado_dist = (preco7 / float(linha7["mm200"]) - 1) * 100
    assert r.dist_mm200_7d == pytest.approx(esperado_dist)


def test_calcular_marcador_7_pregoes_sem_historico_suficiente_e_none():
    idx = pd.bdate_range("2026-01-01", periods=5)   # menos de 8 pregões
    c = pd.Series([10.0, 10.5, 11.0, 10.8, 10.9], index=idx)
    hist = pd.DataFrame({"Open": c, "High": c, "Low": c, "Close": c, "Adj Close": c,
                         "Volume": 1000, "Dividends": 0.0, "Stock Splits": 0.0})
    r = calcular(hist, None)
    assert r.ifr_7d is None and r.dist_mm200_7d is None
