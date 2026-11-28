import datetime as dt
import json

import pytest

from utils import dados_fixos as df

PETR4 = {"acoes_total": 12.89e9, "lucro_12m": 140.4e9, "dividendo_12m": None, "fator_adr": 1,
         "moeda_resultado": "BRL", "fonte_oficial": "PDF RI (CVM/IPE)", "data_ultimo_balanco": "30/09/2026"}
BBAS3 = {"acoes_total": 5.71e9, "lucro_12m": 12.45e9, "dividendo_12m": None, "fator_adr": 1,
         "moeda_resultado": "BRL", "fonte_oficial": "PDF RI (CVM/IPE)", "data_ultimo_balanco": "30/09/2026"}

# ------------------------------------------------------------ Issue #35: dados reais (CVM), buscados em 26/11/2026
# PETR4 - "Relatório de Desempenho 3T26" (Dados Econômico-Financeiros/Press-release, CVM/IPE,
# protocolo 1587565, entregue em 10/11/2026):
#   - acoes_total RECONFIRMADO ao vivo: "Ações Ordinárias (ON) ... 7.442.231.382" + "Ações
#     Preferenciais (PN) ... 5.446.501.379" = 12.888.732.761 (bate com a fixture PETR4 acima,
#     12,89 bi, a menos de 0,01%: mantemos 12,89e9 por consistência com os testes já existentes).
#   - patrimonio_liquido NOVO (Issue #35): Balanço Patrimonial do mesmo documento, "PASSIVO - R$
#     milhões 30.09.2026 31.12.2025 ... Patrimônio Líquido 505.631 417.587" -> R$ 505,631 bilhões
#     (coluna de 30/09/2026, a mais recente - 31/12/2025 é só o comparativo).
#   - lucro_12m: 3 dos 4 trimestres RECONFIRMADOS ao vivo nos releases trimestrais (3T26 R$ 47,90
#     bi, 2T26 R$ 52,495 bi, 1T26 R$ 32,761 bi = R$ 133,156 bi); o release do 4T25 (05/03/2026) usa
#     um formato que a extração de texto de `ler_lucro_trimestre` não reconhece nesta tentativa
#     (limitação pré-existente, não introduzida por esta issue) - mantemos o valor de 4T25 implícito
#     na fixture já usada pelas Issues #29/#31 (140,4 − 133,156 = R$ 7,244 bi), e documentamos a
#     limitação no PR.
#   - dividendo_12m: mesmos 4 trimestres (balanço de 30/09/2026) já confirmados na Issue #31
#     (PR #32, via Fato Relevante por trimestre): 1,18732774 + 1,34814262 + 0,70097272 + 0,62622908
#     = R$ 3,8627016/ação.
# BBAS3 - "Análise do Desempenho 3T26" (Relatório de Análise Gerencial, CVM/IPE, protocolo 1589018,
# entregue em 13/11/2026):
#   - acoes_total e lucro_12m CORRIGIDOS (27/11/2026, bug real achado comparando "Indicadores" com
#     "Dados fixos" na tela pro mesmo ticker): a 1ª tentativa desta issue leu "Ações Ordinárias (ON)
#     ... 2.842.623.097" e achou que BBAS3 tinha feito um grupamento de ações - ERRADO. Esse número
#     é só o FREE FLOAT (49,6% do total, linha "Ações em circulação (free float)" das Demonstrações
#     Contábeis) - o TOTAL emitido continua R$ 5.708.922.664/5.730.834.040 ("Número médio ponderado
#     de ações" e "Total emitido" no mesmo documento), igual à fixture antiga (5,71 bi). Do mesmo
#     jeito, lucro_12m usava a linha genérica "Lucro Líquido" em vez de "Lucro Líquido Contábil"
#     (a linha certa, configurada em contabil_br_config.json) e bateu errado no 4T25 (R$ 1,079 bi em
#     vez de R$ 4,972 bi) - `buscar_fixos_br` agora REUSA utils/contabil_br.json pra ações e lucro
#     quando o ticker está configurado lá, em vez de reimplementar essa extração (ver
#     `_contabil_br_configurado`, CLAUDE.md). lucro_12m real: 4T25 R$ 4,972 bi + 1T26 R$ 3,090 bi +
#     2T26 R$ 3,175 bi + 3T26 R$ 1,216 bi = R$ 12,453 bi (bate com utils/contabil_br.json).
#   - dividendo_12m (linha "JCP/Dividendos por Ação", já por ação, não afetada pelos 2 bugs acima):
#     0,26 + 0,15 + 0,16 + 0,04 = R$ 0,61 por ação.
#   - patrimonio_liquido (Issue #35, também não afetado): mesma tabela de destaques, linha
#     "Patrimônio Líquido" coluna 3T26 = R$ 190,121 bilhões; confirmado também na Nota 23 das
#     Demonstrações Contábeis do mesmo documento, "Patrimônio líquido consolidado 190.121.308" (em
#     milhares de reais).
#   - cotação de teste (23,07): tirada do próprio documento, "Valor de mercado por ação (R$) 23,07".
PETR4_REAL = {**PETR4, "dividendo_12m": 3.8627016, "patrimonio_liquido": 505.631e9}
BBAS3_REAL = {"acoes_total": 5_708_922_664.0, "lucro_12m": 12_453_000_000.0, "dividendo_12m": 0.61,
              "patrimonio_liquido": 190.121e9, "fator_adr": 1, "moeda_resultado": "BRL",
              "fonte_oficial": "PDF RI (CVM/IPE)", "data_ultimo_balanco": "30/09/2026"}


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


