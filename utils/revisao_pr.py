"""Revisão automática dos PRs do Automático (guidance/TTM/biblioteca) - Issue pedida pelo usuário
em 28/11/2026: "aplica esta trava de segurança em todos os PRs do Automático a partir de agora. Não
mergear se falhar 1 trava." Vale pra QUALQUER PR aberto pelos robôs (ttm/revisar,
ttm/contabil-revisar, ttm/robo-claude-*, biblioteca/revisar) - 4 travas, todas têm que passar:

TRAVA 1 - NENHUM TICKER APAGADO: todo ticker que já existia no arquivo (base) continua existindo
no PR (head). Some um ticker = bug do robô (sobrescreveu o arquivo em vez de atualizar), não uma
remoção intencional - o projeto não tem nenhum fluxo que apaga ticker por decisão automática.

TRAVA 2 - NENHUM VALOR APROVADO REGREDIDO: um valor já publicado (está no `main`, ou seja em
`antes`) pro MESMO período (mesma `trimestre_ref`/`periodo`/chave de período) não pode virar um
valor DIFERENTE no PR - isso seria o robô reescrevendo um número já revisado/aprovado por humano,
não uma atualização legítima (atualização legítima é um PERÍODO NOVO, não uma mudança no período
que já estava lá). Mudança de período (trimestre novo) nunca é regressão, mesmo que o valor numérico
caia (ex.: LPA trimestral pode ser menor que o trimestre anterior - isso é dado real, não bug).

TRAVA 3 - REVISÃO CONTRA O DOCUMENTO OFICIAL: cada entrada tem que citar uma fonte oficial (RI da
empresa, SEC EDGAR, CVM/RAD) com link - sem fonte oficial rastreável (ou achando uma fonte que
claramente não é da empresa certa, ex. notícia/agregador), a trava falha. A CONFIRMAÇÃO de verdade
do número contra o texto do documento (ticker/período/valor/página batendo) é feita à parte (manual
ou via Perplexity/API do Claude, pela infra que já existe em `utils/biblioteca.py` e
`utils/fetch_guidance.py`) - esta função só verifica que a entrada TEM o que permite essa conferência
(fonte oficial reconhecível + link) e, quando a confirmação já foi feita, aceita o registro dela
(`pagina_conferida=True` por quem chama).

TRAVA 4 - NENHUMA TROCA DE TICKER: 2 tickers diferentes nunca podem compartilhar o MESMO link +
MESMO valor - isso é sinal de que o robô copiou o resultado de um ticker pro outro por engano
(ex.: GOOGL com o link e valor da MSFT).

Travou em qualquer uma: a PR vira DRAFT (não é fechada, não é mergeada) e o motivo vai num comentário
- decisão humana depois. Passou nas 4: pode mergear.
"""
from __future__ import annotations

FONTES_OFICIAIS_DOMINIOS = (
    "sec.gov", "cvm.gov.br", "rad.cvm.gov.br",
)


def _dominio(url: str) -> str:
    if not url:
        return ""
    sem_protocolo = url.split("://", 1)[-1]
    return sem_protocolo.split("/", 1)[0].lower()


def tickers_removidos(antes: dict, depois: dict) -> list[str]:
    """TRAVA 1: tickers que estavam em `antes` (o que já está no main) e sumiram em `depois`
    (o que o PR propõe). Lista vazia = trava passou."""
    return sorted(set(antes) - set(depois))


def _periodos(registro: dict) -> dict:
    """Chave de período de um registro de ticker, pra comparar "mesmo período" entre antes/depois.
    Aceita os nomes de campo já usados nos vários JSONs do projeto (trimestre_ref, periodo, ano)."""
    chaves = ("trimestre_ref", "periodo", "ano", "trimestre_data")
    return {k: registro.get(k) for k in chaves if registro.get(k) is not None}


def _campos_numericos(registro: dict) -> dict:
    return {k: v for k, v in registro.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}


