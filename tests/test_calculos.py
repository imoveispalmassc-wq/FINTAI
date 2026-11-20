import pytest

from calculos import normalizar_ticker


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


def test_teto_valuation_conservador_numero_de_graham():
    from calculos import teto_valuation_conservador
    r = teto_valuation_conservador(2.0, 20.0)   # Número de Graham = sqrt(22.5*2*20) = 30
    assert r["teto"] == pytest.approx(30.0) and r["numeroGraham"] == pytest.approx(30.0) and r["aviso"] == ""


def test_teto_valuation_conservador_sem_vpa_cai_para_p_l_15():
    from calculos import teto_valuation_conservador
    r = teto_valuation_conservador(2.0, None)
    assert r["teto"] == pytest.approx(30.0) and r["numeroGraham"] is None
    assert "Sem VPA" in r["aviso"] and "15" in r["aviso"]


def test_teto_valuation_conservador_sem_lpa_media_e_sem_dado():
    from calculos import teto_valuation_conservador
    assert teto_valuation_conservador(None, 20.0) == {"teto": None, "numeroGraham": None, "aviso": ""}
    assert teto_valuation_conservador(0, 20.0)["teto"] is None
    assert teto_valuation_conservador(-1, 20.0)["teto"] is None


def test_teto_valuation_conservador_vpa_invalido_tambem_cai_para_15():
    from calculos import teto_valuation_conservador
    assert teto_valuation_conservador(2.0, 0)["teto"] == pytest.approx(30.0)
    assert teto_valuation_conservador(2.0, -5)["teto"] == pytest.approx(30.0)
