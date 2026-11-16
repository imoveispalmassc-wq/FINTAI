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
    anterior = 0
    for t in range(janela, len(c) - 1):
        n = queda_desde_topo(c[t - janela:t + 1], janela)["dias"]
        # o último grupo ("10 ou mais") conta cada queda uma vez só, no dia em que chega a 10;
        # senão uma queda de 20 dias entraria 11 vezes (do 10º ao 20º dia), sobrepostas
        if n and not (n == janela and anterior == janela):
            conta[n][0] += 1
            conta[n][1] += int(c[t + 1] > c[t])
        anterior = n
    return {n: {"vezes": v, "altas": a, "pct": (a / v * 100) if v else None} for n, (v, a) in conta.items()}


# ------------------------------------------------------------ ordem: MM200 -> oportunidade -> dias
MM200_OPORTUNIDADE = 5.0   # oportunidade só com o preço até +5% acima da média de 200 dias
MM200_CARO = 15.0          # +15% ou mais acima da média de 200 dias = esticado, caro


def classificar(preco: float, mm200: float | None, inclinacao: float | None,
                oportunidade_ate: float, cara_acima: float) -> dict:
    """Passos 1 e 2 do SIMONS: faixa de 52 semanas (30/70) e distância até a MM200.

    Oportunidade: zona de oportunidade da faixa E até +5% da MM200.
    Caro: zona cara da faixa OU +15% ou mais acima da MM200. O resto é Neutro.
    "conservador": preço abaixo da MM200 com a média caindo (tendência de baixa)."""
    dist = round((preco / mm200 - 1) * 100, 2) if mm200 else None   # arredonda como na tela
    zona = "Oportunidade" if preco <= oportunidade_ate else "Cara" if preco > cara_acima else "Neutra"
    caindo = inclinacao is not None and not pd.isna(inclinacao) and inclinacao < -1
    if zona == "Cara" or (dist is not None and dist >= MM200_CARO):
        classe = "CARO"
    elif zona == "Oportunidade" and (dist is None or dist <= MM200_OPORTUNIDADE):
        classe = "OPORTUNIDADE"
    else:
        classe = "NEUTRO"
    return {"classe": classe, "subzona": zona, "distMM200": dist, "conservador": bool(mm200 and preco < mm200 and caindo),
            "mm200Caindo": caindo, "bemAbaixoAte": None, "oportunidadeAte": oportunidade_ate,
            "caroAcima": cara_acima, "pelaMM200": False}


def timing(classe: str, dias: int, conservador: bool) -> dict:
    """Passo 3: os dias de queda viram entrada escalonada (em terços), só dentro de uma oportunidade.

    Normal: 2-3 dias = 1/3, 4-6 dias = 2/3, 7+ dias = 3/3 (o 5º dia nunca manda tudo).
    Conservador (abaixo da MM200 com média caindo): 4-6 dias = 1/3, 7+ dias = 2/3; a última parte
    só depois que o preço voltar acima da MM200 ou a média parar de cair."""
    if classe == "CARO":
        return {"parte": 0, "acao": "NÃO COMPRA", "detalhe": "Preço caro: dias de queda não abrem compra"}
    if classe == "NEUTRO":
        return {"parte": 0, "acao": "AGUARDAR", "detalhe": "Fora da oportunidade: dias de queda são só alerta"}
    if conservador:
        parte = 2 if dias >= 7 else 1 if dias >= 4 else 0
        limite = "; última parte só com o preço acima da MM200 ou a média parando de cair"
    else:
        parte = 3 if dias >= 7 else 2 if dias >= 4 else 1 if dias >= 2 else 0
        limite = ""
    if parte == 0:
        return {"parte": 0, "acao": "OBSERVA",
                "detalhe": f"Oportunidade validada; esperar {4 if conservador else 2} dias de queda para a 1ª parte{limite}"}
    return {"parte": parte, "acao": f"ENTRADA {parte}/3",
            "detalhe": f"Movimento curto: {parte}ª parte de 3{limite}"}


# ------------------------------------------------------------ "melhor" linha do histórico: só com padrão forte
MELHOR_MIN_CASOS = 30
MELHOR_ACIMA_MEDIA = 8.0    # pontos acima da média geral
MELHOR_ACIMA_SEGUNDO = 5.0  # pontos acima da segunda melhor


def melhor_linha(hist: dict) -> dict:
    """Linha com padrão forte de alta no dia seguinte, ou o aviso de que não há.

    Regras: 30+ casos; 8+ pontos acima da média geral (todas as linhas somadas);
    5+ pontos acima da segunda melhor (entre as com 30+ casos)."""
    tv = sum(v["vezes"] for v in hist.values())
    ta = sum(v["altas"] for v in hist.values())
    media = ta / tv * 100 if tv else None
    elegiveis = sorted(((n, v["altas"] / v["vezes"] * 100, v) for n, v in hist.items() if v["vezes"] >= MELHOR_MIN_CASOS),
                       key=lambda x: (-x[1], -x[2]["vezes"]))
    if not elegiveis or media is None:
        return {"dias": None, "media": media, "min": None, "max": None, "motivo": "poucos casos"}
    n, pct, v = elegiveis[0]
    segundo = elegiveis[1][1] if len(elegiveis) > 1 else None
    pcts = [e[1] for e in elegiveis]
    forte = pct >= media + MELHOR_ACIMA_MEDIA and (segundo is None or pct >= segundo + MELHOR_ACIMA_SEGUNDO)
    if not forte:
        return {"dias": None, "media": media, "min": min(pcts), "max": max(pcts), "motivo": "ruido",
                "topDias": n, "topPct": pct, "segundoDias": elegiveis[1][0] if len(elegiveis) > 1 else None,
                "segundo": segundo, "falhaMedia": pct < media + MELHOR_ACIMA_MEDIA,
                "falhaSegundo": segundo is not None and pct < segundo + MELHOR_ACIMA_SEGUNDO}
    return {"dias": n, "pct": pct, "vezes": v["vezes"], "altas": v["altas"], "media": media,
            "segundo": segundo, "min": min(pcts), "max": max(pcts), "motivo": ""}
