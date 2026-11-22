import datetime as dt
import json

import pytest

from utils import dados_fixos as df

PETR4 = {"acoes_total": 12.89e9, "lucro_12m": 140.4e9, "dividendo_12m": None, "fator_adr": 1,
         "moeda_resultado": "BRL", "fonte_oficial": "PDF RI (CVM/IPE)", "data_ultimo_balanco": "30/09/2026"}
BBAS3 = {"acoes_total": 5.71e9, "lucro_12m": 12.45e9, "dividendo_12m": None, "fator_adr": 1,
         "moeda_resultado": "BRL", "fonte_oficial": "PDF RI (CVM/IPE)", "data_ultimo_balanco": "30/09/2026"}


# ------------------------------------------------------------ item 5 da Issue: fórmulas, tem que bater exatamente
def test_petr4_lpa_e_pl_batem_com_a_issue():
    ind = df.calcular_indicadores(PETR4, 42.67)
    assert ind["lpa"] == pytest.approx(10.89, abs=0.01)
    assert ind["pl"] == pytest.approx(3.92, abs=0.01)


def test_bbas3_lpa_e_pl_batem_com_a_issue():
    ind = df.calcular_indicadores(BBAS3, 14.30)
    assert ind["lpa"] == pytest.approx(2.18, abs=0.01)
    assert ind["pl"] == pytest.approx(6.56, abs=0.01)


def test_dy_e_formula_fixa():
    fixos = {**PETR4, "dividendo_12m": 4.0}
    ind = df.calcular_indicadores(fixos, 42.67)
    assert ind["dy"] == pytest.approx(4.0 / 42.67)


def test_adr_multiplica_pelo_fator():
    fixos = {**PETR4, "dividendo_12m": 2.0, "fator_adr": 2}
    ind = df.calcular_indicadores(fixos, 42.67)
    assert ind["lpaAdr"] == pytest.approx(ind["lpa"] * 2)
    assert ind["dividendoAdr"] == pytest.approx(4.0)


def test_sem_acoes_ou_lucro_fica_sem_dado():
    assert df.calcular_indicadores({"acoes_total": None, "lucro_12m": 1e9}, 10.0)["lpa"] is None
    assert df.calcular_indicadores({"acoes_total": 1e9, "lucro_12m": None}, 10.0)["lpa"] is None


def test_pl_medio_12m_media_dos_4_trimestres():
    fixos = {**PETR4, "trimestres": [
        {"tri": "4T25", "lucro": 28.651e9}, {"tri": "1T26", "lucro": 25.743e9},
        {"tri": "2T26", "lucro": 23.909e9}, {"tri": "3T26", "lucro": 55.813e9},
    ]}
    cotacoes = [30.0, 32.0, 35.0, 42.67]
    pl_medio = df.pl_medio_12m_fixo(fixos, cotacoes)
    esperado = sum(c / (t["lucro"] / fixos["acoes_total"]) for c, t in zip(cotacoes, fixos["trimestres"])) / 4
    assert pl_medio == pytest.approx(esperado)


def test_pl_medio_12m_sem_cotacoes_trimestrais_fica_sem_dado():
    fixos = {**PETR4, "trimestres": [{"tri": "3T26", "lucro": 1e9}]}
    assert df.pl_medio_12m_fixo(fixos, None) is None
    assert df.calcular_indicadores(fixos, 42.67)["plMedio12m"] is None


def test_contas_mostram_a_formula_embaixo():
    ind = df.calcular_indicadores(PETR4, 42.67)
    assert "140,40" in ind["contas"]["lpa"] and "12,89" in ind["contas"]["lpa"]
    assert "Fonte: PDF RI (CVM/IPE)" in ind["contas"]["acoes"]


# ------------------------------------------------------------ item 1: lista sob demanda / cache
def test_ticker_novo_busca_na_fonte_e_salva(tmp_path, monkeypatch):
    arq = tmp_path / "dados_fixos.json"
    monkeypatch.setattr(df, "ARQ", arq)
    chamadas = []

    def busca(ticker, hoje):
        chamadas.append(ticker)
        return {"status": "ok", **PETR4}

    r1 = df.obter("PETR4", dt.date(2026, 11, 22), 42.67, buscar_br=busca, verificar_novo=False)
    assert r1["status"] == "ok" and r1["pl"] == pytest.approx(3.92, abs=0.01)
    assert chamadas == ["PETR4"]
    assert json.loads(arq.read_text(encoding="utf-8"))["PETR4"]["acoes_total"] == PETR4["acoes_total"]

    # 2ª vez: usa o salvo, não busca de novo na fonte oficial
    r2 = df.obter("PETR4", dt.date(2026, 11, 23), 43.00, buscar_br=busca, verificar_novo=False)
    assert chamadas == ["PETR4"]                       # não chamou busca() outra vez
    assert r2["pl"] == pytest.approx(43.00 / r2["lpa"])
    assert r2["lpa"] == r1["lpa"]                       # fundamentos não mudaram, só a cotação


