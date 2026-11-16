import pytest

from utils.override import OVERRIDE, guidance, validar

TABELA = {"XXXX3": {"lucro_min": 21e9, "lucro_max": 25e9, "acoes": 5.73e9, "payout": 0.40,
                    "fonte": "Empresa X, release 4T25", "data": "10/02/2026"}}


def test_lpa_e_dividendo_pelo_guidance():
    g = guidance("XXXX3", TABELA)
    assert g["lpa"] == pytest.approx((21e9 + 25e9) / 2 / 5.73e9)
    assert g["dividendo"] == pytest.approx(g["lpa"] * 0.40)
    assert g["lpaMin"] == pytest.approx(21e9 / 5.73e9) and g["lpaMax"] == pytest.approx(25e9 / 5.73e9)
    assert (g["fonte"], g["data"]) == ("Empresa X, release 4T25", "10/02/2026")


def test_ticker_aceita_sufixo_e_minusculas():
    assert guidance("xxxx3.SA", TABELA) is not None
    assert guidance("YYYY3", TABELA) is None


@pytest.mark.parametrize("mudanca,erro", [
    ({"lucro_min": 30e9}, "lucro_min maior"),
    ({"acoes": 0}, "acoes"),
    ({"lucro_max": None}, "lucro_max"),
    ({"payout": 40}, "payout"),
    ({"fonte": ""}, "fonte"),
])
def test_cadastro_invalido_e_ignorado(mudanca, erro):
    o = {**TABELA["XXXX3"], **mudanca}
    assert any(erro in e for e in validar("XXXX3", o))
    assert guidance("XXXX3", {"XXXX3": o}) is None


def test_tabela_real_comeca_vazia_ou_valida():
    # nenhum valor sem fonte: tudo que estiver cadastrado precisa passar na validação
    for ticker, o in OVERRIDE.items():
        assert validar(ticker, o) == [], ticker


def test_payout_e_opcional():
    o = {k: v for k, v in TABELA["XXXX3"].items() if k != "payout"}
    g = guidance("XXXX3", {"XXXX3": o})
    assert g is not None and g["payout"] is None and g["dividendo"] is None


def test_cadastro_manual_ganha_do_automatico(tmp_path, monkeypatch):
    import json
    import utils.override as ov
    auto = tmp_path / "auto.json"
    auto.write_text(json.dumps({"XXXX3": {**TABELA["XXXX3"], "lucro_min": 1e9, "lucro_max": 2e9},
                                "YYYY3": TABELA["XXXX3"]}))
    monkeypatch.setattr(ov, "ARQ_AUTO", auto)
    monkeypatch.setattr(ov, "OVERRIDE", {"XXXX3": TABELA["XXXX3"]})
    assert ov.guidance("XXXX3")["lucroMin"] == 21e9      # manual
    assert ov.guidance("YYYY3") is not None               # automático


def test_acoes_do_yahoo_quando_o_cadastro_nao_traz():
    o = {k: v for k, v in TABELA["XXXX3"].items() if k != "acoes"}
    assert guidance("XXXX3", {"XXXX3": o}) is None                  # sem ações em lugar nenhum
    g = guidance("XXXX3", {"XXXX3": o}, acoes_padrao=5.73e9)
    assert g["lpa"] == pytest.approx(23e9 / 5.73e9) and g["acoesFonte"] == "Yahoo Finance"


def test_cadastro_do_bbas3_com_o_guidance_de_11_11_2026():
    from utils.override import OVERRIDE
    o = OVERRIDE["BBAS3"]
    assert (o["lucro_min"], o["lucro_max"], o["payout"], o["data"]) == (9e9, 11e9, 0.25, "11/11/2026")
    g = guidance("BBAS3", OVERRIDE, acoes_padrao=5.73e9)
    assert g["lpa"] == pytest.approx(10e9 / 5.73e9) and g["dividendo"] == pytest.approx(g["lpa"] * 0.25)
