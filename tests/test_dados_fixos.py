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


# ------------------------------------------------------------ Issue #31: dividendo/JCP por ação (BR)
# (a) tabela do release/relatório de resultados (ex. BBAS3, "Relatório de Análise Gerencial")
TABELA_BBAS3 = ("R$ milhões, exceto quando indicado 3T25 2T26 3T26 Δ% A/A Δ% T/T  9M25 9M26  Δ% Acm.\n"
               "Lucro Líquido Ajustado 3.785 3.908 1.270 (66,5) (67,5)  14.943 8.608  (42,4)\n"
               "JCP/Dividendos por Ação – R$ 0,07 0,16 0,04 (51,4) (78,4) 0,65 0,35 (45,9)\n")


def test_extrair_dividendo_tabela_acha_a_coluna_do_trimestre():
    assert df.extrair_dividendo_tabela(TABELA_BBAS3, "3T26") == pytest.approx(0.04)
    assert df.extrair_dividendo_tabela(TABELA_BBAS3, "2T26") == pytest.approx(0.16)
    assert df.extrair_dividendo_tabela(TABELA_BBAS3, "3T25") == pytest.approx(0.07)


def test_extrair_dividendo_tabela_sem_a_linha():
    assert df.extrair_dividendo_tabela("nada de dividendo aqui", "3T26") is None


def test_extrair_dividendo_tabela_sem_o_trimestre_no_cabecalho():
    assert df.extrair_dividendo_tabela(TABELA_BBAS3, "1T26") is None


# (b) Fato Relevante/Aviso aos Acionistas (ex. PETR4, "Petrobras informa sobre remuneração aos acionistas")
FATO_PETR4_TRIMESTRE = (
    "A Petróleo Brasileiro S.A. informa que o Conselho de Administração aprovou o pagamento de "
    "remuneração aos acionistas no valor de R$ 15,3 bilhões, equivalente a R$ 1,18732774 por ação "
    "ordinária e preferencial em circulação, como antecipação da remuneração relativa ao exercício "
    "de 2026, declarada com base no balanço de 30 de setembro de 2026.\n\n"
    "Valor a ser pago: R$ 1,18732774 por ação ordinária e preferencial em circulação, sendo que:")
FATO_PETR4_ANUAL = (
    "A Petróleo Brasileiro S.A. informa que o Conselho de Administração autorizou o encaminhamento "
    "à Assembleia Geral Ordinária da proposta de distribuição de remuneração aos acionistas no "
    "montante de R$ 8,1 bilhões relativa ao quarto trimestre de 2025.\n\n"
    "Valor a ser pago: R$ 0,62622908 por ação ordinária e preferencial em circulação, sendo que:")


def test_extrair_dividendo_fato_relevante_pelo_balanco():
    assert df.extrair_dividendo_fato_relevante(FATO_PETR4_TRIMESTRE) == (pytest.approx(1.18732774), "3T26")


def test_extrair_dividendo_fato_relevante_pelo_trimestre_ordinal():
    assert df.extrair_dividendo_fato_relevante(FATO_PETR4_ANUAL) == (pytest.approx(0.62622908), "4T25")


def test_extrair_dividendo_fato_relevante_sem_valor_por_acao():
    assert df.extrair_dividendo_fato_relevante("nenhuma remuneração aqui") is None


# buscar_fixos_br: dividendo_12m preenchido / "Sem dado", sem rede de verdade
def _doc(data, categoria="Dados Econômico-Financeiros", tipo="Press-release", assunto="Relatório de Desempenho",
        link=None):
    return {"data": data, "categoria": categoria, "tipo": tipo, "assunto": assunto,
           "link": link or f"https://cvm/{data}"}


CAPA_ACOES = "Ações Ordinárias (ON) .......... 5.000.000.000\nAções Preferenciais (PN) .......... 1.000.000.000"