def test_ticker_nao_encontrado_na_fonte_oficial_nao_cria_entrada(tmp_path, monkeypatch):
    arq = tmp_path / "dados_fixos.json"
    monkeypatch.setattr(df, "ARQ", arq)

    def busca(ticker, hoje):
        return {"status": "nao_encontrado", "motivo": "CNPJ não encontrado na CVM"}

    r = df.obter("ZZZZ9", dt.date(2026, 11, 22), 10.0, buscar_br=busca)
    assert r == {"status": "nao_encontrado", "mensagem": df.MENSAGEM_NAO_ENCONTRADO,
                 "motivo": "CNPJ não encontrado na CVM", "ticker": "ZZZZ9"}
    assert not arq.exists()                             # nada gravado


def test_ticker_eua_usa_a_busca_dos_eua_nao_a_da_b3(tmp_path, monkeypatch):
    arq = tmp_path / "dados_fixos.json"
    monkeypatch.setattr(df, "ARQ", arq)
    chamou = {"br": False, "eua": False}

    def busca_br(ticker, hoje):
        chamou["br"] = True
        return {"status": "nao_encontrado", "motivo": "não deveria ter chamado"}

    def busca_eua(ticker, hoje):
        chamou["eua"] = True
        return {"status": "ok", "acoes_total": 1e9, "lucro_12m": 1e8, "dividendo_12m": None,
                "fator_adr": 1, "moeda_resultado": "USD", "fonte_oficial": "SEC EDGAR, XBRL companyfacts (10-Q/10-K)",
                "data_ultimo_balanco": "30/09/2026"}

    r = df.obter("MU", dt.date(2026, 11, 22), 200.0, buscar_br=busca_br, buscar_eua=busca_eua, verificar_novo=False)
    assert chamou == {"br": False, "eua": True}
    assert r["status"] == "ok" and r["moeda_resultado"] == "USD"


# ------------------------------------------------------------ item 3: balanço novo detectado, sem sobrescrever sozinho
def test_balanco_novo_detectado_mas_nao_sobrescreve(tmp_path, monkeypatch):
    arq = tmp_path / "dados_fixos.json"
    arq.write_text(json.dumps({"PETR4": PETR4}), encoding="utf-8")
    monkeypatch.setattr(df, "ARQ", arq)

    r = df.obter("PETR4", dt.date(2026, 11, 22), 42.67,
                 buscar_data_mais_recente=lambda: "31/12/2026")
    assert r["avisoBalancoNovo"] == "Balanço novo detectado, atualizar dados fixos de PETR4?"
    assert r["acoes_total"] == PETR4["acoes_total"]     # não sobrescreveu
    assert json.loads(arq.read_text(encoding="utf-8"))["PETR4"] == PETR4   # arquivo intacto


def test_sem_balanco_novo_nenhum_aviso(tmp_path, monkeypatch):
    arq = tmp_path / "dados_fixos.json"
    arq.write_text(json.dumps({"PETR4": PETR4}), encoding="utf-8")
    monkeypatch.setattr(df, "ARQ", arq)

    r = df.obter("PETR4", dt.date(2026, 11, 22), 42.67,
                 buscar_data_mais_recente=lambda: "30/09/2026")
    assert r["avisoBalancoNovo"] is None


# ------------------------------------------------------------ extração de ações (BR): ON + PN + Units, nunca só ON
def test_extrair_acoes_br_soma_on_e_pn():
    texto = "Ações Ordinárias (ON) .......... 5.708.922.664\nAções Preferenciais (PN) .......... 1.000.000.000"
    total, detalhe = df.extrair_acoes_br(texto)
    assert total == 6_708_922_664 and "ON" in detalhe and "PN" in detalhe


def test_extrair_acoes_br_sem_nenhuma_classe():
    assert df.extrair_acoes_br("nada de ações aqui") == (None, "")


def test_eh_br():
    assert df.eh_br("PETR4") and df.eh_br("petr4.sa") and df.eh_br("BBAS3")
    assert not df.eh_br("AAPL") and not df.eh_br("MU")
