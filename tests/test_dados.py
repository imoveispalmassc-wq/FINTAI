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
    assert "Faixa inferior até R$" in fx["5a"]["decisao"]["texto"]


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


def test_contabil_muda_quando_chega_balanco_novo():
    import pandas as pd
    from calculos import lpa_contabil_ttm
    lucro, anual, acoes, datas = _bb_contabil()
    antes = lpa_contabil_ttm(lucro, anual, acoes, 1.93, datas)
    # sai o balanço do 4T26 (lucro 0,30/ação): o 4T25 (0,92) sai da soma de 12 meses
    lucro2 = pd.concat([lucro, pd.Series({pd.Timestamp("2026-09-30"): 0.17 * acoes, pd.Timestamp("2026-12-31"): 0.30 * acoes})])
    datas2 = datas.append(pd.DatetimeIndex([pd.Timestamp("2027-02-10")]).tz_localize("America/Sao_Paulo"))
    depois = lpa_contabil_ttm(lucro2, anual, acoes, 1.31, datas2)
    assert round(antes.iloc[-1], 2) == 1.93 and round(depois.iloc[-1], 2) == 1.31
    assert f"{depois.index[-1]:%d/%m/%Y}" == "10/02/2027"


def test_contabil_volta_para_o_yahoo_se_a_sec_estiver_incompleta():
    from tela.dados import contabil_12m
    ok = {"ADM": {"status": "ok", "lpa_12m": 5.12, "fonte": "SEC 10-Q/10-K, lucro por ação diluído (GAAP)"}}
    assert contabil_12m("ADM", 5.10, ok)[:2] == (5.12, "SEC 10-Q/10-K, lucro por ação diluído (GAAP)")
    inc = {"ADM": {"status": "incompleto", "motivo": "só 3 trimestre(s) na SEC"}}
    assert contabil_12m("ADM", 5.10, inc)[:2] == (5.10, "Yahoo - SEC incompleto")
    assert contabil_12m("ADM", 5.10, {})[:2] == (5.10, "Yahoo - SEC ainda não lida pelo robô")
    assert contabil_12m("VALE3.SA", 6.1, ok)[:2] == (6.1, "Yahoo Finance")          # B3 fora da lista: Yahoo


def test_card_pl_na_ordem_inicio_contabil_previsao():
    # issue #47 (item 12): bloco único "Lucro e Preço vs Lucro" - a "Visão do ano" mantém a ordem
    # cronológica Início do ano -> Contábil 12 meses (TTM) -> Previsão atual.
    import pathlib
    js = pathlib.Path(__file__).resolve().parent.parent.joinpath("tela", "detalhe.js").read_text(encoding="utf-8")
    bloco = js[js.index("const linhasVisao"):js.index("const linhasMedias")]
    assert bloco.index("Início do ano") < bloco.index("Contábil 12 meses") < bloco.index("Previsão atual")
    assert "Lucro e Preço vs Lucro" in js



# ------------------------------------------------------------ contábil da B3 pelo release (BBAS3)
def test_bbas3_contabil_do_release_e_pendente_sem_documento():
    from tela.dados import contabil_12m
    br = {"BBAS3": {"status": "ok", "lpa_12m": 2.5015, "lucro_12m": 14.28e9, "acoes": 5.7089e9,
                    "fonte": "BB, Divulgação de Resultados, Lucro Líquido Ajustado"}}
    assert contabil_12m("BBAS3.SA", 1.93, {}, br)[:2] == (2.5015, "BB, Divulgação de Resultados, Lucro Líquido Ajustado")
    pend = {"BBAS3": {"status": "pendente", "motivo": "só 2 trimestre(s) lidos dos releases"}}
    lpa, fonte, _ = contabil_12m("BBAS3.SA", 1.93, {}, pend)
    assert lpa == 1.93 and fonte.startswith("Yahoo - pendente")              # não inventa número


def test_indicador_de_atualizacao_do_contabil_b3():
    import datetime as dt
    from tela.dados import atualizacao_contabil
    br = dt.timezone(dt.timedelta(hours=-3))
    c = {"status": "ok", "atualizado_em": "17/11 18:32", "trimestre_ref": "3T26", "trimestre_data": "set/26"}
    a = atualizacao_contabil(c, dt.datetime(2026, 11, 17, 19, 0, tzinfo=br))
    assert a == {"em": "17/11 18:32", "iso": "2026-11-17T18:32:00-03:00", "tri": "3T26", "triData": "set/26"}
    # gravado em dezembro e lido em janeiro: ano anterior
    c2 = {**c, "atualizado_em": "31/12 08:05"}
    assert atualizacao_contabil(c2, dt.datetime(2027, 1, 1, 9, 0, tzinfo=br))["iso"].startswith("2026-12-31")
    assert atualizacao_contabil({"status": "ok"}) is None and atualizacao_contabil(None) is None