# ------------------------------------------------------------ Issue #35: P/VP, Payout, ROE (fórmulas)
# PETR4_REAL e BBAS3_REAL: todos os campos confirmados em documentos reais da CVM (ver comentário
# acima, com a fonte exata de cada número). Valores esperados calculados à parte (não hardcoded
# "no olho") - ver cálculo em utils/dados_fixos.py e no corpo do PR.
def test_petr4_pvp_payout_roe_batem_com_o_balanco_real():
    ind = df.calcular_indicadores(PETR4_REAL, 42.67)
    assert ind["vpa"] == pytest.approx(39.2266, abs=0.001)          # 505,631 bi / 12,89 bi ações
    assert ind["pvp"] == pytest.approx(1.0878, abs=0.001)           # 42,67 / 39,2266
    assert ind["roe"] == pytest.approx(0.27767, abs=0.0001)         # 140,4 bi / 505,631 bi = 27,8%
    assert ind["payout"] == pytest.approx(0.35463, abs=0.0001)      # 3,8627 / LPA 10,8922 = 35,5%


def test_bbas3_pvp_payout_roe_batem_com_o_balanco_real():
    ind = df.calcular_indicadores(BBAS3_REAL, 23.07)                # cotação do próprio documento
    assert ind["vpa"] == pytest.approx(33.3024, abs=0.001)          # 190,121 bi / 5,708922664 bi ações
    assert ind["pvp"] == pytest.approx(0.69274, abs=0.0001)         # 23,07 / 33,3024
    assert ind["roe"] == pytest.approx(0.065500, abs=0.0001)        # 12,453 bi / 190,121 bi = 6,55%
    assert ind["payout"] == pytest.approx(0.279647, abs=0.0001)     # 0,61 / LPA 2,1813 = 28,0%


def test_roe_e_igual_seja_pelo_total_ou_pelo_lpa_vpa():
    """ROE = lucro_12m / patrimonio_liquido é equivalente a LPA / VPA (os dois ÷ acoes_total se
    cancelam) - confere que a conta fixa bate com essa identidade, não só com um valor isolado."""
    ind = df.calcular_indicadores(PETR4_REAL, 42.67)
    assert ind["roe"] == pytest.approx(ind["lpa"] / ind["vpa"])


def test_sem_patrimonio_liquido_pvp_e_roe_ficam_sem_dado():
    fixos = {**PETR4, "patrimonio_liquido": None}
    ind = df.calcular_indicadores(fixos, 42.67)
    assert ind["pvp"] is None and ind["roe"] is None and ind["vpa"] is None
    assert ind["contas"]["pvp"] == "P/VP: Sem dado" and ind["contas"]["roe"] == "ROE: Sem dado"


def test_sem_dividendo_payout_fica_sem_dado_mas_pvp_e_roe_continuam():
    fixos = {**PETR4_REAL, "dividendo_12m": None}
    ind = df.calcular_indicadores(fixos, 42.67)
    assert ind["payout"] is None and ind["contas"]["payout"] == "Payout: Sem dado"
    assert ind["pvp"] is not None and ind["roe"] is not None


