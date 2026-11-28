"""Regras de decisão do FINTAI: estado do ativo, selo do teste histórico e fundamentos."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from utils.formato import num
from utils.percentile import (P_CARO, P_COMPRA, P_OPORTUNIDADE, percentil_movel,
                              preco_no_percentil)

ACERTO_MINIMO = 60.0   # % de acerto em 12 meses para validar um sinal
CASOS_MINIMOS = 8      # semanas de histórico no sinal para a estatística valer
DIVIDA_EBITDA_MAX = 4.0
TOLERANCIA = 5.0       # % de diferença para um critério deixar de ser "Neutro"


# ------------------------------------------------------------ selo do backtest
@dataclass(frozen=True)
class Selo:
    validado: bool
    rotulo: str
    texto: str


def selo_backtest(tipo: str, acerto_12m: float | None, retorno_12m: float | None,
                  referencia_12m: float | None, casos: int, ticker: str = "") -> Selo:
    """Valida um sinal pelo que aconteceu nos 12 meses seguintes, no histórico do ativo.

    tipo "compra": acerto = % das vezes em que a ação subiu; validado se acerto > 60%
        e o retorno médio superou a referência (comprar em uma semana qualquer).
    tipo "venda": acerto = % das vezes em que a ação caiu; validado se acerto > 60%
        e o retorno médio ficou abaixo da referência.
    """
    nome = ticker or "este ativo"
    faltam = (acerto_12m is None or retorno_12m is None or referencia_12m is None
              or casos < CASOS_MINIMOS)
    if tipo == "compra":
        ok = not faltam and acerto_12m > ACERTO_MINIMO and retorno_12m > referencia_12m
        if ok:
            if referencia_12m > 0:
                texto = f"Comprar nesse sinal deu {num(retorno_12m / referencia_12m, 1)}x mais retorno"
            else:
                texto = "Comprar nesse sinal rendeu mais do que comprar em uma semana qualquer"
        elif faltam:
            texto = f"Poucos casos no histórico. NÃO use esse sinal para comprar {nome}."
        else:
            texto = (f"Comprar nesse sinal não rendeu mais do que comprar em uma semana "
                     f"qualquer. NÃO use esse sinal para comprar {nome}.")
    elif tipo == "venda":
        ok = not faltam and acerto_12m > ACERTO_MINIMO and retorno_12m < referencia_12m
        if ok:
            texto = (f"Depois desse sinal a ação caiu em {num(acerto_12m, 0)}% das vezes. "
                     "Vender nesse sinal evitou perdas.")
        elif not faltam and retorno_12m > 0:
            texto = f"Quem vendeu perdeu alta. NÃO use esse sinal para vender {nome}."
        elif faltam:
            texto = f"Poucos casos no histórico. NÃO use esse sinal para vender {nome}."
        else:
            texto = f"Vender nesse sinal não se confirmou. NÃO use esse sinal para vender {nome}."
    else:
        raise ValueError("tipo deve ser 'compra' ou 'venda'")
    return Selo(ok, "SINAL VALIDADO ✅" if ok else "SINAL INVALIDADO ❌", texto)


# ------------------------------------------------------------ fundamento quebrou
def fundamento_quebrou(lucros_trimestrais: pd.Series | None,
                       divida_liquida_ebitda: float | None) -> tuple[bool, str]:
    """True se os 2 últimos trimestres deram prejuízo ou dívida líquida/EBITDA > 4."""
    if lucros_trimestrais is not None:
        l = lucros_trimestrais.dropna().sort_index()
        if len(l) >= 2 and (l.iloc[-2:] < 0).all():
            return True, "2 trimestres seguidos de prejuízo"
    if divida_liquida_ebitda is not None and divida_liquida_ebitda > DIVIDA_EBITDA_MAX:
        return True, f"dívida líquida de {num(divida_liquida_ebitda, 1)}x o EBITDA (limite: 4x)"
    return False, ""


# ------------------------------------------------------------ estado
@dataclass(frozen=True)
class Estado:
    codigo: str   # COMPRAR | AGUARDAR | CARO
    rotulo: str
    texto: str
    zona: str     # Faixa inferior | Zona neutra | Faixa superior (issue #47, item 10: nomes sem
                  # julgamento de valor - "Oportunidade"/"Cara" tirados do texto, cores mantidas)
    validado: bool = False   # só faz sentido na Faixa inferior
    alerta: str = ""         # aviso de fundamento quebrado; não muda o botão


def decidir_estado(percentil: float, minimo: float, maximo: float, *,
                   compra_validada: bool, venda_validada: bool = False,
                   quebrou: bool = False, motivo_quebra: str = "",
                   simbolo: str = "R$", preco: float | None = None,
                   tendencia: str = "") -> Estado:
    """Decisão pela posição do preço na faixa de 52 semanas, igual para qualquer ativo.

    - Preço <= Ponto de oportunidade (mínima + 30% da amplitude): COMPRAR, rótulo "Faixa inferior"
    - Preço entre o Ponto e o Fim da Neutra:                      AGUARDAR, rótulo "Neutro"
    - Preço > Fim da Neutra (mínima + 70% da amplitude):          CARO, rótulo "Faixa superior"

    `rotulo` nunca usa palavra de julgamento ("Oportunidade"/"Evitar") nem verbo de recomendação
    ("AGUARDAR") - só o nome neutro da zona, pra nunca sugerir uma recomendação de compra/venda/
    espera ao usuário (só `codigo`, interno, continua COMPRAR/AGUARDAR/CARO - usado pra cor/classe
    CSS, nunca mostrado).

    `texto` descreve o limite da PRÓPRIA zona em que o preço está (REGRA TRAVADA, 27/11/2026 - bug
    reportado pelo usuário com BBAS3: preço na Faixa inferior mostrava "Faixa neutra a partir de
    R$ 15,11", confundindo porque descrevia a zona ACIMA, não a zona onde o preço realmente estava):
    - Preço na Faixa inferior: "Faixa inferior até [limite de 30%]" - o preço está nessa zona, então
      o texto fecha ela por cima.
    - Preço na Zona neutra: "Faixa neutra a partir de [limite de 30%]" - mesmo valor de sempre (o
      início da própria zona neutra, que é onde o preço está).
    - Preço na Faixa superior: "Faixa superior acima de [limite de 70%]" - mesma ideia, abrindo a
      própria zona por baixo.
    Os avisos (zona não validada pelo histórico, fundamento quebrado) vão em `alerta` e não mudam o
    botão. A posição numérica na faixa nunca aparece no texto.
    """
    alvo = preco_no_percentil(minimo, maximo, P_OPORTUNIDADE)
    avisos = [f"Atenção: {motivo_quebra}."] if quebrou and motivo_quebra else []
    if percentil <= P_OPORTUNIDADE:
        if not compra_validada:
            avisos.append("Comprar nessa zona não foi validado pelo histórico deste ativo.")
        texto = f"Faixa inferior até {simbolo} {num(alvo)}"
        return Estado("COMPRAR", "Faixa inferior", texto, "Faixa inferior",
                      compra_validada, " ".join(avisos))
    if percentil > P_CARO:
        cara = preco_no_percentil(minimo, maximo, P_CARO)
        texto = f"Faixa superior acima de {simbolo} {num(cara)}"
        return Estado("CARO", "Faixa superior", texto, "Faixa superior", False, " ".join(avisos))
    texto = f"Faixa neutra a partir de {simbolo} {num(alvo)}"
    return Estado("AGUARDAR", "Neutro", texto, "Zona neutra", False, " ".join(avisos))


def decidir_estado_conservador(preco: float, teto: float, caro_acima: float | None = None, *,
                               quebrou: bool = False, motivo_quebra: str = "", simbolo: str = "R$") -> Estado:
    """Decisão do modo Conservador por valuation (Preço Teto = âncora de preço médio de 1 ano),
    não pela faixa de preço histórica de 52 semanas.

    - Preço <= 70% da âncora (margem de segurança de 30%): COMPRAR, rótulo "Faixa inferior"
    - Preço entre 70% da âncora e `caro_acima` (padrão: a própria âncora × 1,30 - zona
      neutra alargada em 30% acima, pra não virar "Faixa superior" só por passar um pouco do teto):
      AGUARDAR, rótulo "Neutro"
    - Preço > caro_acima:                                     CARO, rótulo "Faixa superior"

    `rotulo` sem palavra de julgamento nem verbo de recomendação - mesma regra de `decidir_estado`
    acima (`codigo` continua interno, só pra cor/classe CSS). `texto` descreve o limite da PRÓPRIA
    zona em que o preço está - mesma regra travada de `decidir_estado` acima ("Faixa inferior até"/
    "Faixa neutra a partir de"/"Faixa superior acima de"). Nunca validado por teste histórico (não
    existe backtest para este critério)."""
    alvo = teto * 0.70
    caro_acima = teto * 1.30 if caro_acima is None else caro_acima
    avisos = [f"Atenção: {motivo_quebra}."] if quebrou and motivo_quebra else []
    if preco <= alvo:
        texto = f"Faixa inferior até {simbolo} {num(alvo)}"
        return Estado("COMPRAR", "Faixa inferior", texto, "Faixa inferior", False, " ".join(avisos))
    if preco > caro_acima:
        texto = f"Faixa superior acima de {simbolo} {num(caro_acima)}"
        return Estado("CARO", "Faixa superior", texto, "Faixa superior", False, " ".join(avisos))
    texto = f"Faixa neutra a partir de {simbolo} {num(alvo)}"
    return Estado("AGUARDAR", "Neutro", texto, "Zona neutra", False, " ".join(avisos))


# ------------------------------------------------------------ critérios de fundamentos
@dataclass(frozen=True)
class Avaliacao:
    status: str            # Favorável | Neutro | Desfavorável | Sem dados
    icone: str
    diferenca: float | None  # % do valor atual em relação à referência


def avaliar_criterio(atual: float | None, referencia: float | None, *,
                     maior_e_melhor: bool, tolerancia: float = TOLERANCIA) -> Avaliacao:
    """Compara o valor atual com a referência. Diferença dentro de ±5% é Neutro."""
    if atual is None or referencia is None or pd.isna(atual) or pd.isna(referencia) or referencia == 0:
        return Avaliacao("Sem dados", "➖", None)
    dif = (atual - referencia) / abs(referencia) * 100
    if abs(dif) < tolerancia:
        return Avaliacao("Neutro", "⚠️", dif)
    bom = dif > 0 if maior_e_melhor else dif < 0
    return Avaliacao("Favorável", "✅", dif) if bom else Avaliacao("Desfavorável", "❌", dif)


# ------------------------------------------------------------ teste histórico
def backtest_percentil(hist: pd.DataFrame, anos: float | None = 5) -> dict:
    """Testa as zonas semana a semana, só com dados conhecidos em cada data, e mede o que
    aconteceu 6 e 12 meses depois.

    anos: tamanho da janela, contada para trás a partir do último pregão (None = todo o
    histórico). Só entram semanas dentro da janela.

    Devolve, para "compra" (Zona de Oportunidade), "venda" (Zona Cara) e "referencia"
    (qualquer semana): casos, retorno médio de 6 e 12 meses e acerto de 12 meses.
    Na venda, acerto = % das vezes em que a ação caiu. "anos" é o período realmente
    coberto e "insuficiente" avisa quando o histórico não chega à janela pedida.
    """
    h = hist.copy()
    if getattr(h.index, "tz", None) is not None:
        h.index = h.index.tz_localize(None)
    h = h.sort_index().dropna(subset=["High", "Low", "Close"])
    adj = (h["Adj Close"] if "Adj Close" in h else h["Close"]).ffill()
    w = h.resample("W-FRI").agg({"Low": "min", "High": "max", "Close": "last"})
    w["adj"] = adj.resample("W-FRI").last()
    w = w.dropna(subset=["Close"])
    perc = percentil_movel(w["Close"], w["Low"], w["High"]).to_numpy()
    valido = ~np.isnan(perc)
    fim = h.index[-1]
    if anos is not None:
        valido &= np.asarray(w.index > fim - pd.DateOffset(years=int(anos)))
    r6 = (w["adj"].shift(-26) / w["adj"] - 1).to_numpy() * 100
    r12 = (w["adj"].shift(-52) / w["adj"] - 1).to_numpy() * 100

    def medir(mascara, acerto_na_queda=False):
        m = mascara & valido
        a, b = r6[m & ~np.isnan(r6)], r12[m & ~np.isnan(r12)]
        acerto = None
        if len(b):
            acerto = float(((b < 0) if acerto_na_queda else (b > 0)).mean() * 100)
        return {"casos": int(len(b)),
                "retorno_6m": float(a.mean()) if len(a) else None,
                "retorno_12m": float(b.mean()) if len(b) else None,
                "acerto_12m": acerto}

    with np.errstate(invalid="ignore"):
        compra, venda = perc <= P_COMPRA, perc >= P_CARO
    datas = w.index[valido]
    coberto = (fim - datas[0]).days / 365.25 if len(datas) else 0.0
    return {
        "compra": medir(compra),
        "venda": medir(venda, acerto_na_queda=True),
        "referencia": medir(np.ones(len(w), dtype=bool)),
        "anos": coberto,
        "insuficiente": anos is not None and coberto < anos - 0.25,
    }


# ------------------------------------------------------------ selo de fundamentos (issue #47, item 11)
def avaliar_fundamentos(*, lucro_caindo: bool | None, lucro_trimestres_seguidos: int | None = None,
                        prejuizo: bool = False, roe_caindo: bool | None = None, roe_abaixo_10: bool | None = None,
                        roe_trimestres_seguidos: int | None = None, roe_disponivel: bool = True,
                        paga_dividendo: bool = True,
                        dividendo_cortado: bool | None = None, dividendo_cortes_seguidos: int | None = None,
                        divida_subindo: bool | None = None) -> dict | None:
    """Selo de Fundamentos: só um FATO de fundamento, nunca uma recomendação de compra/venda.

    REGRA TRAVADA: lucro é SEMPRE o LPA/lucro CONTÁBIL (nunca ajustado) - se o contábil caiu,
    conta contra a empresa mesmo que o ajustado esteja bonito.

    Os 3 fundamentos avaliados: (1) lucro contábil caindo; (2) ROE caindo; (3) dividendo
    cortado/reduzido (ignorado para quem não paga dividendo, ex. MU, OU quando não há dado de
    dividendo disponível - `paga_dividendo=False` nos dois casos, decidido por quem chama).

    Esta função é pura: quem chama decide se há dado suficiente para preencher cada argumento.
    `lucro_caindo` é o único fundamento OBRIGATÓRIO (sem ele, devolve None - nunca inventamos a
    comparação). ROE é OPCIONAL (28/11/2026, pedido do usuário): `roe_disponivel=False` ignora o
    ROE no cálculo (mesma ideia de `paga_dividendo=False` pro dividendo) - usado quando não existe
    série trimestral de ROE pra aquele ticker (hoje, nenhum ticker tem). Com `roe_disponivel=True`
    (padrão, compatível com o uso anterior) e `roe_caindo=None`, ainda devolve None.

    LIMITAÇÃO CONHECIDA (ver CLAUDE.md): o projeto não guarda série trimestral de ROE em nenhuma
    fonte (`patrimonio_liquido` em `utils/dados_fixos.json` é só o balanço mais recente, nunca uma
    série) - por isso quem chama hoje sempre passa `roe_disponivel=False`, e o selo nível 3 (que
    exige ROE caindo e abaixo de 10% por 2+ trimestres) nunca dispara enquanto isso não existir.
    Lucro e dividendo já usam dado real (últimos 4 trimestres de `utils/contabil_br.json` /
    `utils/contabil_sec.json` e `utils/dados_fixos.json` - ver `tela.dados._fundamentos_selo`),
    comparando os 2 trimestres mais recentes contra os 2 anteriores (o máximo que os 4 trimestres
    guardados permitem) - mais simples que "mesmo trimestre do ano anterior", mas real, não None.
    """
    if lucro_caindo is None:
        return None
    itens = [(bool(lucro_caindo), "Lucro em queda")]
    if roe_disponivel:
        if roe_caindo is None:
            return None
        itens.append((bool(roe_caindo), "ROE em queda"))
    if paga_dividendo:
        if dividendo_cortado is None:
            return None
        itens.append((bool(dividendo_cortado), "Dividendo reduzido"))
    ruins = [nome for ok, nome in itens if ok]
    n_ruins = len(ruins)
    if n_ruins == 0:
        return None

    # Nível 3 (estrutural, 2+ trimestres seguidos): lucro caindo 3-4 trimestres seguidos OU
    # prejuízo; e ROE caindo e abaixo de 10% por 2+ trimestres seguidos; e (se paga dividendo)
    # dividendo cortado 2x seguidas; e dívida subindo. Sem ROE disponível, nunca dispara (roe_caindo
    # fica None/falsy) - não é um bug, é a trava "nunca inventa" fazendo o trabalho dela.
    estrutural = (
        (prejuizo or (lucro_trimestres_seguidos is not None and lucro_trimestres_seguidos >= 3))
        and bool(roe_caindo) and bool(roe_abaixo_10) and (roe_trimestres_seguidos is not None and roe_trimestres_seguidos >= 2)
        and bool(divida_subindo)
        and (not paga_dividendo or (dividendo_cortes_seguidos is not None and dividendo_cortes_seguidos >= 2))
    )
    # Motivos (28/11/2026, pedido do usuário): lista pra mostrar embaixo do título QUAIS
    # fundamentos acionaram o selo - sem isso, "Fundamentos em alerta" não dizia nada sobre qual
    # dos 3. Nível 1 mostra só o único motivo que disparou; Nível 2/3 mostram os 3 critérios
    # avaliados, inclusive "ROE: sem dado" quando `roe_disponivel=False` (nunca "ROE em queda" sem
    # dado de verdade - regra "nunca inventa"). Dividendo usa "cortado" só no Nível 3 (estrutural,
    # 2x seguidas) e "reduzido" no 1/2 (1 só já ruim).
    if n_ruins == 1:
        return {"nivel": 1, "titulo": f"Observar: {ruins[0]}", "motivos": [ruins[0]],
                "subtexto": "1 fundamento em alerta. Verifique antes de decidir."}
    dividendo_palavra = "Dividendo cortado" if estrutural else "Dividendo reduzido"
    motivos = ["Lucro em queda" if lucro_caindo else None]
    # 28/11/2026: com ROE disponível, sempre mostra uma linha pra ele (mesmo estável) - antes só
    # aparecia quando estava caindo, dando a entender (errado) que não tínhamos o dado.
    motivos.append(("ROE em queda" if roe_caindo else "ROE estável") if roe_disponivel else "ROE: sem dado")
    if paga_dividendo:
        motivos.append(dividendo_palavra if dividendo_cortado else None)
    motivos = [m for m in motivos if m]
    if estrutural:
        return {"nivel": 3, "titulo": "Fundamentos deteriorados", "motivos": motivos,
                "subtexto": "Lucro, ROE e dividendo piorando juntos há mais de 2 trimestres. Preço baixo aqui não é desconto, é reflexo do fundamento."}
    return {"nivel": 2, "titulo": "Fundamentos em alerta", "motivos": motivos,
            "subtexto": "Preço baixo não significa barato."}
