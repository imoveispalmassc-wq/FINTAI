"""Trava de segurança pros PRs do Automático (pedida pelo usuário, 28/11/2026): 4 travas, nenhuma
pode falhar pra mergear. Ver utils/revisao_pr.py para a explicação de cada uma."""
from utils.revisao_pr import (
    fonte_oficial_rastreavel,
    revisar,
    tickers_removidos,
    tickers_trocados,
    valores_regredidos,
)


def test_trava1_detecta_ticker_apagado():
    antes = {"PETR4": {"lpa_ttm": 3.0}, "BBAS3": {"lpa_ttm": 2.18}}
    depois = {"BBAS3": {"lpa_ttm": 2.18}}
    assert tickers_removidos(antes, depois) == ["PETR4"]


def test_trava1_passa_sem_ticker_apagado():
    antes = {"PETR4": {"lpa_ttm": 3.0}}
    depois = {"PETR4": {"lpa_ttm": 3.0}, "BBAS3": {"lpa_ttm": 2.18}}
    assert tickers_removidos(antes, depois) == []


def test_trava2_detecta_valor_regredido_mesmo_periodo():
    antes = {"TGT": {"trimestre_ref": "3T26", "lpa_ttm": 10.77}}
    depois = {"TGT": {"trimestre_ref": "3T26", "lpa_ttm": 10.76}}
    achados = valores_regredidos(antes, depois)
    assert achados == [{"ticker": "TGT", "campo": "lpa_ttm", "antes": 10.77, "depois": 10.76,
                        "periodo": {"trimestre_ref": "3T26"}}]


def test_trava2_periodo_novo_nunca_e_regressao_mesmo_com_valor_menor():
    antes = {"TGT": {"trimestre_ref": "2T26", "lpa_ttm": 10.77}}
    depois = {"TGT": {"trimestre_ref": "3T26", "lpa_ttm": 9.50}}
    assert valores_regredidos(antes, depois) == []


def test_trava2_biblioteca_json_campo_aninhado():
    antes = {"BBAS3": {"lpa_atual": {"periodo": "3T26", "valor": 0.21}}}
    depois = {"BBAS3": {"lpa_atual": {"periodo": "3T26", "valor": 0.19}}}
    achados = valores_regredidos(antes, depois)
    assert achados[0]["campo"] == "lpa_atual.valor"
    assert achados[0]["antes"] == 0.21 and achados[0]["depois"] == 0.19


def test_trava3_sem_link_falha():
    assert fonte_oficial_rastreavel({"valor": 10.77}) is False


def test_trava3_com_link_passa():
    assert fonte_oficial_rastreavel({"valor": 10.77, "link": "https://sec.gov/x"}) is True


def test_trava4_detecta_ticker_trocado_mesmo_link_e_valor():
    depois = {
        "GOOGL": {"lpa_atual": {"valor": 19.16, "link": "https://x.com/msft-release"}},
        "MSFT": {"lpa_atual": {"valor": 19.16, "link": "https://x.com/msft-release"}},
    }
    achados = tickers_trocados(depois)
    assert len(achados) == 1
    assert achados[0]["tickers"] == ["GOOGL", "MSFT"]


def test_trava4_mesmo_link_valores_diferentes_nao_e_troca():
    depois = {
        "GOOGL": {"lpa_atual": {"valor": 19.03, "link": "https://x.com/release"}},
        "MSFT": {"lpa_atual": {"valor": 19.16, "link": "https://x.com/release"}},
    }
    assert tickers_trocados(depois) == []


def test_revisar_passa_nas_4_travas():
    antes = {"BBAS3": {"lpa_atual": {"periodo": "3T26", "valor": 0.21, "link": "https://sec.gov/x"}}}
    depois = {
        "BBAS3": {"lpa_atual": {"periodo": "3T26", "valor": 0.21, "link": "https://sec.gov/x"}},
        "PETR4": {"lpa_atual": {"periodo": "3T26", "valor": 1.50, "link": "https://rad.cvm.gov.br/y"}},
    }
    v = revisar(antes, depois)
    assert v["passou"] is True
    assert v["falhas"] == {}


def test_revisar_falha_relata_o_motivo():
    antes = {"PETR4": {"lpa_atual": {"periodo": "3T26", "valor": 1.5, "link": "https://rad.cvm.gov.br/y"}}}
    depois = {}  # PETR4 sumiu
    v = revisar(antes, depois)
    assert v["passou"] is False
    assert "TRAVA 1 - ticker apagado" in v["falhas"]
    assert v["falhas"]["TRAVA 1 - ticker apagado"] == ["PETR4"]