def test_media_n_anos_so_calcula_com_anos_suficientes():
    from tela.dados import _media_n_anos
    pontos = [(2021, 1.0), (2022, 2.0), (2023, 3.0), (2024, 4.0)]   # só 4 anos (limite comum do Yahoo)
    assert _media_n_anos(pontos, 3) == pytest.approx(3.0)           # (2+3+4)/3
    assert _media_n_anos(pontos, 4) == pytest.approx(2.5)
    assert _media_n_anos(pontos, 5) is None                         # não tem 5 anos: nunca estende
    assert _media_n_anos(pontos, 10) is None
    assert _media_n_anos([], 3) is None


def test_decidir_estado_conservador_zonas_com_margem_de_30_por_cento():
    from utils.signals import decidir_estado_conservador
    teto = 100.0   # oportunidade até 70; neutra alargada até 130 (30% acima); cara daí pra cima
    assert decidir_estado_conservador(69.0, teto).codigo == "COMPRAR"
    assert decidir_estado_conservador(70.0, teto).codigo == "COMPRAR"
    assert decidir_estado_conservador(85.0, teto).codigo == "AGUARDAR"
    assert decidir_estado_conservador(100.0, teto).codigo == "AGUARDAR"
    assert decidir_estado_conservador(130.0, teto).codigo == "AGUARDAR"
    assert decidir_estado_conservador(130.01, teto).codigo == "CARO"
    e = decidir_estado_conservador(50.0, teto, simbolo="R$")
    assert "R$" in e.texto and "70" in e.texto
    assert decidir_estado_conservador(50.0, teto).validado is False   # nunca tem teste histórico


def test_decidir_estado_conservador_caro_acima_explicito_sobrescreve_padrao():
    from utils.signals import decidir_estado_conservador
    # caro_acima explícito (ex. vindo da Faixa, já calculado como teto × 1,30) vence o padrão
    assert decidir_estado_conservador(105.0, 100.0, 110.0).codigo == "AGUARDAR"
    assert decidir_estado_conservador(110.01, 100.0, 110.0).codigo == "CARO"


def test_decidir_estado_conservador_texto_mostra_sempre_o_alvo_de_30_por_cento():
    from utils.signals import decidir_estado_conservador
    e = decidir_estado_conservador(50.0, 100.0, simbolo="R$")
    assert "70" in e.texto

# ------------------------------------------------------------ Faixa de preço do Conservador (ponta a ponta)
def _faixa_conservador(media_1a, media_3a, media_5a, mm200, preco):
    """Simula o trecho de montar() que monta conservadorFaixa, sem precisar da rede."""
    from calculos import teto_valuation_conservador
    from utils.signals import decidir_estado_conservador
    teto_v = teto_valuation_conservador(media_1a, media_3a, media_5a)
    if teto_v["teto"] is None:
        return None
    caro_acima = teto_v["teto"] * 1.30
    oportunidade_ate = teto_v["teto"] * 0.70
    estado_c = decidir_estado_conservador(preco, teto_v["teto"], caro_acima, simbolo="R$")
    return {"ancora1a": teto_v["ancora1a"], "teto": teto_v["teto"], "oportunidadeAte": oportunidade_ate,
           "caroAcima": caro_acima,
           "limite3a": teto_v["limite3a"], "limite5a": teto_v["limite5a"], "mm200": mm200,
           "decisao": {"codigo": estado_c.codigo, "rotulo": estado_c.rotulo, "texto": estado_c.texto,
                      "zona": estado_c.zona, "validado": estado_c.validado, "alerta": estado_c.alerta}}


def test_faixa_conservador_ancora_1a_com_limites_3a_5a_como_referencia():
    fx = _faixa_conservador(100.0, 80.0, 60.0, mm200=90.0, preco=90.0)
    assert fx["teto"] == pytest.approx(100.0) and fx["ancora1a"] == pytest.approx(100.0)
    assert fx["caroAcima"] == pytest.approx(130.0)
    assert fx["limite3a"] == pytest.approx(48.0) and fx["limite5a"] == pytest.approx(30.0)
    assert fx["mm200"] == pytest.approx(90.0)
    assert fx["decisao"]["codigo"] == "AGUARDAR"   # 90 está entre 70 (oportunidade) e 130 (cara)


