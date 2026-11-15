"""Modo Simons: sequência de quedas dos últimos pregões e a régua fixa de repique.

As probabilidades vêm de uma régua fixa, ainda não validada com dados deste ativo.
"""
from __future__ import annotations

import pandas as pd

# dias de queda seguidos -> (probabilidade de repique no dia seguinte em %, ação, detalhe)
REGUA = {
    1: (51, "NÃO FAZ NADA", "Não faz nada"),
    2: (54, "OBSERVA", "Observa"),
    3: (58, "MOVIMENTO CURTO", "Movimento curto pequeno"),
    4: (61, "MOVIMENTO CURTO", "Movimento curto médio"),
    5: (64, "MOVIMENTO CURTO", "Movimento curto maior"),
}
SELO = "A VALIDAR - Precisa de 12 meses de teste pra frente"


def sequencia_de_quedas(fechamentos: pd.Series, janela: int = 10) -> tuple[int, float]:
    """Dias seguidos de queda terminando no último pregão (no máximo `janela`) e a queda
    acumulada nesses dias, em %."""
    c = fechamentos.dropna().to_numpy()[-(janela + 1):]
    dias = 0
    i = len(c) - 1
    while i > 0 and c[i] < c[i - 1]:
        dias += 1
        i -= 1
    queda = (c[-1] / c[-1 - dias] - 1) * 100 if dias else 0.0
    return dias, float(queda)


def leitura(dias: int) -> dict:
    """Termômetro (0 a 5), probabilidade e ação pela régua fixa. 5 ou mais dias usam a última linha."""
    nivel = min(max(dias, 0), 5)
    if nivel == 0:
        return {"nivel": 0, "prob": None, "acao": "NÃO FAZ NADA", "detalhe": "Sem queda no último pregão"}
    prob, acao, detalhe = REGUA[nivel]
    return {"nivel": nivel, "prob": prob, "acao": acao, "detalhe": detalhe}