def test_contas_pvp_payout_roe_mostram_a_formula_embaixo():
    ind = df.calcular_indicadores(PETR4_REAL, 42.67)
    assert "505,63" in ind["contas"]["pvp"] and "12,89" in ind["contas"]["pvp"] and "42,67" in ind["contas"]["pvp"]
    assert "35,5%" in ind["contas"]["payout"]
    assert "27,8%" in ind["contas"]["roe"] and "505,63" in ind["contas"]["roe"]


# ------------------------------------------------------------ Issue #35: extração do patrimônio líquido (BR)
# Dois formatos reais vistos nos documentos da CVM (ver PETR4_REAL/BBAS3_REAL acima para a fonte exata):
# (a) tabela de destaques por trimestre (3T25 2T26 3T26 ...), igual à técnica já usada para o lucro;
# (b) Balanço Patrimonial com 2 colunas de DATA (mais recente primeiro), unidade no cabeçalho.
TABELA_PL_BBAS3 = ("des conforme indicado 3T25 2T26 3T26 Δ% A/A Δ% T/T 9M25 9M26 Δ% Acm.\n"
                  "Patrimônio Líquido 186.587 189.211 190.121 1,9 0,5 185.123 188.456 1,8\n")
BALANCO_PL_PETR4 = ("PASSIVO - R$ milhões 30.09.2026 31.12.2025 Circulante 202.387 198.368 "
                    "Não Circulante 618.449 607.434 Patrimônio Líquido 505.631 417.587 "
                    "Atribuível aos acionistas da Petrobras 504.698 415.786\n")


def test_extrair_patrimonio_liquido_br_tabela_por_trimestre():
    assert df.extrair_patrimonio_liquido_br(TABELA_PL_BBAS3, "3T26")[0] == pytest.approx(190.121e9)
    assert df.extrair_patrimonio_liquido_br(TABELA_PL_BBAS3, "2T26")[0] == pytest.approx(189.211e9)


def test_extrair_patrimonio_liquido_br_balanco_por_data():
    valor, fonte = df.extrair_patrimonio_liquido_br(BALANCO_PL_PETR4, "3T26")
    assert valor == pytest.approx(505.631e9)
    assert "30.09.2026" in fonte


def test_extrair_patrimonio_liquido_br_ignora_retorno_sobre_patrimonio():
    """"Retorno sobre Patrimônio Líquido" (RSPL/ROE) não é o patrimônio líquido em si - não deve
    ser lido como se fosse o valor do balanço."""
    texto = ("des conforme indicado 3T25 2T26 3T26\n"
            "Retorno sobre Patrimônio Líquido (RSPL) 8,4% 8,3% 2,8%\n"
            "Patrimônio Líquido 186.587 189.211 190.121 1,9 0,5\n")
    assert df.extrair_patrimonio_liquido_br(texto, "3T26")[0] == pytest.approx(190.121e9)


def test_extrair_patrimonio_liquido_br_sem_achar():
    assert df.extrair_patrimonio_liquido_br("nada de patrimônio aqui", "3T26") == (None, "")


# ------------------------------------------------------------ Issue #35: patrimonio_liquido no retorno de buscar_fixos_br
def test_buscar_fixos_br_grava_patrimonio_liquido_do_balanco_mais_recente():
    docs_resultado = [_doc("2026-11-10"), _doc("2026-08-06"), _doc("2026-05-11"), _doc("2026-02-12")]
    textos = {
        "2026-11-10": f"{CAPA_ACOES}\nNo 3T26, o lucro líquido foi de R$ 39,75 bilhões.\n{BALANCO_PL_PETR4}",
        "2026-08-06": "No 2T26, o lucro líquido foi de R$ 52,45 bilhões.",
        "2026-05-11": "No 1T26, o lucro líquido foi de R$ 32,71 bilhões.",
        "2026-02-12": "No 4T25, o lucro líquido foi de R$ 28,00 bilhões.",
    }

    def busca_cnpj(ticker, hoje):
        return ("33.000.167/0001-01", "PETROBRAS")

    def busca_docs(cnpj, hoje):
        return docs_resultado

    def busca_docs_dividendo(cnpj, hoje):
        return []

    def ler_pdf(link):
        return b"", textos[link.rsplit("/", 1)[1]]

    r = df.buscar_fixos_br("PETR4", dt.date(2026, 11, 22), buscar_cnpj=busca_cnpj, buscar_docs=busca_docs,
                          ler_pdf=ler_pdf, buscar_docs_dividendo=busca_docs_dividendo, contabil_cfg={})
    assert r["status"] == "ok"
    assert r["patrimonio_liquido"] == pytest.approx(505.631e9)
    assert r["patrimonio_motivo"] is None
    assert "patrimônio líquido" in r["fonte_oficial"]


