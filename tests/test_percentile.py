import pandas as pd
import pytest

from utils.percentile import (nome_da_zona, percentil_movel, percentil_na_faixa,
                              preco_no_percentil, zonas)

# Exemplo CSMG3 da especificação
PRECO, MINIMO, MAXIMO = 55.15, 37.34, 67.82


def test_percentil_csmg3():
    assert round(percentil_na_faixa(PRECO, MINIMO, MAXIMO)) == 58


def test_percentil_nos_extremos_e_fora_da_faixa():
    assert percentil_na_faixa(MINIMO, MINIMO, MAXIMO) == 0
    assert percentil_na_faixa(MAXIMO, MINIMO, MAXIMO) == 100
    assert percentil_na_faixa(10, MINIMO, MAXIMO) == 0
    assert percentil_na_faixa(99, MINIMO, MAXIMO) == 100


def test_percentil_faixa_sem_largura():
    assert percentil_na_faixa(10, 10, 10) == 50


def test_zonas_csmg3():
    z = zonas(MINIMO, MAXIMO)
    assert round(z.oportunidade_ate, 2) == 46.48   # mínima + 30% da amplitude
    assert round(z.cara_acima, 2) == 58.68         # mínima + 70% da amplitude


def test_preco_no_percentil_e_inverso_do_percentil():
    p = percentil_na_faixa(PRECO, MINIMO, MAXIMO)
    assert preco_no_percentil(MINIMO, MAXIMO, p) == pytest.approx(PRECO)


@pytest.mark.parametrize("p,zona", [(0, "Oportunidade"), (30, "Oportunidade"), (31, "Neutra"),
                                    (58, "Neutra"), (70, "Neutra"), (70.1, "Cara"), (100, "Cara")])
def test_nome_da_zona(p, zona):
    assert nome_da_zona(p) == zona


def test_percentil_movel_nao_olha_o_futuro():
    s = pd.Series([10.0, 20.0, 15.0, 30.0, 12.0])
    p = percentil_movel(s, s, s, janela=3)
    assert p.isna().tolist() == [True, True, False, False, False]
    assert p.iloc[2] == 50   # 15 na faixa 10–20
    assert p.iloc[3] == 100  # 30 é a máxima da janela 20,15,30
    assert p.iloc[4] == 0    # 12 é a mínima da janela 15,30,12


def test_validacao_da_regra_com_a_faixa_da_mu():
    """Mínima 192,59 e máxima 1.255,00 têm de dar ponto 511,31 e fim da neutra 936,28."""
    z = zonas(192.59, 1255.00)
    assert round(z.oportunidade_ate, 2) == 511.31
    assert round(z.cara_acima, 2) == 936.28


@pytest.mark.parametrize("minimo,maximo", [(192.59, 1255.00), (187.37, 291.24), (29.02, 39.90)])
def test_ponto_de_oportunidade_muda_com_o_ativo(minimo, maximo):
    z = zonas(minimo, maximo)
    assert z.oportunidade_ate == pytest.approx(minimo + 0.30 * (maximo - minimo))
    assert z.cara_acima == pytest.approx(minimo + 0.70 * (maximo - minimo))
    assert minimo < z.oportunidade_ate < z.cara_acima < maximo


def test_tres_ativos_dao_tres_pontos_diferentes():
    pontos = {round(zonas(a, b).oportunidade_ate, 2) for a, b in [(192.59, 1255.00), (187.37, 291.24), (29.02, 39.90)]}
    assert len(pontos) == 3
