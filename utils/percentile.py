"""Posição do preço dentro da faixa de 52 semanas ("percentil") e zonas de preço.

Percentil = (preço - mínima de 52 semanas) / (máxima - mínima) × 100.
0 = na mínima do ano, 100 = na máxima.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

P_OPORTUNIDADE = 25  # zona de oportunidade: mínima + 25% da amplitude de 52 semanas
P_COMPRA = 25        # o teste histórico de compra usa a mesma zona de oportunidade
P_CARO = 75          # zona cara: máxima - 25% da amplitude


def percentil_na_faixa(preco: float, minimo: float, maximo: float) -> float:
    """Posição do preço na faixa mínimo–máximo, de 0 a 100."""
    if maximo <= minimo:
        return 50.0
    return max(0.0, min(100.0, (preco - minimo) / (maximo - minimo) * 100))


def preco_no_percentil(minimo: float, maximo: float, percentil: float) -> float:
    """Preço que corresponde a um percentil da faixa."""
    return minimo + (maximo - minimo) * percentil / 100


@dataclass(frozen=True)
class Zonas:
    minimo: float
    maximo: float
    oportunidade_ate: float  # preço no percentil 30
    cara_acima: float        # preço no percentil 70


def zonas(minimo: float, maximo: float) -> Zonas:
    return Zonas(minimo, maximo,
                 preco_no_percentil(minimo, maximo, P_OPORTUNIDADE),
                 preco_no_percentil(minimo, maximo, P_CARO))


def nome_da_zona(percentil: float) -> str:
    if percentil <= P_OPORTUNIDADE:
        return "Oportunidade"
    if percentil > P_CARO:
        return "Cara"
    return "Neutra"


def percentil_movel(fechamento: pd.Series, minima: pd.Series, maxima: pd.Series,
                    janela: int = 52) -> pd.Series:
    """Percentil de cada período usando só a faixa das `janela` observações até ele
    (sem olhar para o futuro). Usado no teste histórico, com dados semanais."""
    lo = minima.rolling(janela).min()
    hi = maxima.rolling(janela).max()
    largura = (hi - lo).where(hi > lo)
    return ((fechamento - lo) / largura * 100).clip(0, 100)