def test_buscar_fixos_br_patrimonio_trimestres_junta_os_4_quando_cada_release_tem_o_seu():
    """Item 11 (28/11/2026): cada release trimestral normalmente reporta o PRÓPRIO balanço do seu
    trimestre - se os 4 releases (um por trimestre) tiverem essa tabela, patrimonio_trimestres junta
    os 4, não só o mais recente (continua em patrimonio_liquido, sem mudar o Issue #35)."""
    docs_resultado = [_doc("2026-11-10"), _doc("2026-08-06"), _doc("2026-05-11"), _doc("2026-02-12")]
    textos = {
        "2026-11-10": f"{CAPA_ACOES}\nNo 3T26, o lucro líquido foi de R$ 39,75 bilhões.\n"
                      "PASSIVO - R$ milhões 30.09.2026 30.06.2026 Patrimônio Líquido 505.631 480.000\n",
        "2026-08-06": "No 2T26, o lucro líquido foi de R$ 52,45 bilhões.\n"
                      "PASSIVO - R$ milhões 30.06.2026 31.03.2026 Patrimônio Líquido 480.000 460.000\n",
        "2026-05-11": "No 1T26, o lucro líquido foi de R$ 32,71 bilhões.\n"
                      "PASSIVO - R$ milhões 31.03.2026 31.12.2025 Patrimônio Líquido 460.000 417.587\n",
        "2026-02-12": "No 4T25, o lucro líquido foi de R$ 28,00 bilhões.\n"
                      "PASSIVO - R$ milhões 31.12.2025 30.09.2025 Patrimônio Líquido 417.587 400.000\n",
    }

    def busca_cnpj(ticker, hoje):
        return ("33.000.167/0001-01", "PETROBRAS")

    def busca_docs(cnpj, hoje):
        return docs_resultado

    def busca_docs_dividendo(cnpj, hoje):
        return []

    def ler_pdf(link):
        return b"", textos[link.rsplit("/", 1)[1]]

    r = df.buscar_fixos_br("PETR4", dt.date(2026, 11, 22), buscar_cnpj=busca_cnpj, buscar_docs=busca_docs,
                          ler_pdf=ler_pdf, buscar_docs_dividendo=busca_docs_dividendo, contabil_cfg={})
    assert r["status"] == "ok"
    assert r["patrimonio_liquido"] == pytest.approx(505.631e9)  # Issue #35 continua igual
    assert [p["trimestre"] for p in r["patrimonio_trimestres"]] == ["4T25", "1T26", "2T26", "3T26"]
    assert [p["valor"] for p in r["patrimonio_trimestres"]] == pytest.approx(
        [417.587e9, 460.0e9, 480.0e9, 505.631e9])


def test_buscar_fixos_br_sem_patrimonio_em_nenhum_documento_fica_sem_dado():
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
        return []

    def ler_pdf(link):
        return b"", textos[link.rsplit("/", 1)[1]]

    r = df.buscar_fixos_br("PETR4", dt.date(2026, 11, 22), buscar_cnpj=busca_cnpj, buscar_docs=busca_docs,
                          ler_pdf=ler_pdf, buscar_docs_dividendo=busca_docs_dividendo, contabil_cfg={})
    assert r["status"] == "ok"
    assert r["patrimonio_liquido"] is None
    assert r["patrimonio_motivo"] and "não encontrado" in r["patrimonio_motivo"]
    assert r["lucro_12m"] == pytest.approx(39.75e9 + 52.45e9 + 32.71e9 + 28.00e9)  # lucro continua normal


