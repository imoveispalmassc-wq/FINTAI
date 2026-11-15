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
