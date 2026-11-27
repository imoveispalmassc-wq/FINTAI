import numpy as np
import pandas as pd
import pytest

from utils.percentile import percentil_na_faixa
from utils.signals import (avaliar_criterio, avaliar_fundamentos, backtest_percentil, decidir_estado,
                           fundamento_quebrou, selo_backtest)

MINIMO, MAXIMO = 37.34, 67.82


def estado(percentil, **kw):
    base = dict(compra_validada=False, venda_validada=False)
    base.update(kw)
    return decidir_estado(percentil, MINIMO, MAXIMO, **base)


# ------------------------------------------------------------ estado
def test_aguardar_entre_o_ponto_e_o_fim_da_neutra():
    e = estado(percentil_na_faixa(55.15, MINIMO, MAXIMO), compra_validada=True)
    assert (e.codigo, e.rotulo, e.zona) == ("AGUARDAR", "Neutro", "Zona neutra")
    assert e.texto == "Faixa neutra a partir de R$ 46,48"
    assert estado(31).codigo == "AGUARDAR" and estado(70).codigo == "AGUARDAR"


def test_comprar_ate_o_ponto_de_oportunidade():
    sim = estado(30, compra_validada=True)
    assert (sim.codigo, sim.rotulo, sim.zona) == ("COMPRAR", "Faixa inferior", "Faixa inferior")
    assert sim.validado and sim.alerta == ""
    nao = estado(10, compra_validada=False)
    assert nao.codigo == "COMPRAR" and not nao.validado
    assert nao.alerta == "Comprar nessa zona não foi validado pelo histórico deste ativo."


def test_caro_acima_do_fim_da_neutra():
    for p in (70.1, 85, 100):
        e = estado(p, venda_validada=True)
        assert (e.codigo, e.rotulo, e.zona) == ("CARO", "Faixa superior", "Faixa superior")


def test_texto_descreve_o_limite_da_propria_zona_do_preco():
    # bug reportado pelo usuário com BBAS3: preço na Faixa inferior mostrava "Faixa neutra a
    # partir de" - o texto tem que descrever o limite da zona em que o PREÇO está, não de outra.
    assert estado(5).texto == "Faixa inferior até R$ 46,48"
    assert estado(50).texto == "Faixa neutra a partir de R$ 46,48"
    assert estado(95).texto == "Faixa superior acima de R$ 58,68"
    mu = decidir_estado(55, 192.59, 1255.0, compra_validada=False, simbolo="US$", preco=778.31, tendencia="Alta")
    assert mu.texto == "Faixa neutra a partir de US$ 511,31"


def test_fundamento_quebrado_vira_alerta_e_nao_muda_o_botao():
    e = estado(50, quebrou=True, motivo_quebra="2 trimestres seguidos de prejuízo")
    assert e.codigo == "AGUARDAR" and e.alerta == "Atenção: 2 trimestres seguidos de prejuízo."
    assert estado(50).alerta == ""


@pytest.mark.parametrize("p", range(0, 101, 5))
@pytest.mark.parametrize("compra,quebrou", [(False, False), (True, False), (True, True)])
def test_textos_nunca_citam_percentil_nem_venda(p, compra, quebrou):
    e = estado(p, compra_validada=compra, venda_validada=True, quebrou=quebrou, motivo_quebra="x")
    texto = (e.rotulo + e.texto + e.zona + e.alerta).lower()
    assert "percentil" not in texto and "vend" not in texto and "%" not in texto
    assert e.codigo in ("COMPRAR", "AGUARDAR", "CARO")


# ------------------------------------------------------------ fundamento quebrou
def test_fundamento_quebrou():
    datas = pd.date_range("2025-03-31", periods=4, freq="QE")
    assert fundamento_quebrou(pd.Series([5, 3, -1, -2], datas), None)[0]
    assert not fundamento_quebrou(pd.Series([5, -3, 1, -2], datas), None)[0]
    assert not fundamento_quebrou(pd.Series([-5, -3, 1, 2], datas), None)[0]
    assert fundamento_quebrou(None, 4.5)[0]
    assert not fundamento_quebrou(None, 4.0)[0]
    assert not fundamento_quebrou(None, None)[0]


# ------------------------------------------------------------ selo
def test_selo_compra_validado_mostra_o_multiplo_real():
    s = selo_backtest("compra", 75, 30, 15, 40, "CSMG3")
    assert s.validado and s.rotulo == "SINAL VALIDADO ✅"
    assert s.texto == "Comprar nesse sinal deu 2,0x mais retorno"


def test_selo_compra_invalidado():
    assert not selo_backtest("compra", 55, 30, 15, 40).validado      # acerto baixo
    assert not selo_backtest("compra", 75, 10, 15, 40).validado      # perdeu da referência
    assert not selo_backtest("compra", 75, 30, 15, 3).validado       # poucos casos
    assert not selo_backtest("compra", None, None, 15, 0).validado   # sem dados
    assert selo_backtest("compra", 60, 30, 15, 40).validado is False  # exige > 60, não >=


def test_selo_venda_invalidado_usa_o_texto_obrigatorio():
    s = selo_backtest("venda", 20, 18, 15, 40, "CSMG3")
    assert not s.validado and s.rotulo == "SINAL INVALIDADO ❌"
    assert s.texto == "Quem vendeu perdeu alta. NÃO use esse sinal para vender CSMG3."


def test_selo_venda_validado():
    s = selo_backtest("venda", 70, -12, 15, 40, "XPTO3")
    assert s.validado and "caiu em 70%" in s.texto