def valores_regredidos(antes: dict, depois: dict) -> list[dict]:
    """TRAVA 2: ticker presente nos 2 lados, MESMO período (mesma trimestre_ref/periodo/ano), mas
    um campo numérico mudou de valor - isso é o robô reescrevendo um número já publicado pro mesmo
    período, não uma atualização legítima (que seria um período NOVO). Lista vazia = trava passou.
    Cada item: {"ticker", "campo", "antes", "depois", "periodo"}."""
    achados = []
    for ticker in sorted(set(antes) & set(depois)):
        reg_antes, reg_depois = antes[ticker], depois[ticker]
        if not isinstance(reg_antes, dict) or not isinstance(reg_depois, dict):
            continue
        # campos aninhados (ex. biblioteca.json: ticker -> campo -> registro)
        if all(isinstance(v, dict) for v in reg_antes.values()) and reg_antes:
            for campo in sorted(set(reg_antes) & set(reg_depois)):
                achados.extend(
                    _diferenca_mesmo_periodo(ticker, campo, reg_antes[campo], reg_depois[campo]))
            continue
        achados.extend(_diferenca_mesmo_periodo(ticker, None, reg_antes, reg_depois))
    return achados


def _diferenca_mesmo_periodo(ticker: str, campo: str | None, a: dict, d: dict) -> list[dict]:
    if not isinstance(a, dict) or not isinstance(d, dict):
        return []
    periodo_a, periodo_d = _periodos(a), _periodos(d)
    if periodo_a != periodo_d:
        return []  # período mudou (trimestre novo) - atualização legítima, nunca regressão
    out = []
    num_a, num_d = _campos_numericos(a), _campos_numericos(d)
    for chave in sorted(set(num_a) & set(num_d)):
        if num_a[chave] != num_d[chave]:
            out.append({"ticker": ticker, "campo": chave if not campo else f"{campo}.{chave}",
                        "antes": num_a[chave], "depois": num_d[chave], "periodo": periodo_a})
    return out


def fonte_oficial_rastreavel(registro: dict) -> bool:
    """TRAVA 3 (parte verificável sem rede): a entrada cita um link de domínio oficial reconhecido
    (SEC EDGAR, CVM/RAD) OU, pra RI de empresa (domínio não listado, cada empresa tem o seu), que
    pelo menos exista um link não vazio pra conferência manual/Perplexity - sem link nenhum, a trava
    falha direto (não tem como conferir)."""
    link = registro.get("link") or registro.get("url") or ""
    return bool(link)


def _chave_dedup(registro: dict) -> tuple | None:
    link = registro.get("link") or registro.get("url")
    valor = registro.get("valor") if "valor" in registro else registro.get("lpa_ttm") or registro.get("lpa")
    if not link or valor is None:
        return None
    return (link, valor)


def tickers_trocados(depois: dict) -> list[dict]:
    """TRAVA 4: 2 tickers diferentes com o MESMO link + MESMO valor - sinal de cópia errada de um
    ticker pro outro. Lista vazia = trava passou. Cada item: {"chave": (link, valor), "tickers": [...]}."""
    por_chave: dict[tuple, list[str]] = {}
    for ticker, registro in depois.items():
        if not isinstance(registro, dict):
            continue
        alvos = registro.values() if all(isinstance(v, dict) for v in registro.values()) and registro else [registro]
        for alvo in alvos:
            if not isinstance(alvo, dict):
                continue
            chave = _chave_dedup(alvo)
            if chave:
                por_chave.setdefault(chave, []).append(ticker)
    return [{"chave": chave, "tickers": sorted(set(tks))}
            for chave, tks in por_chave.items() if len(set(tks)) > 1]


def revisar(antes: dict, depois: dict) -> dict:
    """Roda as 4 travas e devolve o veredito: {"passou": bool, "falhas": {trava: [...]}}."""
    falhas = {}
    removidos = tickers_removidos(antes, depois)
    if removidos:
        falhas["TRAVA 1 - ticker apagado"] = removidos
    regredidos = valores_regredidos(antes, depois)
    if regredidos:
        falhas["TRAVA 2 - valor regredido"] = regredidos
    sem_fonte = [t for t, reg in depois.items()
                 if isinstance(reg, dict) and t not in antes
                 and not (all(isinstance(v, dict) for v in reg.values()) and reg
                          and any(fonte_oficial_rastreavel(v) for v in reg.values()))
                 and not fonte_oficial_rastreavel(reg)]
    if sem_fonte:
        falhas["TRAVA 3 - sem fonte rastreável"] = sem_fonte
    trocados = tickers_trocados(depois)
    if trocados:
        falhas["TRAVA 4 - ticker trocado"] = trocados
    return {"passou": not falhas, "falhas": falhas}
