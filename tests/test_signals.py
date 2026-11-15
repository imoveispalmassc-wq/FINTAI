import numpy as np
import pandas as pd
import pytest

from utils.percentile import percentil_na_faixa
from utils.signals import (avaliar_criterio, backtest_percentil, decidir_estado,
                           fundamento_quebrou, selo_backtest)

MINIMO, MAXIMO = 37.34, 67.82


def estado(percentil, **kw):
    base = dict(compra_validada=False, venda_validada=False)
    base.update(kw)
    return decidir_estado(percentil, MINIMO, MAXIMO, **base)


# ------------------------------------------------------------ estado
def test_csmg3_fica_em_aguardar_com_o_texto_da_especificacao():
    e = estado(percentil_na_faixa(55.15, MINIMO, MAXIMO), compra_validada=True, venda_validada=True)
    assert e.codigo == "AGUARDAR"
    assert e.texto == "Ponto de oportunidade em R$ 46,48."
    assert e.zona == "Zona neutra"


def test_comprar_exige_preco_baixo_e_backtest_validado():
    assert estado(30, compra_validada=True).codigo == "COMPRAR"
    assert estado(20, compra_validada=True).codigo == "COMPRAR"
    assert estado(20, compra_validada=False).codigo == "AGUARDAR"
    assert estado(31, compra_validada=True).codigo == "AGUARDAR"


def test_caro_nunca_fala_em_venda():
    for p in (70, 85, 100):
        e = estado(p)
        assert e.codigo == "CARO"
        assert "Caro para comprar agora" in e.texto
        assert "vend" not in (e.rotulo + e.texto).lower()


def test_vender_so_com_backtest_validado_ou_fundamento_quebrado():
    assert estado(80, venda_validada=True).codigo == "VENDER"
    assert estado(80, venda_validada=False).codigo == "CARO"
    # venda validada não vale fora da zona cara
    assert estado(50, venda_validada=True).codigo == "AGUARDAR"
    # fundamento quebrado vale em qualquer preço
    e = estado(10, compra_validada=True, quebrou=True, motivo_quebra="2 trimestres seguidos de prejuízo")
    assert e.codigo == "VENDER" and "prejuízo" in e.texto


@pytest.mark.parametrize("p", range(0, 101, 5))
@pytest.mark.parametrize("compra,venda,quebrou", [(False, False, False), (True, True, False),
                                                   (True, True, True)])
def test_textos_nunca_citam_percentil(p, compra, venda, quebrou):
    e = estado(p, compra_validada=compra, venda_validada=venda, quebrou=quebrou, motivo_quebra="x")
    assert "percentil" not in (e.rotulo + e.texto + e.zona).lower()


@pytest.mark.parametrize("p", range(0, 101, 5))
def test_venda_nunca_aparece_sem_validacao(p):
    e = estado(p, compra_validada=True, venda_validada=False, quebrou=False)
    assert e.codigo != "VENDER"
    assert "vend" not in (e.rotulo + e.texto).lower()


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