def test_faixa_conservador_sem_media_1a_fica_none():
    # ticker recém-listado (menos de 1 ano de pregão): sem teto, a tela cai pra faixa de 52 semanas
    assert _faixa_conservador(None, 80.0, 60.0, mm200=None, preco=20.0) is None


def test_faixa_conservador_caso_real_bbas3_ponto_de_entrada_fixo_em_30_por_cento():
    # caso real: âncora (preço médio 1a) 21,73 -> oportunidade 15,21, limite 3a 14,65, limite 5a
    # 11,28 (só referências visuais); preço 14,30 já bateu a oportunidade - COMPRAR, e o texto
    # "Ponto de oportunidade em" continua mostrando o alvo fixo de 30% (15,21), não os de 3/5 anos
    media_3a, media_5a = 14.646974525937608 / 0.60, 11.275316084938488 / 0.50
    fx = _faixa_conservador(21.73115379993732, media_3a, media_5a, mm200=21.65, preco=14.30)
    assert fx["oportunidadeAte"] == pytest.approx(15.21, abs=0.01)
    assert fx["limite3a"] == pytest.approx(14.65, abs=0.01)
    assert fx["limite5a"] == pytest.approx(11.28, abs=0.01)
    assert fx["decisao"]["codigo"] == "COMPRAR"
    assert "15,21" in fx["decisao"]["texto"]


def test_faixa_conservador_limites_exatos_70_e_130_por_cento():
    ancora = 100.0   # oportunidade até 70; zona neutra alargada até 130 (30% acima da âncora)
    fx_70 = _faixa_conservador(ancora, None, None, mm200=None, preco=70.0)   # 70% da âncora: ainda oportunidade
    assert fx_70["decisao"]["codigo"] == "COMPRAR"
    fx_100 = _faixa_conservador(ancora, None, None, mm200=None, preco=100.0)  # exatamente a âncora: ainda neutra
    assert fx_100["decisao"]["codigo"] == "AGUARDAR"
    fx_130 = _faixa_conservador(ancora, None, None, mm200=None, preco=130.0)  # 30% acima: ainda neutra
    assert fx_130["decisao"]["codigo"] == "AGUARDAR"
    fx_131 = _faixa_conservador(ancora, None, None, mm200=None, preco=130.01)  # passou dos 30%: cara
    assert fx_131["decisao"]["codigo"] == "CARO"
    assert fx_70["decisao"]["validado"] is False and fx_100["decisao"]["validado"] is False


def test_faixa_conservador_sem_3a_5a_nao_trava_o_teto():
    # sem histórico de 3/5 anos (ticker mais novo): o teto (âncora de 1 ano) continua valendo
    fx = _faixa_conservador(100.0, None, None, mm200=None, preco=20.0)
    assert fx is not None and fx["teto"] == pytest.approx(100.0)
    assert fx["limite3a"] is None and fx["limite5a"] is None


def test_outlook_trimestral_eua_le_do_arquivo_gravado_pelo_robo(tmp_path, monkeypatch):
    import json

    from tela.dados import ARQ_OUTLOOK_TRI, outlook_trimestral_eua

    arq = tmp_path / "guidance_trimestral_eua.json"
    arq.write_text(json.dumps({"MU": {"periodo": "1T FY2027", "receita_min": 6e10, "receita_max": 6.3e10,
                                      "margem_bruta": 85.95, "lpa_min": 36.84, "lpa_max": 38.84,
                                      "fonte": "MICRON TECHNOLOGY INC, Form 8-K (SEC)", "data": "30/09/2026"}}),
                   encoding="utf-8")
    monkeypatch.setattr("tela.dados.ARQ_OUTLOOK_TRI", arq)
    r = outlook_trimestral_eua("MU")
    assert r["periodo"] == "1T FY2027" and r["lpaMin"] == 36.84 and r["lpaMax"] == 38.84


def test_proximo_anuncio_info_le_do_info_ja_buscado_sem_rede_extra():
    from tela.dados import proximo_anuncio_info

    assert proximo_anuncio_info({"earningsTimestampStart": 1801056600}) == "27/01/2027"
    assert proximo_anuncio_info({"earningsTimestamp": 1801056600}) == "27/01/2027"
    assert proximo_anuncio_info({}) is None


def test_com_proximo_anuncio_prefere_info_mas_mantem_alternativa():
    from tela.dados import _com_proximo_anuncio

    assert _com_proximo_anuncio(None, {"earningsTimestampStart": 1801056600}) is None
    # info tem a data: ganha do que veio do robô/ao vivo
    ot = {"periodo": "4T FY2026", "proximoAnuncio": "17/12/2026"}
    assert _com_proximo_anuncio(ot, {"earningsTimestampStart": 1801056600})["proximoAnuncio"] == "27/01/2027"
    # info sem a data: mantém a alternativa (robô/ao vivo) em vez de apagar
    assert _com_proximo_anuncio(ot, {})["proximoAnuncio"] == "17/12/2026"


