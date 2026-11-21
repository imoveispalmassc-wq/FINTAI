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


def test_guidance_em_lucro_por_acao_com_dividendo_da_empresa():
    from utils.override import guidance, validar
    t = {"ACM": {"lpa_min": 6.15, "lpa_max": 6.35, "periodo": "FY2027", "dividendo": 1.36,
                 "fonte": "AECOM 8-K", "data": "16/11/2026"}}
    g = guidance("ACM", tabela=t)
    assert g["porLpa"] and g["lpa"] == pytest.approx(6.25) and (g["lpaMin"], g["lpaMax"]) == (6.15, 6.35)
    assert g["dividendo"] == 1.36 and g["dividendoFonte"] == "empresa" and g["periodo"] == "FY2027"
    assert validar("X", {"lpa_min": 6, "lpa_max": 5, "fonte": "f", "data": "d"}) == ["lpa_min maior que lpa_max"]
    assert validar("X", {"lpa_min": 6, "lpa_max": 7, "data": "d"}) == ["falta o campo 'fonte'"]


def test_todo_cadastro_manual_tambem_entra_em_guidance_tickers_json():
    """Qualquer ticker com guidance manual em OVERRIDE precisa estar em guidance_tickers.json,
    senão o robô diário nunca passa a acompanhar (fica só no cadastro manual, parado no tempo) e a
    tela mostra "ainda não verificado" pra um ticker que já tem guidance oficial - vale igual pra
    B3 e EUA (antes só a B3 recebia esse cuidado por hábito)."""
    import json
    from pathlib import Path

    tickers = set(json.loads(Path(__file__).parent.parent.joinpath("utils", "guidance_tickers.json")
                             .read_text(encoding="utf-8")))
    faltando = [t for t in OVERRIDE if t.upper() not in tickers]
    assert not faltando, f"cadastrados em OVERRIDE mas fora de guidance_tickers.json: {faltando}"


def test_cadastros_adm_hsic_acm_e_xp_sem_guidance():
    from utils.override import OVERRIDE, guidance
    adm, hsic, acm = guidance("ADM"), guidance("HSIC"), guidance("ACM")
    assert adm["lpa"] == pytest.approx(5.65) and adm["data"] == "03/11/2026"
    assert hsic["lpa"] == pytest.approx(5.45) and hsic["data"] == "16/11/2026"
    assert hsic["bases"] == [{"ano": 2025, "valor": 4.65, "antes": 4.97}, {"ano": 2024, "valor": 4.58, "antes": 4.74}]
    assert acm["lpa"] == pytest.approx(6.25) and acm["dividendo"] == 1.36 and acm["periodo"] == "FY2027"
    assert all(g["fonte"] and g["data"] for g in (adm, hsic, acm))
    assert "XP" not in OVERRIDE


# ------------------------------------------------------------ projeção do início do ano (congelada)
def test_guidance_inicial_nao_muda_quando_chega_guidance_atualizado(tmp_path, monkeypatch):
    import json
    from utils import fetch_guidance as fg
    from utils.override import gravar_inicial, guidance_inicial
    inicial = {"lpa_min": 3.60, "lpa_max": 4.25, "fonte": "ADM 8-K 4T25", "data": "03/02/2026"}
    atualizado = {"lpa_min": 5.50, "lpa_max": 5.80, "fonte": "ADM 8-K 3T26", "data": "03/11/2026"}
    t, gravou = gravar_inicial({}, "ADM", "2026", inicial)
    assert gravou and t["ADM"]["2026"]["travado"]
    t2, gravou2 = gravar_inicial(t, "ADM", "2026", atualizado)            # chega o guidance novo
    assert not gravou2 and t2["ADM"]["2026"]["lpa_min"] == 3.60
    g = guidance_inicial("ADM", "2026", tabela=t2)
    assert g["lpa"] == pytest.approx(3.925) and g["data"] == "03/02/2026"
    # pelo robô: com a projeção já gravada, nem busca de novo e o arquivo não muda
    arq = tmp_path / "ini.json"
    arq.write_text(json.dumps(t2), encoding="utf-8")
    monkeypatch.setattr(fg, "ARQ_INICIAL", arq)
    assert fg.planejar_inicial("ADM", fg.dt.date(2026, 11, 17), t2) is None
    assert fg.aplicar_iniciais([{"ticker": "ADM", "inicial": {"ano": "2026", "novo": atualizado, "motivo": ""}}]) == 0
    assert json.loads(arq.read_text(encoding="utf-8"))["ADM"]["2026"]["lpa_max"] == 4.25


def test_sem_inicial_fica_marcado_e_pode_ser_preenchido_depois():
    from utils.override import SEM_INICIAL, gravar_inicial, guidance_inicial
    t, _ = gravar_inicial({}, "HSIC", "2026", None)
    assert t["HSIC"]["2026"] == {"status": SEM_INICIAL} and guidance_inicial("HSIC", "2026", tabela=t)["status"] == SEM_INICIAL
    t, gravou = gravar_inicial(t, "HSIC", "2026", {"lpa_min": 5.1, "lpa_max": 5.3, "fonte": "f", "data": "d"})
    assert gravou and t["HSIC"]["2026"]["lpa_min"] == 5.1


def test_cadastro_inicial_adm_backfill_e_vazios():
    from utils.override import guidance, guidance_inicial
    adm = guidance_inicial("ADM", "2026")
    assert (adm["lpaMin"], adm["lpaMax"], adm["data"]) == (3.60, 4.25, "03/02/2026") and adm["travado"]
    assert guidance("ADM")["lpa"] == pytest.approx(5.65)            # guidance atual intacto
    # HSIC, ACM e XP começam vazios; o robô pode preencher uma vez (travado, com fonte e data)
    for t, ano in (("HSIC", "2026"), ("ACM", "FY2027"), ("XP", "2026")):
        g = guidance_inicial(t, ano)
        assert g.get("status") == "sem projeção inicial encontrada" or (g["travado"] and g["fonte"] and g["data"])