def test_buscar_fixos_br_petr4_estilo_fato_relevante_preenche_dividendo():
    """PETR4: a tabela do release não tem dividendo por ação (abordagem a) - cai para o Fato
    Relevante/Aviso aos Acionistas (abordagem b), um documento por trimestre."""
    docs_resultado = [_doc("2026-11-10"), _doc("2026-08-06"), _doc("2026-05-11"), _doc("2026-02-12")]
    docs_dividendo = [
        _doc("2026-11-10", "Fato Relevante", "", "Petrobras informa sobre remuneração aos acionistas",
            link="https://cvm/div/2026-11-10"),
        _doc("2026-08-06", "Fato Relevante", "", "Petrobras informa sobre remuneração aos acionistas",
            link="https://cvm/div/2026-08-06"),
        _doc("2026-05-11", "Fato Relevante", "", "Petrobras informa sobre remuneração aos acionistas",
            link="https://cvm/div/2026-05-11"),
        _doc("2026-03-05", "Fato Relevante", "", "Petrobras informa sobre remuneração aos acionistas",
            link="https://cvm/div/2026-03-05"),
    ]
    textos_resultado = {
        "2026-11-10": f"{CAPA_ACOES}\nNo 3T26, o lucro líquido foi de R$ 39,75 bilhões.",
        "2026-08-06": "No 2T26, o lucro líquido foi de R$ 52,45 bilhões.",
        "2026-05-11": "No 1T26, o lucro líquido foi de R$ 32,71 bilhões.",
        "2026-02-12": "No 4T25, o lucro líquido foi de R$ 28,00 bilhões.",
    }
    textos_dividendo = {
        "2026-11-10": "declarada com base no balanço de 30 de setembro de 2026. "
                     "Valor a ser pago: R$ 1,18732774 por ação ordinária e preferencial em circulação.",
        "2026-08-06": "declarada com base no balanço de 30 de junho de 2026. "
                     "Valor a ser pago: R$ 1,34814262 por ação ordinária e preferencial em circulação.",
        "2026-05-11": "declarada com base no balanço de 31 de março de 2026. "
                     "Valor a ser pago: R$ 0,70097272 por ação ordinária e preferencial em circulação.",
        "2026-03-05": "relativa ao quarto trimestre de 2025. "
                     "Valor a ser pago: R$ 0,62622908 por ação ordinária e preferencial em circulação.",
    }

    def busca_cnpj(ticker, hoje):
        return ("33.000.167/0001-01", "PETROBRAS")

    def busca_docs(cnpj, hoje):
        return docs_resultado

    def busca_docs_dividendo(cnpj, hoje):
        return docs_dividendo

    def ler_pdf(link):
        data = link.rsplit("/", 1)[1]
        texto = textos_dividendo[data] if "/div/" in link else textos_resultado[data]
        return b"", texto

    r = df.buscar_fixos_br("PETR4", dt.date(2026, 11, 22), buscar_cnpj=busca_cnpj, buscar_docs=busca_docs,
                          ler_pdf=ler_pdf, buscar_docs_dividendo=busca_docs_dividendo)
    assert r["status"] == "ok"
    esperado = 1.18732774 + 1.34814262 + 0.70097272 + 0.62622908
    assert r["dividendo_12m"] == pytest.approx(esperado)
    assert r["dividendo_motivo"] is None
    assert "Fato Relevante" in r["fonte_oficial"]
    ind = df.calcular_indicadores(r, 42.67)
    assert ind["dy"] == pytest.approx(esperado / 42.67)