def test_outlook_trimestral_eua_traz_atualizacao_e_proximo_anuncio(tmp_path, monkeypatch):
    import json

    from tela.dados import ARQ_OUTLOOK_TRI, outlook_trimestral_eua

    arq = tmp_path / "guidance_trimestral_eua.json"
    arq.write_text(json.dumps({"MU": {"periodo": "1T FY2027", "receita_min": 6e10, "receita_max": 6.3e10,
                                      "fonte": "MICRON TECHNOLOGY INC, Form 8-K (SEC)", "data": "30/09/2026",
                                      "atualizado_em": "17/11 18:32", "proximo_anuncio": "17/12/2026"}}),
                   encoding="utf-8")
    monkeypatch.setattr("tela.dados.ARQ_OUTLOOK_TRI", arq)
    r = outlook_trimestral_eua("MU")
    assert r["proximoAnuncio"] == "17/12/2026"
    assert r["atualizacao"]["em"] == "17/11 18:32" and r["atualizacao"]["iso"].startswith("2026-11-17")


def test_outlook_trimestral_eua_b3_e_ticker_sem_dado_devolvem_none(tmp_path, monkeypatch):
    from tela.dados import outlook_trimestral_eua

    monkeypatch.setattr("tela.dados.ARQ_OUTLOOK_TRI", tmp_path / "nao_existe.json")
    assert outlook_trimestral_eua("PETR4.SA") is None
    assert outlook_trimestral_eua("ZZZZ") is None


def test_issue25_petr4_lucro_total_usa_acoes_oficiais_e_nao_as_do_yahoo():
    """PETR4: LPA contábil 10,89 × 12,89 bi (ON+PN oficial) = R$ 140,4 bi; nunca × 5,45 bi (só PN, Yahoo) = 59,3 bi."""
    from tela.dados import acoes_oficiais
    info = {"sharesOutstanding": 5446501379}
    sec = {"status": "ok", "lpa_12m": 10.8949, "acoes": 12888732761.0, "lucro_12m": 140421e6,
           "fonte_acoes": "Petrobras 6-K 3T26, nota 26"}
    acoes, fonte = acoes_oficiais(info, sec)
    assert acoes == 12888732761 and "6-K" in fonte
    assert round(sec["lpa_12m"] * acoes / 1e9, 1) == 140.4
    # BBAS3 (ações do contábil = as do Yahoo) não muda; sem contábil do robô, Yahoo
    assert acoes_oficiais({"sharesOutstanding": 5708922664}, {"status": "ok", "acoes": 5708922664.0})[0] == 5708922664
    assert acoes_oficiais(info, None) == (5446501379, "Yahoo")
    assert acoes_oficiais(info, {"status": "pendente"}) == (5446501379, "Yahoo")


# ------------------------------------------------------------ card "Dados fixos (fonte oficial)" (Issue #29)
def test_dados_fixos_tela_nao_encontrado():
    from tela.dados import dados_fixos_tela

    r = dados_fixos_tela({"status": "nao_encontrado", "mensagem": "Ticker não encontrado na fonte oficial.",
                          "ticker": "ZZZZ9"}, 10.0)
    assert r == {"status": "nao_encontrado", "ticker": "ZZZZ9", "mensagem": "Ticker não encontrado na fonte oficial."}


def test_dados_fixos_tela_none_sem_busca():
    from tela.dados import dados_fixos_tela

    assert dados_fixos_tela(None, 10.0) is None


def test_dados_fixos_tela_calcula_com_a_cotacao_do_dia():
    from tela.dados import dados_fixos_tela

    fixos = {"status": "ok", "ticker": "PETR4", "acoes_total": 12.89e9, "lucro_12m": 140.4e9,
             "dividendo_12m": None, "fator_adr": 1, "moeda_resultado": "BRL",
             "fonte_oficial": "PDF RI (CVM/IPE)", "data_ultimo_balanco": "30/09/2026", "avisoBalancoNovo": None}
    r = dados_fixos_tela(fixos, 42.67)
    assert r["status"] == "ok" and round(r["lpa"], 2) == 10.89 and round(r["pl"], 2) == 3.92
    assert r["fonteOficial"] == "PDF RI (CVM/IPE)" and r["dataUltimoBalanco"] == "30/09/2026"
    assert "LPA:" in r["contas"]["lpa"]