# ------------------------------------------------------------ Issue #35: patrimônio líquido (EUA, SEC)
def _fato_instante(fim, val, filed="2026-11-01"):
    return {"end": fim, "val": val, "filed": filed}


def test_patrimonio_sec_usa_stockholders_equity():
    fatos = {"facts": {"us-gaap": {"StockholdersEquity": {"units": {"USD": [
        _fato_instante("2026-06-30", 90e9), _fato_instante("2026-09-30", 100e9),
    ]}}}}}
    valor, tag = df._patrimonio_sec(fatos, dt.date(2026, 9, 30))
    assert valor == pytest.approx(100e9) and tag == "StockholdersEquity"


def test_patrimonio_sec_cai_para_tag_com_nao_controladores():
    fatos = {"facts": {"us-gaap": {"StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest":
        {"units": {"USD": [_fato_instante("2026-09-30", 105e9)]}}}}}
    valor, tag = df._patrimonio_sec(fatos, dt.date(2026, 9, 30))
    assert valor == pytest.approx(105e9)
    assert tag == "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"


def test_patrimonio_sec_sem_dado_na_data():
    fatos = {"facts": {"us-gaap": {"StockholdersEquity": {"units": {"USD": [
        _fato_instante("2026-06-30", 90e9),
    ]}}}}}
    assert df._patrimonio_sec(fatos, dt.date(2026, 9, 30)) == (None, None)


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
                          ler_pdf=ler_pdf, buscar_docs_dividendo=busca_docs_dividendo, contabil_cfg={})
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
                          ler_pdf=ler_pdf, buscar_docs_dividendo=busca_docs_dividendo, contabil_cfg={})
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
                          ler_pdf=ler_pdf, buscar_docs_dividendo=busca_docs_dividendo, contabil_cfg={})
    assert r["status"] == "ok"
    assert r["dividendo_12m"] is None
    assert r["dividendo_motivo"] and "não encontrado" in r["dividendo_motivo"]
    ind = df.calcular_indicadores(r, 42.67)
    assert ind["dy"] is None and ind["contas"]["dy"] == "DY: Sem dado"
    assert r["lucro_12m"] == pytest.approx(39.75e9 + 52.45e9 + 32.71e9 + 28.00e9)  # lucro continua normal


# ------------------------------------------------------------ bug real corrigido (27/11/2026): ações = free
# float em vez do total emitido, e lucro = linha genérica em vez da linha específica do ticker. Achado
# comparando "Indicadores" (Yahoo/contabil_br.json) com "Dados fixos" (extração própria) pro BBAS3: Ações
# 2,84 bi (errado, free float) vs 5,71 bi (certo, total emitido); LPA 3,0113 (errado) vs 2,18 (certo).
def test_extrair_acoes_br_ignora_free_float_e_acha_o_total():
    texto = (
        "k) Movimentação de ações em circulação/free float\n"
        "Ações Ordinárias em circulação (free float) no fim do período 2.843.025.842\n"
        "...\n"
        "Composição do Capital Social\n"
        "Ações Ordinárias (ON) .......... 5.730.834.040\n"
    )
    total, detalhe = df.extrair_acoes_br(texto)
    assert total == 5_730_834_040 and "ON" in detalhe


def test_extrair_acoes_br_so_com_free_float_nao_acha_nada():
    # nenhuma ocorrência de "ordinárias" fora do contexto de free float/tesouraria -> não inventa
    # um total que não está no documento (nunca aceita o subconjunto como se fosse o total).
    texto = "Ações Ordinárias em circulação (free float) no fim do período 2.843.025.842"
    assert df.extrair_acoes_br(texto) == (None, "")


def test_extrair_acoes_br_ignora_tesouraria():
    texto = (
        "Ações Ordinárias em tesouraria 10.000.000\n"
        "Ações Ordinárias (ON) emitidas 5.730.834.040\n"
    )
    total, _ = df.extrair_acoes_br(texto)
    assert total == 5_730_834_040


# ------------------------------------------------------------ reuso de utils/contabil_br.json (27/11/2026)
CONTABIL_CFG_BBAS3 = {"BBAS3": {"linha": "Lucro Líquido Contábil", "linha_ajustado": "Lucro Líquido Ajustado",
                                "fonte": "BB, Análise do Desempenho, Lucro Líquido Contábil"}}
