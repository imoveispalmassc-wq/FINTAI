import pandas as pd
import pytest

from utils.lynch import cagr, crescimento_anual, peg, regra_prejuizo, veredito
from utils.simons import REGUA, leitura, sequencia_de_quedas


# ------------------------------------------------------------ regra de prejuízo
def test_sem_prejuizo_usa_a_media_dos_3_anos():
    r = regra_prejuizo([2.0, 4.0, 6.0])
    assert r["status"] == "ok" and r["media"] == pytest.approx(4.0) and r["mensagem"] == ""


def test_um_ano_de_prejuizo_sai_da_media():
    r = regra_prejuizo([-5.0, 4.0, 6.0])
    assert r["status"] == "excluido" and r["media"] == pytest.approx(5.0)
    assert r["mensagem"] == "Ano de prejuízo excluído"


def test_dois_anos_de_prejuizo_nao_calcula():
    r = regra_prejuizo([-5.0, -1.0, 6.0])
    assert r["status"] == "recorrente" and r["media"] is None
    assert r["mensagem"] == "Sem cálculo - Empresa com prejuízo recorrente"


def test_regra_usa_so_os_3_ultimos_anos_e_trata_falta_de_dados():
    assert regra_prejuizo([-9.0, 2.0, 4.0, 6.0])["status"] == "ok"
    assert regra_prejuizo([])["status"] == "sem_dados"
    assert regra_prejuizo([None, float("nan")])["status"] == "sem_dados"


# ------------------------------------------------------------ Lynch
def test_cagr():
    assert cagr(100, 133.1, 3) == pytest.approx(10.0)
    assert cagr(-1, 5, 3) is None and cagr(5, -1, 3) is None and cagr(5, 6, 0) is None


def test_crescimento_anual_com_e_sem_exclusao():
    pontos = [(2022, 100.0), (2023, 110.0), (2024, 121.0), (2025, 133.1)]
    g, anos = crescimento_anual(pontos)
    assert g == pytest.approx(10.0) and anos == 3
    com_prejuizo = [(2022, -3.0), (2023, 2.0), (2024, 3.0), (2025, 4.5)]
    assert crescimento_anual(com_prejuizo)[0] is None
    g, anos = crescimento_anual(com_prejuizo, excluir_negativos=True)
    assert g == pytest.approx(50.0) and anos == 2


def test_peg():
    assert peg(10.47, 20.0) == pytest.approx(0.5235)
    assert peg(10.0, -5.0) is None and peg(None, 10.0) is None and peg(-3.0, 10.0) is None


@pytest.mark.parametrize("p,receita,cor,titulo", [
    (0.5, 25.0, "verde", "Lynch aprova"),
    (0.5, 5.0, "amarelo", "Lynch fica de olho"),     # PEG bom, receita cresce pouco
    (1.5, 25.0, "amarelo", "Lynch fica de olho"),
    (2.5, 25.0, "vermelho", "Lynch não compra"),
    (0.5, -2.0, "vermelho", "Lynch não compra"),     # receita caindo
])
def test_veredito_lynch(p, receita, cor, titulo):
    v = veredito(p, receita, "ok")
    assert (v["cor"], v["titulo"]) == (cor, titulo)


def test_veredito_lynch_sem_lucro_e_sem_peg():
    assert veredito(0.5, 25.0, "recorrente")["titulo"] == "Sem PEG - Lynch não compra empresa sem lucro"
    assert veredito(None, 12.0, "ok")["cor"] == "cinza"
    assert veredito(None, 12.0, "ok", lucro_futuro=-8.0)["titulo"] == "Lynch não compra"


# ------------------------------------------------------------ Simons
def _fech(valores):
    return pd.Series(valores, index=pd.bdate_range("2026-11-02", periods=len(valores)), dtype=float)


def test_sequencia_de_quedas():
    assert sequencia_de_quedas(_fech([10, 11, 12])) == (0, 0.0)
    dias, queda = sequencia_de_quedas(_fech([10, 12, 11, 10.5, 9.9]))
    assert dias == 3 and queda == pytest.approx((9.9 / 12 - 1) * 100)
    assert sequencia_de_quedas(_fech([10, 9, 9.5, 9.4]))[0] == 1


def test_sequencia_respeita_a_janela_de_10_dias():
    dias, _ = sequencia_de_quedas(_fech(list(range(40, 20, -1))))
    assert dias == 10


@pytest.mark.parametrize("dias,prob,acao", [(1, 51, "NÃO FAZ NADA"), (2, 54, "OBSERVA"),
                                            (3, 58, "MOVIMENTO CURTO"), (4, 61, "MOVIMENTO CURTO"),
                                            (5, 64, "MOVIMENTO CURTO"), (8, 64, "MOVIMENTO CURTO")])
def test_regua_fixa(dias, prob, acao):
    l = leitura(dias)
    assert (l["prob"], l["acao"]) == (prob, acao) and l["nivel"] == min(dias, 5)


def test_sem_queda_nao_ha_probabilidade():
    l = leitura(0)
    assert l["prob"] is None and l["acao"] == "NÃO FAZ NADA" and l["nivel"] == 0


def test_app_nao_usa_a_palavra_proibida():
    import pathlib
    raiz = pathlib.Path(__file__).parent.parent
    proibida = "tra" + "de"
    for nome in ("app.py", "tela/detalhe.js", "tela/detalhe.html", "tela/dados.py",
                 "utils/simons.py", "utils/lynch.py", "utils/signals.py"):
        assert proibida not in (raiz / nome).read_text(encoding="utf-8").lower(), nome
    assert all(proibida not in " ".join(map(str, v)).lower() for v in REGUA.values())


def test_queda_desde_o_topo_nao_quebra_com_alta_no_meio():
    from utils.simons import queda_desde_topo
    c = [16.5, 16.4, 16.1, 16.4, 16.4, 17.13, 17.0, 17.1, 16.9, 15.5, 15.1, 14.73]   # -11 .. hoje
    q = queda_desde_topo(_fech(c))
    assert q["dias"] == 6 and q["altas"] == 1
    assert q["queda"] == pytest.approx((14.73 / 17.13 - 1) * 100)


def test_queda_desde_o_topo_zera_se_hoje_subiu_ou_hoje_e_o_topo():
    from utils.simons import queda_desde_topo
    assert queda_desde_topo(_fech([10, 9, 8, 8.5]))["dias"] == 0
    assert queda_desde_topo(_fech([8, 9, 10]))["dias"] == 0


def test_queda_desde_o_topo_vai_ate_10_dias():
    from utils.simons import queda_desde_topo
    assert queda_desde_topo(_fech(list(range(40, 20, -1))))["dias"] == 10


def test_historico_conta_casos_e_altas_no_dia_seguinte():
    from utils.simons import historico
    # padrão repetido: topo 11, três quedas (10, 9, 8), volta ao topo
    c = [10, 9, 8, 11] * 30
    h = historico(_fech(c), anos=50)
    assert h[1]["vezes"] > 0 and h[1]["pct"] == 0 and h[2]["pct"] == 0   # depois de 1 e 2 dias, mais queda
    assert h[3]["pct"] == 100                                            # depois de 3 dias, sempre subiu
    assert h[7]["vezes"] == 0 and h[7]["pct"] is None


def test_leitura_ate_10_dias_usa_a_ultima_linha_da_regua():
    l = leitura(8, 10)
    assert l["nivel"] == 8 and l["prob"] == 64 and l["acao"] == "MOVIMENTO CURTO"
