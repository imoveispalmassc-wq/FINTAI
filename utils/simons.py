"""Modo Simons: queda dos últimos pregões, régua fixa de repique e o histórico do próprio ativo.

A régua fixa (1 a 5+ dias) ainda não foi validada. O histórico conta, nos últimos anos do ativo,
quantas vezes ele subiu no pregão seguinte depois de N dias de queda desde o topo.
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


JANELA = 10   # pregões olhados para trás (termômetro de 0 a 10)


def leitura(dias: int, maximo: int = 5) -> dict:
    """Termômetro (0 a `maximo`), probabilidade e ação pela régua fixa. 5 ou mais dias usam a última linha."""
    nivel = min(max(dias, 0), maximo)
    if nivel == 0:
        return {"nivel": 0, "prob": None, "acao": "NÃO FAZ NADA", "detalhe": "Sem queda no último pregão"}
    prob, acao, detalhe = REGUA[min(nivel, 5)]
    return {"nivel": nivel, "prob": prob, "acao": acao, "detalhe": detalhe}


def queda_desde_topo(fechamentos, janela: int = JANELA) -> dict:
    """Dias desde o maior fechamento dos últimos `janela` pregões, se o último pregão foi de queda.

    Uma alta no meio não quebra a contagem enquanto o preço não passar do topo. Se o último pregão
    subiu, o repique já começou: dias = 0."""
    c = pd.Series(fechamentos).dropna().to_numpy()[-(janela + 1):]
    vazio = {"dias": 0, "queda": 0.0, "altas": 0, "topo_pos": len(c) - 1}
    if len(c) < 2 or not c[-1] < c[-2]:
        return vazio
    topo = len(c) - 1 - int(c[::-1].argmax())   # topo mais recente, se o máximo se repetir
    dias = len(c) - 1 - topo
    if dias == 0:
        return vazio
    trecho = c[topo:]
    altas = int((trecho[1:] > trecho[:-1]).sum())
    return {"dias": dias, "queda": float((c[-1] / c[topo] - 1) * 100), "altas": altas, "topo_pos": topo}


def historico(fechamentos: pd.Series, anos: int = 5, janela: int = JANELA) -> dict:
    """No histórico do ativo (até `anos`), para cada N de 1 a `janela` dias de queda desde o topo:
    quantas vezes aconteceu e em quantas o pregão seguinte fechou em alta."""
    f = pd.Series(fechamentos).dropna()
    if len(f) and isinstance(f.index, pd.DatetimeIndex):
        f = f[f.index > f.index[-1] - pd.DateOffset(years=anos)]
    c = f.to_numpy()
    conta = {n: [0, 0] for n in range(1, janela + 1)}
    for t in range(janela, len(c) - 1):
        n = queda_desde_topo(c[t - janela:t + 1], janela)["dias"]
        if n:
            conta[n][0] += 1
            conta[n][1] += int(c[t + 1] > c[t])
    return {n: {"vezes": v, "altas": a, "pct": (a / v * 100) if v else None} for n, (v, a) in conta.items()}