CONTABIL_TABELA_BBAS3_OK = {"BBAS3": {
    "status": "ok", "acoes": 5_708_922_664.0, "lucro_12m": 12_453_000_000.0, "lpa_12m": 2.1813,
    "fonte": "BB, Análise do Desempenho, Lucro Líquido Contábil",
    "trimestres": [
        {"tri": "4T25", "fim": "31/12/2025", "lucro": 4_972_000_000.0, "data": "24/02/2026", "url": "https://cvm/4t25"},
        {"tri": "1T26", "fim": "31/03/2026", "lucro": 3_090_000_000.0, "data": "13/05/2026", "url": "https://cvm/1t26"},
        {"tri": "2T26", "fim": "30/06/2026", "lucro": 3_175_000_000.0, "data": "17/08/2026", "url": "https://cvm/2t26"},
        {"tri": "3T26", "fim": "30/09/2026", "lucro": 1_216_000_000.0, "data": "13/11/2026", "url": "https://cvm/3t26"},
    ],
}}


def test_contabil_br_configurado_devolve_none_sem_config():
    assert df._contabil_br_configurado("BBAS3", tabela_cfg={}, tabela_contabil=CONTABIL_TABELA_BBAS3_OK) is None


def test_contabil_br_configurado_devolve_none_sem_status_ok():
    tabela = {"BBAS3": {"status": "yahoo_pendente"}}
    assert df._contabil_br_configurado("BBAS3", tabela_cfg=CONTABIL_CFG_BBAS3, tabela_contabil=tabela) is None


def test_contabil_br_configurado_devolve_o_registro_quando_ok():
    c = df._contabil_br_configurado("bbas3", tabela_cfg=CONTABIL_CFG_BBAS3, tabela_contabil=CONTABIL_TABELA_BBAS3_OK)
    assert c is not None and c["acoes"] == 5_708_922_664.0


def test_buscar_fixos_br_reusa_contabil_br_json_pra_acoes_e_lucro():
    """BBAS3 configurado e com contabil_br.json "ok": ações e lucro vêm de lá (5,71 bi / 12,45 bi,
    LPA 2,18), nunca da extração própria (que bateria 2,84 bi / 8,56 bi, LPA 3,0113 - o bug real).
    Só dividendo (tabela do release, mesmo formato de TABELA_BBAS3) e patrimônio líquido (mesmo
    formato de TABELA_PL_BBAS3) continuam extraídos aqui, já que contabil_br.json não guarda esses
    2 campos - 1 único documento (3T26) já traz os 2."""
    texto_3t26 = f"{TABELA_BBAS3}{TABELA_PL_BBAS3}"

    def busca_cnpj(ticker, hoje):
        return ("00.000.000/0001-91", "BCO BRASIL S.A.")

    def busca_docs(cnpj, hoje):
        return [_doc("2026-11-13", link="https://cvm/3t26")]

    def busca_docs_dividendo(cnpj, hoje):
        return []

    def ler_pdf(link):
        return b"", texto_3t26

    r = df.buscar_fixos_br("BBAS3", dt.date(2026, 11, 22), buscar_cnpj=busca_cnpj, buscar_docs=busca_docs,
                          ler_pdf=ler_pdf, buscar_docs_dividendo=busca_docs_dividendo,
                          contabil_cfg=CONTABIL_CFG_BBAS3, contabil_tabela=CONTABIL_TABELA_BBAS3_OK)
    assert r["status"] == "ok"
    assert r["acoes_total"] == 5_708_922_664.0
    assert r["lucro_12m"] == pytest.approx(12_453_000_000.0)
    # só o 3T26 foi passado (1 único documento) - dividendo precisa dos 4 trimestres, fica sem
    # dado (nunca inventa os outros 3); patrimônio só precisa do MAIS RECENTE (3T26), que já veio.
    assert r["dividendo_12m"] is None
    assert r["patrimonio_liquido"] == pytest.approx(190.121e9)
    assert "contabil_br.json" in r["fonte_oficial"]
    ind = df.calcular_indicadores(r, 17.80)
    assert ind["lpa"] == pytest.approx(2.1813, abs=0.001)