def test_selo_venda_invalido_sem_alta_nao_afirma_que_perdeu_alta():
    s = selo_backtest("venda", 55, -3, -8, 40, "XPTO3")
    assert not s.validado and "perdeu alta" not in s.texto


# ------------------------------------------------------------ critérios
def test_avaliar_criterio():
    assert avaliar_criterio(8, 10, maior_e_melhor=False).status == "Favorável"     # P/L menor
    assert avaliar_criterio(12, 10, maior_e_melhor=False).status == "Desfavorável"
    assert avaliar_criterio(10.3, 10, maior_e_melhor=False).status == "Neutro"
    assert avaliar_criterio(6, 5, maior_e_melhor=True).status == "Favorável"       # DY maior
    assert avaliar_criterio(None, 5, maior_e_melhor=True).status == "Sem dados"
    assert avaliar_criterio(5, 0, maior_e_melhor=True).status == "Sem dados"
    assert avaliar_criterio(8, 10, maior_e_melhor=False).diferenca == pytest.approx(-20)
    # referência negativa (prejuízo que virou lucro) conta como melhora
    assert avaliar_criterio(1, -2, maior_e_melhor=True).status == "Favorável"


# ------------------------------------------------------------ backtest
def _hist(fechamentos):
    idx = pd.bdate_range("2018-01-01", periods=len(fechamentos))
    c = pd.Series(fechamentos, idx, dtype=float)
    return pd.DataFrame({"High": c, "Low": c, "Close": c, "Adj Close": c})


def test_backtest_em_alta_constante():
    # ação que só sobe: sempre na máxima da faixa, toda "venda" perde alta
    b = backtest_percentil(_hist(np.linspace(10, 100, 2000)))
    assert b["compra"]["casos"] == 0
    assert b["venda"]["casos"] > 50
    assert b["venda"]["acerto_12m"] == 0
    assert b["venda"]["retorno_12m"] > 0
    assert b["referencia"]["acerto_12m"] == 100


def test_backtest_ciclico_valida_a_compra():
    # ação que oscila sem tendência: comprar em baixo rende mais do que a média
    t = np.arange(2600)
    b = backtest_percentil(_hist(50 + 20 * np.sin(2 * np.pi * t / 520)))
    assert b["compra"]["retorno_12m"] > b["referencia"]["retorno_12m"]
    assert b["venda"]["retorno_12m"] < b["referencia"]["retorno_12m"]
    assert b["compra"]["acerto_12m"] > 60 and b["venda"]["acerto_12m"] > 60


def test_backtest_janela_de_5_anos():
    t = np.arange(2600)                      # ~10 anos de pregões
    h = _hist(50 + 20 * np.sin(2 * np.pi * t / 520))
    b5, bmax = backtest_percentil(h, anos=5), backtest_percentil(h, anos=None)
    assert 4.9 <= b5["anos"] <= 5.05 and not b5["insuficiente"]
    assert bmax["anos"] > 8
    assert b5["referencia"]["casos"] < bmax["referencia"]["casos"]


def test_backtest_avisa_historico_insuficiente():
    b = backtest_percentil(_hist(np.linspace(10, 30, 900)), anos=5)   # ~3,5 anos
    assert b["insuficiente"] and b["anos"] < 5


# ------------------------------------------------------------ selo de fundamentos (issue #47, item 11)
def test_selo_fundamentos_sem_historico_nao_aparece():
    # sem lucro_caindo ou roe_caindo (histórico insuficiente): nunca inventa comparação
    assert avaliar_fundamentos(lucro_caindo=None, roe_caindo=False) is None
    assert avaliar_fundamentos(lucro_caindo=False, roe_caindo=None) is None
    # paga dividendo mas falta o dado de dividendo: também não aparece
    assert avaliar_fundamentos(lucro_caindo=False, roe_caindo=False, dividendo_cortado=None) is None


def test_selo_fundamentos_sem_nenhum_ruim():
    assert avaliar_fundamentos(lucro_caindo=False, roe_caindo=False, dividendo_cortado=False) is None


def test_selo_fundamentos_nivel_1_observar():
    s = avaliar_fundamentos(lucro_caindo=True, roe_caindo=False, dividendo_cortado=False)
    assert s["nivel"] == 1 and s["titulo"] == "Observar: Lucro"


def test_selo_fundamentos_nivel_2_alerta():
    s = avaliar_fundamentos(lucro_caindo=True, roe_caindo=True, dividendo_cortado=False)
    assert s["nivel"] == 2 and s["titulo"] == "Fundamentos em alerta"


def test_selo_fundamentos_nivel_3_deteriorados():
    s = avaliar_fundamentos(lucro_caindo=True, lucro_trimestres_seguidos=3, roe_caindo=True,
                            roe_abaixo_10=True, roe_trimestres_seguidos=2, dividendo_cortado=True,
                            dividendo_cortes_seguidos=2, divida_subindo=True)
    assert s["nivel"] == 3 and s["titulo"] == "Fundamentos deteriorados"


def test_selo_fundamentos_empresa_sem_dividendo_ignora_esse_criterio():
    # ex. MU: não paga dividendo - usa só lucro + ROE, sem exigir o dado de dividendo
    s = avaliar_fundamentos(lucro_caindo=True, roe_caindo=True, paga_dividendo=False)
    assert s["nivel"] == 2
    # nível 3 sem dívida subindo não dispara, mesmo com os outros 2 ruins
    s2 = avaliar_fundamentos(lucro_caindo=True, lucro_trimestres_seguidos=4, roe_caindo=True,
                             roe_abaixo_10=True, roe_trimestres_seguidos=2, paga_dividendo=False,
                             divida_subindo=False)
    assert s2["nivel"] == 2
