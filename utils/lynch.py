"""Regra de prejuízo (válida para os modos Graham e Lynch) e cálculos do modo Lynch."""
from __future__ import annotations

import math


def regra_prejuizo(lpas: list[float]) -> dict:
    """Aplica a regra aos LPAs anuais dos últimos 3 anos (do mais antigo ao mais novo).

    - nenhum ano negativo: média dos anos              -> status "ok"
    - 1 ano negativo: sai da média                      -> status "excluido"
    - 2 ou mais anos negativos: não calcula             -> status "recorrente"
    - sem dados                                         -> status "sem_dados"
    """
    vals = [float(x) for x in lpas if x is not None and not math.isnan(float(x))][-3:]
    if not vals:
        return {"status": "sem_dados", "media": None, "mensagem": "Dados indisponíveis"}
    negativos = [x for x in vals if x < 0]
    if len(negativos) >= 2:
        return {"status": "recorrente", "media": None,
                "mensagem": "Sem cálculo - Empresa com prejuízo recorrente"}
    positivos = [x for x in vals if x >= 0]
    if len(negativos) == 1:
        media = sum(positivos) / len(positivos) if positivos else None
        return {"status": "excluido" if positivos else "recorrente", "media": media,
                "mensagem": "Ano de prejuízo excluído" if positivos
                else "Sem cálculo - Empresa com prejuízo recorrente"}
    return {"status": "ok", "media": sum(vals) / len(vals), "mensagem": ""}


def cagr(inicio: float, fim: float, anos: float) -> float | None:
    """Crescimento composto ao ano, em %. None se algum valor não for positivo."""
    if inicio is None or fim is None or anos is None or anos <= 0 or inicio <= 0 or fim <= 0:
        return None
    return ((fim / inicio) ** (1 / anos) - 1) * 100


def crescimento_anual(pontos: list[tuple[int, float]], excluir_negativos: bool = False
                      ) -> tuple[float | None, int]:
    """Crescimento ao ano entre o primeiro e o último ano da lista [(ano, valor), ...].

    Com excluir_negativos, anos de prejuízo saem antes da conta (regra de prejuízo).
    Devolve (crescimento % a.a., número de anos entre as pontas)."""
    p = sorted((int(a), float(v)) for a, v in pontos if v is not None and not math.isnan(float(v)))
    if excluir_negativos:
        p = [x for x in p if x[1] >= 0]
    if len(p) < 2:
        return None, 0
    anos = p[-1][0] - p[0][0]
    return cagr(p[0][1], p[-1][1], anos), anos


def peg(pl: float | None, crescimento: float | None) -> float | None:
    """PEG = P/L ÷ crescimento do lucro (em % ao ano). Só existe com os dois positivos."""
    if pl is None or crescimento is None or pl <= 0 or crescimento <= 0:
        return None
    return pl / crescimento


def veredito(peg_futuro: float | None, receita: float | None, status_prejuizo: str,
             lucro_futuro: float | None = None) -> dict:
    """Cor e frase do modo Lynch.

    Vermelho: PEG > 2, receita caindo, lucro estimado em queda ou prejuízo recorrente.
    Verde:    PEG < 1 e receita crescendo mais de 10%.
    Amarelo:  o resto (PEG entre 1 e 2, ou receita crescendo pouco).
    """
    if status_prejuizo == "recorrente":
        return {"cor": "vermelho", "titulo": "Sem PEG - Lynch não compra empresa sem lucro", "motivo": ""}
    if receita is not None and receita < 0:
        return {"cor": "vermelho", "titulo": "Lynch não compra", "motivo": "Receita caindo."}
    if peg_futuro is None:
        if lucro_futuro is not None and lucro_futuro <= 0:
            return {"cor": "vermelho", "titulo": "Lynch não compra",
                    "motivo": "Os analistas estimam lucro em queda, então não há PEG."}
        return {"cor": "cinza", "titulo": "Sem PEG - Sem estimativa no Yahoo para este ativo", "motivo": ""}
    if peg_futuro > 2:
        return {"cor": "vermelho", "titulo": "Lynch não compra", "motivo": "PEG maior que 2."}
    if peg_futuro < 1 and receita is not None and receita > 10:
        return {"cor": "verde", "titulo": "Lynch aprova", "motivo": "PEG menor que 1 e receita crescendo mais de 10%."}
    motivo = "PEG entre 1 e 2." if peg_futuro >= 1 else "PEG menor que 1, mas a receita cresce pouco."
    if receita is None:
        motivo = "PEG calculado, mas sem dado de crescimento da receita."
    return {"cor": "amarelo", "titulo": "Lynch fica de olho", "motivo": motivo}


# ------------------------------------------------------------ preço no modo Lynch: só pela MM200 (ignora a faixa 30/70)
LYNCH_BEM_ABAIXO = -10.0   # abaixo de MM200 -10%: "Bem abaixo da MM200", mostrado à parte
LYNCH_OPORTUNIDADE = 5.0   # oportunidade: MM200 -10% até MM200 +5%
LYNCH_CARO = 15.0          # caro: +15% ou mais acima da MM200


def preco_lynch(preco: float, mm200: float | None, simbolo: str = "R$") -> dict | None:
    """Bem abaixo (< -10%) e Faixa inferior (-10% a +5%) = COMPRAR; Neutro (+5% a +15%); Faixa
    superior (+15% ou mais). `rotulo` sem palavra de julgamento nem verbo de recomendação (mesma
    regra de `utils.signals.decidir_estado` - `codigo` continua interno, só pra cor/classe CSS).
    `texto` descreve o limite da PRÓPRIA zona em que o preço está, mesma regra travada de
    `utils.signals.decidir_estado` ("Faixa inferior até"/"Faixa neutra a partir de"/"Faixa superior
    acima de" - nunca o limite de uma zona diferente da que o preço está)."""
    if not mm200 or mm200 <= 0 or preco is None:
        return None
    dist = round((preco / mm200 - 1) * 100, 2)   # arredonda como na tela (evita 14,9999...)
    ate = mm200 * (1 + LYNCH_OPORTUNIDADE / 100)
    cara = mm200 * (1 + LYNCH_CARO / 100)
    num = lambda v: f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if dist >= LYNCH_CARO:
        codigo, rotulo, zona = "CARO", "Faixa superior", "Faixa superior"
        texto = f"Faixa superior acima de {simbolo} {num(cara)}"
    elif dist > LYNCH_OPORTUNIDADE:
        codigo, rotulo, zona = "AGUARDAR", "Neutro", "Zona neutra"
        texto = f"Faixa neutra a partir de {simbolo} {num(ate)}"
    elif dist >= LYNCH_BEM_ABAIXO:
        codigo, rotulo, zona = "COMPRAR", "Faixa inferior", "Faixa inferior"
        texto = f"Faixa inferior até {simbolo} {num(ate)}"
    else:
        codigo, rotulo, zona = "COMPRAR", "Bem abaixo da MM200", "Bem abaixo da MM200"
        texto = f"Faixa inferior até {simbolo} {num(ate)}"
    return {"codigo": codigo, "rotulo": rotulo, "zona": zona, "dist": dist,
            "bemAbaixoAte": mm200 * (1 + LYNCH_BEM_ABAIXO / 100), "oportunidadeAte": ate,
            "caroAcima": cara, "texto": texto}