def test_buscar_fixos_br_sem_contabil_configurado_usa_extracao_propria_como_antes():
    """Ticker fora de contabil_br_config.json (ou ainda sem contabil_br.json "ok"): continua
    extraindo ações/lucro sozinho - comportamento inalterado pra quem não está configurado."""
    docs_resultado = [_doc("2026-11-10"), _doc("2026-08-06"), _doc("2026-05-11"), _doc("2026-02-12")]
    textos = {
        "2026-11-10": f"{CAPA_ACOES}\nNo 3T26, o lucro líquido foi de R$ 39,75 bilhões.",
        "2026-08-06": "No 2T26, o lucro líquido foi de R$ 52,45 bilhões.",
        "2026-05-11": "No 1T26, o lucro líquido foi de R$ 32,71 bilhões.",
        "2026-02-12": "No 4T25, o lucro líquido foi de R$ 28,00 bilhões.",
    }

    def busca_cnpj(ticker, hoje):
        return ("11.111.111/0001-11", "TICKER NOVO")

    def busca_docs(cnpj, hoje):
        return docs_resultado

    def busca_docs_dividendo(cnpj, hoje):
        return []

    def ler_pdf(link):
        return b"", textos[link.rsplit("/", 1)[1]]

    r = df.buscar_fixos_br("ABCD4", dt.date(2026, 11, 22), buscar_cnpj=busca_cnpj, buscar_docs=busca_docs,
                          ler_pdf=ler_pdf, buscar_docs_dividendo=busca_docs_dividendo, contabil_cfg={})
    assert r["status"] == "ok"
    assert r["acoes_total"] == 6_000_000_000.0   # CAPA_ACOES: 5bi ON + 1bi PN
    assert r["lucro_12m"] == pytest.approx(39.75e9 + 52.45e9 + 32.71e9 + 28.00e9)
    assert "contabil_br.json" not in r["fonte_oficial"]


def test_buscar_fixos_br_fallback_usa_a_linha_configurada_nao_a_generica():
    """Ticker configurado em contabil_br_config.json (linha específica) mas AINDA sem
    contabil_br.json "ok" (robô não rodou ainda pra ele): a extração própria já usa a linha
    certa do config, não a genérica "Lucro Líquido" - reproduz o bug real do 4T25 da BBAS3, onde
    "Lucro Líquido" batia numa linha diferente (errada) de "Lucro Líquido Contábil" (certa)."""
    texto_4t25 = ("R$ milhões 3T25 4T25\n"
                 "Lucro Líquido de Serviços 950 1.079 (10,0)\n"   # linha genérica bateria aqui (errado)
                 "Lucro Líquido Contábil 4.500 4.972 (3,5)\n")    # linha do config bate aqui (certo)
    docs_resultado = [_doc("2026-02-24", link="https://cvm/4t25"), _doc("2026-05-13", link="https://cvm/1t26"),
                     _doc("2026-08-17", link="https://cvm/2t26"), _doc("2026-11-13", link="https://cvm/3t26")]
    textos = {
        "4t25": texto_4t25,
        "1t26": "R$ milhões 4T25 1T26\nLucro Líquido Contábil 4.972 3.090 (37,8)\n",
        "2t26": "R$ milhões 1T26 2T26\nLucro Líquido Contábil 3.090 3.175 2,7\n",
        "3t26": f"{CAPA_ACOES}\nR$ milhões 2T26 3T26\nLucro Líquido Contábil 3.175 1.216 (61,7)\n",
    }

    def busca_cnpj(ticker, hoje):
        return ("00.000.000/0001-91", "BCO BRASIL S.A.")

    def busca_docs(cnpj, hoje):
        return docs_resultado

    def busca_docs_dividendo(cnpj, hoje):
        return []

    def ler_pdf(link):
        return b"", textos[link.rsplit("/", 1)[1]]

    r = df.buscar_fixos_br("BBAS3", dt.date(2026, 11, 22), buscar_cnpj=busca_cnpj, buscar_docs=busca_docs,
                          ler_pdf=ler_pdf, buscar_docs_dividendo=busca_docs_dividendo,
                          contabil_cfg=CONTABIL_CFG_BBAS3, contabil_tabela={})
    assert r["status"] == "ok"
    assert r["lucro_12m"] == pytest.approx(4_972_000_000.0 + 3_090_000_000.0 + 3_175_000_000.0 + 1_216_000_000.0)
