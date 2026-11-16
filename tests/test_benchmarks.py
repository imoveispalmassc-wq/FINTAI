import pandas as pd
import pytest

from utils.benchmarks import acumular, mensal_de_aniversario

FIM = pd.Timestamp("2026-11-13")


def test_acumular_taxas_mensais():
    # 12 meses a 1% ao mês = 12,68% no ano
    datas = pd.date_range("2025-11-01", periods=13, freq="MS")
    s = pd.Series(1.0, index=datas)
    assert acumular(s, FIM - pd.DateOffset(years=1), FIM) == pytest.approx(12.6825, abs=1e-3)


def test_acumular_taxas_diarias():
    datas = pd.bdate_range("2025-10-01", FIM)
    s = pd.Series(0.05, index=datas)
    n = ((datas > FIM - pd.DateOffset(years=1)) & (datas <= FIM)).sum()
    assert acumular(s, FIM - pd.DateOffset(years=1), FIM) == pytest.approx((1.0005 ** n - 1) * 100)


def test_acumular_sem_cobertura_devolve_none():
    s = pd.Series(1.0, index=pd.date_range("2026-03-01", periods=8, freq="MS"))
    assert acumular(s, FIM - pd.DateOffset(years=1), FIM) is None
    assert acumular(pd.Series(dtype=float), FIM - pd.DateOffset(years=1), FIM) is None
    assert acumular(None, FIM - pd.DateOffset(years=1), FIM) is None


def test_poupanca_usa_um_aniversario_por_mes():
    s = pd.Series(0.6, index=pd.date_range("2026-01-01", "2026-03-31", freq="D"))
    m = mensal_de_aniversario(s)
    assert list(m.index.day) == [1, 1, 1]


def test_ipca_de_12_meses_conta_12_meses_ate_o_ultimo_divulgado(monkeypatch):
    import utils.benchmarks as b
    # IPCA de out/2026 é o último divulgado em 13/11/2026; série mensal datada no dia 1º
    meses = pd.date_range("2021-09-01", "2026-10-01", freq="MS")
    ipca = pd.Series(0.5, index=meses)
    monkeypatch.setattr(b, "buscar_sgs", lambda codigo, i, f: ipca if codigo == 433 else pd.Series(dtype=float))
    v = b.retornos_brasil(pd.Timestamp("2026-11-13"))["ipca"]
    assert round(v[0], 4) == round((1.005 ** 12 - 1) * 100, 4)
    assert round(v[1], 4) == round((1.005 ** 36 - 1) * 100, 4)


def test_cdi_conta_as_taxas_de_um_fechamento_ao_outro(monkeypatch):
    import utils.benchmarks as b
    dias = pd.bdate_range("2021-10-01", "2026-11-13")
    cdi = pd.Series(0.05, index=dias)
    monkeypatch.setattr(b, "buscar_sgs", lambda codigo, i, f: cdi if codigo == 12 else pd.Series(dtype=float))
    v = b.retornos_brasil(FIM)["cdi"][0]
    # taxas de 13/11/2025 (inclusive) até 12/11/2026: rendem do fechamento de um dia ao do outro
    n = ((dias >= FIM - pd.DateOffset(years=1)) & (dias < FIM)).sum()
    assert v == pytest.approx((1.0005 ** n - 1) * 100)


def test_poupanca_so_conta_aniversarios_completos(monkeypatch):
    import utils.benchmarks as b
    dias = pd.date_range("2021-09-01", "2026-11-13", freq="D")
    poup = pd.Series(0.6, index=dias)
    monkeypatch.setattr(b, "buscar_sgs", lambda codigo, i, f: poup if codigo == 195 else pd.Series(dtype=float))
    v = b.retornos_brasil(FIM)["poupanca"]
    # em 13/11/2026 o período iniciado em 01/11 ainda não terminou: nov/2025 a out/2026 = 12 períodos
    assert v[0] == pytest.approx((1.006 ** 12 - 1) * 100)
    assert v[2] == pytest.approx((1.006 ** 60 - 1) * 100)
