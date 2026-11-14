"""Formatação de números no padrão brasileiro."""
from __future__ import annotations

import math


def num(v, casas: int = 2) -> str:
    """1234.5 -> '1.234,50'. Valores ausentes viram '—'."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    s = f"{v:,.{casas}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def pct(v, casas: int = 2) -> str:
    """12.3 -> '+12,30%'."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    return f"{'+' if v > 0 else ''}{num(v, casas)}%"