def test_buscar_fixos_br_bbas3_estilo_tabela_preenche_dividendo():
    """BBAS3: a própria tabela de destaques do relatório já traz a linha "JCP/Dividendos por Ação",
    com os 3 últimos trimestres - um único documento cobre todos eles."""
    docs_resultado = [_doc("2026-11-13", tipo="Relatório de Análise Gerencial", assunto="Análise do Desempenho 3T26"),
                     _doc("2026-08-17", tipo="Relatório de Análise Gerencial", assunto="Análise do Desempenho 2T26"),
                     _doc("2026-05-13", tipo="Relatório de Análise Gerencial", assunto="Análise do Desempenho 1T26"),
                     _doc("2026-02-24", tipo="Relatório de Análise Gerencial", assunto="Análise do Desempenho 4T25")]
    textos = {
        "2026-11-13": (f"{CAPA_ACOES}\n"
                       "R$ milhões, exceto quando indicado 3T25 2T26 3T26 Δ% A/A Δ% T/T  9M25 9M26  Δ% Acm.\n"
                       "Lucro Líquido 3.028 3.175 1.216 (59,9) (61,7) 12.836 7.480 (41,7)\n"
                       "JCP/Dividendos por Ação – R$ 0,07 0,16 0,04 (51,4) (78,4) 0,65 0,35 (45,9)\n"),
        "2026-08-17": ("R$ milhões, exceto quando indicado 3T25 1T26 2T26 Δ% A/A Δ% T/T  6M25 6M26  Δ% Acm.\n"
                      "Lucro Líquido 3.028 3.100 3.175 1,0 2,4 6.000 6.275 4,6\n"
                      "JCP/Dividendos por Ação – R$ 0,07 0,15 0,16 128,6 6,7 0,20 0,31 55,0\n"),
        "2026-05-13": ("R$ milhões, exceto quando indicado 4T25 1T25 1T26 Δ% A/A Δ% T/T\n"
                      "Lucro Líquido 2.900 2.800 3.100 10,7 6,9\n"
                      "JCP/Dividendos por Ação – R$ 0,10 0,05 0,15 200,0 50,0\n"),
        "2026-02-24": ("R$ milhões, exceto quando indicado 3T25 4T24 4T25 Δ% A/A Δ% T/T\n"
                      "Lucro Líquido 3.028 2.700 2.900 -4,2 7,4\n"
                      "JCP/Dividendos por Ação – R$ 0,07 0,08 0,10 25,0 25,0\n"),
    }

    def busca_cnpj(ticker, hoje):
        return ("00.000.000/0001-91", "BCO BRASIL S.A.")

    def busca_docs(cnpj, hoje):
        return docs_resultado

    def busca_docs_dividendo(cnpj, hoje):
        return []  # não deveria precisar: a própria tabela já tem os 4 trimestres

    def ler_pdf(link):
        data = link.rsplit("/", 1)[1]
        return b"", textos[data]

    r = df.buscar_fixos_br("BBAS3", dt.date(2026, 11, 22), buscar_cnpj=busca_cnpj, buscar_docs=busca_docs,
                          ler_pdf=ler_pdf, buscar_docs_dividendo=busca_docs_dividendo)
    assert r["status"] == "ok"
    assert r["dividendo_12m"] == pytest.approx(0.04 + 0.16 + 0.15 + 0.10)
    assert r["dividendo_motivo"] is None
    assert "Fato Relevante" not in r["fonte_oficial"]       # achou tudo na tabela, sem precisar do 2º passo
    ind = df.calcular_indicadores(r, 23.07)
    assert ind["dy"] == pytest.approx((0.04 + 0.16 + 0.15 + 0.10) / 23.07)


def test_buscar_fixos_br_sem_dividendo_em_nenhum_documento_fica_sem_dado():
    """Ticker sem dividendo nos documentos lidos: dividendo_12m fica None ("Sem dado"), nunca
    inventado - o lucro/ações continuam calculados normalmente."""
    docs_resultado = [_doc("2026-11-10"), _doc("2026-08-06"), _doc("2026-05-11"), _doc("2026-02-12")]
    textos = {
        "2026-11-10": f"{CAPA_ACOES}\nNo 3T26, o lucro líquido foi de R$ 39,75 bilhões.",
        "2026-08-06": "No 2T26, o lucro líquido foi de R$ 52,45 bilhões.",
        "2026-05-11": "No 1T26, o lucro líquido foi de R$ 32,71 bilhões.",
        "2026-02-12": "No 4T25, o lucro líquido foi de R$ 28,00 bilhões.",
    }

    def busca_cnpj(ticker, hoje):
        return ("33.000.167/0001-01", "PETROBRAS")

    def busca_docs(cnpj, hoje):
        return docs_resultado

    def busca_docs_dividendo(cnpj, hoje):
        return []  # nenhum Fato Relevante de dividendo disponível

    def ler_pdf(link):
        return b"", textos[link.rsplit("/", 1)[1]]

    r = df.buscar_fixos_br("PETR4", dt.date(2026, 11, 22), buscar_cnpj=busca_cnpj, buscar_docs=busca_docs,
                          ler_pdf=ler_pdf, buscar_docs_dividendo=busca_docs_dividendo)
    assert r["status"] == "ok"
    assert r["dividendo_12m"] is None
    assert r["dividendo_motivo"] and "não encontrado" in r["dividendo_motivo"]
    ind = df.calcular_indicadores(r, 42.67)
    assert ind["dy"] is None and ind["contas"]["dy"] == "DY: Sem dado"
    assert r["lucro_12m"] == pytest.approx(39.75e9 + 52.45e9 + 32.71e9 + 28.00e9)  # lucro continua normal
