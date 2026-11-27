"""Biblioteca própria de dados fundamentalistas pesquisados - Issue #48, item 8.

Cache do próprio projeto para qualquer dado fundamentalista (LPA, lucro, dividendo, ROE etc.) -
`utils/biblioteca.json`, no mesmo padrão dos outros caches (ticker -> campo -> registro, igual a
`utils/contabil_br.json` / `utils/contabil_sec.json`).

FLUXO (biblioteca primeiro, rede depois):
1. `buscar_na_biblioteca(ticker, campo, hoje)` - se já tem o dado e não está desatualizado, usa
   (sem bater em Yahoo/SEC/CVM/Perplexity de novo).
2. Sem dado, ou desatualizado, OU se o Yahoo quebrar (erro de rede/parsing): busca fora. A ORDEM
   DE FONTE não muda - é a mesma já definida no projeto (SEC > RI > B3/CVM > Yahoo, ver
   CLAUDE.md, "TTM automático: PROMPT TRAVADO"); quando nenhuma delas responde, só então entra a
   Perplexity (`pesquisar_via_perplexity`), com o PROMPT PADRÃO exato da Issue #48 (não mudar o
   texto do prompt).
3. Achou um dado novo (de onde vier) -> `salvar_na_biblioteca(...)` grava na hora, com fonte e
   data/hora, antes de devolver pra quem chamou.
4. Quando o dado veio da Perplexity, `confirmar_com_claude` (API do Claude, mesma regra de
   confiança baixa do guidance automático em `ler_com_claude`) só CONFIRMA ou CORRIGE o número que
   a Perplexity já trouxe com fonte - nunca inventa um número por conta própria. Sem confirmação
   (API fora do ar, recusa, ou número não encontrado na resposta da Perplexity), o dado não é
   salvo como confiável.

"desatualizado" (Issue #48): mais de `DIAS_DESATUALIZADO` dias desde a última pesquisa - a mesma
régua de ~1 trimestre (120 dias) já usada em `IDADE_MAXIMA_DIAS` (utils/fetch_guidance.py, trava
"documento com mais de 120 dias" do AUTOMÁTICO COM PROTEÇÃO), para não inventar um valor novo de
staleness.

REGRA TRAVADA - CONTÁBIL É SEMPRE O PRINCIPAL (REGRA 1 do TTM, ver CLAUDE.md): o PROMPT PADRÃO
pede Contábil (GAAP) e Ajustado em colunas separadas. `salvar_na_biblioteca` grava os dois campos
separados (`valor` = contábil, sempre o principal; `valor_ajustado` = ajustado, opcional).
`buscar_na_biblioteca` devolve os dois, mas quem lê este módulo (app, robô) usa `valor` como
número principal e só mostra `valor_ajustado` com a etiqueta "[Ajustado]" - nunca como padrão,
nunca misturado no mesmo cálculo com o contábil.

DIVERGÊNCIA (Issue #48, item 9): quando `salvar_na_biblioteca` grava um valor contábil diferente
do que já estava salvo, ela mesma aciona `utils.divergencia.abrir_issue_divergencia` (ver aquele
módulo) - sem travar a gravação na biblioteca se a Issue não puder ser aberta (ex.: sem
GITHUB_TOKEN em execução local): o dado novo sempre é salvo, o aviso de divergência é só um
"melhor esforço" por cima.

LIMITAÇÃO CONHECIDA (ver PR da Issue #48): não foi possível testar a chamada real à
api.perplexity.ai neste ambiente de desenvolvimento - o proxy de rede do agente não libera esse
host (só hosts explicitamente permitidos). A chave (`PERPLEXITY_API_KEY`, já salva nos Secrets do
GitHub) e o formato da chamada (`POST https://api.perplexity.ai/chat/completions`, corpo
OpenAI-compatível com `model` + `messages`) seguem a documentação pública da Perplexity, mas a
validação de ponta a ponta só é possível em produção/Actions, com o Secret configurado. Por isso
os testes deste módulo usam um `chamar`/`sessao` injetável com respostas SIMULADAS, claramente
marcadas como mock no próprio teste - nenhuma chamada de rede de verdade é feita aqui, e nenhum
dado "simulado" é tratado como se fosse um dado real.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ARQ_BIBLIOTECA = RAIZ / "utils" / "biblioteca.json"

# "desatualizado" = mais de 1 trimestre sem bater com o balanço mais recente: mesma régua de
# IDADE_MAXIMA_DIAS do guidance automático (utils/fetch_guidance.py), em vez de inventar um limite novo.
DIAS_DESATUALIZADO = 120

PERPLEXITY_URL = "https://api.perplexity.ai/chat/completions"
PERPLEXITY_MODELO = "sonar-pro"
PERPLEXITY_TIMEOUT = 60

MODELO_CLAUDE = "claude-opus-5-5"

log = logging.getLogger("biblioteca")


# ------------------------------------------------------------ arquivo (mesmo padrão dos outros caches)
def _ler(caminho: Path = ARQ_BIBLIOTECA) -> dict:
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _gravar(dados: dict, caminho: Path = ARQ_BIBLIOTECA) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


# ------------------------------------------------------------ staleness
def esta_desatualizado(registro: dict, hoje: dt.date | None = None, limite_dias: int = DIAS_DESATUALIZADO) -> bool:
    """True quando o registro não tem data/hora, está num formato inválido, ou passou de
    `limite_dias` desde a pesquisa (~1 trimestre, por padrão)."""
    hoje = hoje or dt.date.today()
    data_txt = (registro or {}).get("data_hora")
    if not data_txt:
        return True
    try:
        data = dt.datetime.strptime(data_txt[:10], "%d/%m/%Y").date()
    except ValueError:
        return True
    return (hoje - data).days > limite_dias


# ------------------------------------------------------------ leitura/gravação
def buscar_na_biblioteca(ticker: str, campo: str, hoje: dt.date | None = None, *,
                         dados: dict | None = None, caminho: Path = ARQ_BIBLIOTECA) -> dict | None:
    """Devolve o registro salvo ({"valor", "fonte", "data_hora", ...}) se existir e não estiver
    desatualizado; None caso contrário (ticker novo, campo novo, ou dado velho demais) - quem
    chama então vai buscar fora (Yahoo/SEC/CVM/Perplexity, nesta ordem)."""
    dados = dados if dados is not None else _ler(caminho)
    registro = (dados.get(ticker.upper()) or {}).get(campo)
    if not registro:
        return None
    if esta_desatualizado(registro, hoje):
        log.info("biblioteca: %s.%s desatualizado (pesquisado em %s)", ticker, campo, registro.get("data_hora"))
        return None
    return registro


def salvar_na_biblioteca(ticker: str, campo: str, valor, fonte: str, data_hora: str | None = None, *,
                         valor_ajustado=None, trimestre: str | None = None, link: str | None = None,
                         pagina: str | None = None,
                         dados: dict | None = None, caminho: Path = ARQ_BIBLIOTECA, gravar=None,
                         avisar_divergencia: bool = True, abrir_issue=None) -> dict:
    """Grava `valor` (SEMPRE o contábil - REGRA TRAVADA) + fonte + data/hora na biblioteca, com
    `valor_ajustado` opcional (nunca o principal). Devolve {"anterior": registro antigo ou None,
    "divergente": bool, "issue": resultado de abrir_issue_divergencia ou None}.

    `avisar_divergencia=True` (padrão): se já havia um valor contábil salvo e o novo é diferente
    (fora de arredondamento), aciona utils.divergencia.abrir_issue_divergencia (Issue #48, item 9)
    - best-effort: se a Issue não puder ser aberta (sem GITHUB_TOKEN, API fora do ar), o dado novo
    é salvo do mesmo jeito; só o aviso automático é que fica faltando."""
    dados = dados if dados is not None else _ler(caminho)
    gravar = gravar or (lambda d: _gravar(d, caminho))
    ticker = ticker.upper()
    data_hora = data_hora or f"{dt.datetime.now():%d/%m/%Y %H:%M}"

    registro = {"valor": valor, "fonte": fonte, "data_hora": data_hora}
    if valor_ajustado is not None:
        registro["valor_ajustado"] = valor_ajustado
    if trimestre:
        registro["trimestre"] = trimestre
    if link:
        registro["link"] = link
    if pagina:
        registro["pagina"] = pagina

    anterior = (dados.get(ticker) or {}).get(campo)
    dados.setdefault(ticker, {})[campo] = registro
    gravar(dados)

    resultado = {"anterior": anterior, "divergente": False, "issue": None}
    if avisar_divergencia and anterior is not None:
        import utils.divergencia as divergencia
        if divergencia.detectar(anterior.get("valor"), valor):
            resultado["divergente"] = True
            abrir_issue = abrir_issue or divergencia.abrir_issue_divergencia
            try:
                resultado["issue"] = abrir_issue(
                    ticker=ticker, campo=campo, salvo=anterior.get("valor"), novo=valor,
                    fonte=fonte, link=link, data_hora=data_hora, base="contábil")
            except Exception as e:  # noqa: BLE001 - aviso é best-effort, nunca derruba a gravação
                log.warning("biblioteca: não consegui abrir a issue de divergência de %s.%s (%s: %s)",
                           ticker, campo, e.__class__.__name__, e)
    return resultado


# ------------------------------------------------------------ Perplexity (PROMPT PADRÃO da Issue #48)
PROMPT_PADRAO = """Ação: {ticker} / Período: {periodo} / Comparar com trimestre anterior e mesmo tri ano anterior

Regras: Só fonte oficial RI / SEC / Earnings. Fonte + página em cada linha. Não estimar.
Se não divulgou, "Não divulgado". Trazer Contábil e Ajustado em colunas separadas.

1. NÚCLEO - SEMPRE: LPA/EPS contábil e ajustado, Lucro líquido contábil e ajustado, Receita
   total, Margem líquida, ROE, Dívida líquida / Alavancagem, Guidance atual vs anterior,
   Realizado acumulado vs guidance
2. SE FOR BANCO: Margem financeira / Net Interest Income, Carteira de crédito total e por
   segmento, Inadimplência 90 dias, PDD / Provisão e Custo do crédito, Índice de cobertura,
   Basileia / Capital, Dividendo + JCP / Payout
3. SE NÃO FOR BANCO: Receita por segmento, Margem operacional / EBITDA, Free Cash Flow,
   Recompra de ações (Buyback)

Formato: Tabela: Indicador | Tri Atual Contábil | Tri Atual Ajustado | Tri Anterior |
Mesmo Tri Ano Ant | Var Tri % | Var Anual % | Acumulado Ano Atual | Acumulado Ano Ant |
Fonte / Página"""


def montar_prompt_perplexity(ticker: str, periodo: str) -> str:
    """O PROMPT PADRÃO da Issue #48, usado literalmente (só {ticker}/{periodo} substituídos)."""
    return PROMPT_PADRAO.format(ticker=ticker, periodo=periodo)


def pesquisar_via_perplexity(ticker: str, periodo: str, *, chamar=None) -> dict | None:
    """Pesquisa um dado fundamentalista pela Perplexity, com o PROMPT PADRÃO acima. Devolve
    {"prompt": ..., "resposta": texto da tabela devolvida} ou None (sem PERPLEXITY_API_KEY, ou a
    API falhou/não respondeu no formato esperado). Nunca inventa número: a resposta ainda precisa
    passar por `confirmar_com_claude` antes de ser salva na biblioteca."""
    prompt = montar_prompt_perplexity(ticker, periodo)
    if chamar is None:
        chave = os.environ.get("PERPLEXITY_API_KEY")
        if not chave:
            log.info("biblioteca: sem PERPLEXITY_API_KEY (Secret do GitHub): Perplexity desligada")
            return None
        import requests

        def chamar(prompt_texto: str) -> str | None:
            try:
                r = requests.post(
                    PERPLEXITY_URL, timeout=PERPLEXITY_TIMEOUT,
                    headers={"Authorization": f"Bearer {chave}", "Content-Type": "application/json"},
                    json={"model": PERPLEXITY_MODELO, "messages": [{"role": "user", "content": prompt_texto}]})
                r.raise_for_status()
            except Exception as e:  # noqa: BLE001
                log.warning("biblioteca: Perplexity falhou (%s: %s)", e.__class__.__name__, e)
                return None
            try:
                return r.json()["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError, ValueError):
                log.warning("biblioteca: resposta da Perplexity fora do formato esperado")
                return None
    resposta = chamar(prompt)
    if not resposta:
        return None
    return {"prompt": prompt, "resposta": resposta, "ticker": ticker, "periodo": periodo}


ESQUEMA_CONFIRMACAO_CLAUDE = {
    "type": "object",
    "properties": {
        "achou": {"type": "boolean"},
        "valor_contabil": {"anyOf": [{"type": "number"}, {"type": "null"}]},
        "valor_ajustado": {"anyOf": [{"type": "number"}, {"type": "null"}]},
        "fonte": {"type": "string"},
        "link": {"type": "string"},
        "pagina": {"type": "string"},
        "trecho": {"type": "string"},
    },
    "required": ["achou", "valor_contabil", "valor_ajustado", "fonte", "link", "pagina", "trecho"],
    "additionalProperties": False,
}

INSTRUCAO_CONFIRMACAO_CLAUDE = """Você recebe a resposta de uma pesquisa (Perplexity) sobre {ticker}, e o indicador "{campo}".
Sua única tarefa é CONFIRMAR ou CORRIGIR o número de {campo} que já está nessa resposta - nunca
invente ou calcule um número que não esteja escrito no texto.

REGRA TRAVADA (27/11/2026): só confirma um número de FONTE OFICIAL - RI da própria empresa, SEC
EDGAR, CVM ou B3. Sem fonte oficial (ex.: notícia de jornal, agregador de dados, opinião de
analista sem documento oficial por trás), ou sem link + página dessa fonte: achou = false, mesmo
que o texto tenha um número - nunca confirma um número sem conseguir apontar o link e a página de
onde ele saiu.

Regras:
- achou = true só se o texto tiver um número de {campo} com fonte OFICIAL citada (RI/SEC/CVM/B3),
  E com link da fonte, E com a página/seção onde o número aparece.
- valor_contabil: o número CONTÁBIL/GAAP (nunca o ajustado) de {campo}. valor_ajustado: o número
  ajustado/non-GAAP, se o texto trouxer os dois separados; null se só trouxer um - NUNCA misture
  os dois no mesmo campo.
- fonte: a fonte citada no texto (ex.: "RI, release 3T26").
- link: a URL da fonte oficial citada no texto (ex.: "https://ri.bb.com.br/..."). Sem link na
  resposta: achou = false.
- pagina: a página/seção citada no texto (ex.: "página 4", "Exhibit 99.1"). Sem página na
  resposta: achou = false.
- trecho: copie EXATAMENTE a linha da tabela ou frase de onde tirou o número.
- Sem um número de {campo} com fonte oficial + link + página no texto: achou = false e todos os
  campos null/"" (nunca "Não divulgado" como se fosse um valor - isso é texto de exibição de quem
  chama, não um dado desta função).

Resposta da pesquisa:
{resposta}"""


def confirmar_com_claude(resposta_perplexity: dict, ticker: str, campo: str, chamar=None) -> dict | None:
    """2ª camada (mesma regra de confiança baixa do guidance automático): a API do Claude só
    confirma/corrige o {campo} que a Perplexity já trouxe com fonte, dentro do próprio texto
    devolvido - nunca calcula ou estima um valor por conta própria. Devolve
    {"valor", "valor_ajustado", "fonte", "link", "pagina", "trecho"} ou None (sem confiança, sem
    chave, API falhou, ou número sem fonte OFICIAL + link + página na resposta - REGRA TRAVADA
    27/11/2026: Perplexity só alimenta número com fonte oficial citada; sem isso, nunca salva)."""
    texto = (resposta_perplexity or {}).get("resposta", "")
    if chamar is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            log.info("biblioteca: sem ANTHROPIC_API_KEY: confirmação pela API do Claude desligada")
            return None
        import anthropic

        client = anthropic.Anthropic()

        def chamar(instrucao: str) -> str | None:
            try:
                r = client.beta.messages.create(
                    model=MODELO_CLAUDE, max_tokens=4000,
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default",
                    output_config={"format": {"type": "json_schema", "schema": ESQUEMA_CONFIRMACAO_CLAUDE}},
                    messages=[{"role": "user", "content": instrucao}])
            except Exception as e:  # noqa: BLE001
                log.error("biblioteca: API do Claude falhou na confirmação (%s: %s)", e.__class__.__name__, e)
                return None
            if r.stop_reason in ("refusal", "max_tokens"):
                log.error("biblioteca: API do Claude não concluiu a confirmação (%s)", r.stop_reason)
                return None
            return next((b.text for b in r.content if b.type == "text"), "")
    bruto = chamar(INSTRUCAO_CONFIRMACAO_CLAUDE.format(ticker=ticker, campo=campo, resposta=texto))
    if not bruto:
        return None
    try:
        dados = json.loads(bruto)
    except json.JSONDecodeError:
        log.error("biblioteca: resposta da API do Claude fora do formato esperado")
        return None
    if not dados.get("achou") or dados.get("valor_contabil") is None:
        log.info("biblioteca: API do Claude não confirmou um valor de %s para %s", campo, ticker)
        return None
    # REGRA TRAVADA: sem link ou sem página da fonte oficial, não é dado confiável - nunca salva
    link = (dados.get("link") or "").strip()
    pagina = (dados.get("pagina") or "").strip()
    if not link or not pagina:
        log.info("biblioteca: %s de %s sem link+página de fonte oficial - não confirmado", campo, ticker)
        return None
    # o trecho tem de existir mesmo na resposta da Perplexity - senão pode ter sido inventado
    trecho = (dados.get("trecho") or "").strip()
    if len(trecho) >= 10 and trecho not in texto:
        log.error("biblioteca: API do Claude devolveu um trecho que não está na resposta da Perplexity: descartado")
        return None
    return {"valor": dados["valor_contabil"], "valor_ajustado": dados.get("valor_ajustado"),
           "fonte": dados.get("fonte") or "Perplexity (confirmado pela API do Claude)",
           "link": link, "pagina": pagina, "trecho": trecho}


def obter(ticker: str, campo: str, periodo: str, hoje: dt.date | None = None, *,
         buscar_externo=None, chamar_perplexity=None, chamar_claude=None,
         dados: dict | None = None, caminho: Path = ARQ_BIBLIOTECA) -> dict | None:
    """Ponto de entrada único: biblioteca primeiro, rede depois (Issue #48, item 8).

    1. Já tem na biblioteca e não está desatualizado -> devolve o registro salvo.
    2. Senão, tenta `buscar_externo(ticker, campo)` se foi passado (ex.: SEC/CVM/RI, na mesma
       ordem de fonte já definida no projeto) - quando ele devolver um dado, salva e devolve.
    3. Sem `buscar_externo`, ou ele não achou nada (incluindo "o Yahoo quebrou"): tenta a
       Perplexity + confirmação da API do Claude; achando, salva e devolve.
    4. Nada disso achou -> None (nunca inventa número; quem chama mostra "Sem dado")."""
    hoje = hoje or dt.date.today()
    dados = dados if dados is not None else _ler(caminho)
    salvo = buscar_na_biblioteca(ticker, campo, hoje, dados=dados)
    if salvo:
        return salvo

    if buscar_externo is not None:
        try:
            achado = buscar_externo(ticker, campo)
        except Exception as e:  # noqa: BLE001 - "o Yahoo quebrou": cai para a Perplexity, não propaga o erro
            log.warning("biblioteca: busca externa de %s.%s falhou (%s: %s); tentando a Perplexity",
                       ticker, campo, e.__class__.__name__, e)
            achado = None
        if achado:
            salvar_na_biblioteca(ticker, campo, achado["valor"], achado["fonte"],
                                 valor_ajustado=achado.get("valor_ajustado"), link=achado.get("link"),
                                 dados=dados, caminho=caminho)
            return buscar_na_biblioteca(ticker, campo, hoje, dados=dados)

    resposta = pesquisar_via_perplexity(ticker, periodo, chamar=chamar_perplexity)
    if not resposta:
        return None
    confirmado = confirmar_com_claude(resposta, ticker, campo, chamar=chamar_claude)
    if not confirmado:
        return None
    salvar_na_biblioteca(ticker, campo, confirmado["valor"],
                         f"Perplexity, confirmado pela API do Claude ({confirmado['fonte']})",
                         valor_ajustado=confirmado.get("valor_ajustado"), link=confirmado.get("link"),
                         pagina=confirmado.get("pagina"), dados=dados, caminho=caminho)
    return buscar_na_biblioteca(ticker, campo, hoje, dados=dados)


# ------------------------------------------------------------ workflow (.github/workflows/biblioteca-perplexity.yml)
def _periodo_atual(hoje: dt.date) -> str:
    """"3T26", no mesmo formato do resto do projeto (trimestre civil - aproximação razoável pro
    PROMPT PADRÃO, que já pede pra Perplexity comparar com o trimestre anterior)."""
    tri = (hoje.month - 1) // 3 + 1
    return f"{tri}T{hoje:%y}"


def atualizar_tickers(tickers: list[str], campo: str = "lpa_atual", hoje: dt.date | None = None, *,
                      caminho: Path = ARQ_BIBLIOTECA, buscar_externo=None,
                      chamar_perplexity=None, chamar_claude=None) -> list[dict]:
    """Roda pelo workflow novo (biblioteca-perplexity.yml): para cada ticker, biblioteca primeiro,
    rede depois (`obter`) - sem inventar nada quando nenhuma fonte (biblioteca/externa/Perplexity)
    tem o dado. `buscar_externo`, quando passado, entra ANTES da Perplexity (ex.: as mesmas
    funções de SEC/CVM que o resto do projeto já usa) - None aqui pula direto pra Perplexity, que
    é o alvo específico da Issue #48, item 8."""
    hoje = hoje or dt.date.today()
    periodo = _periodo_atual(hoje)
    resultados = []
    for ticker in tickers:
        try:
            achado = obter(ticker, campo, periodo, hoje, caminho=caminho, buscar_externo=buscar_externo,
                           chamar_perplexity=chamar_perplexity, chamar_claude=chamar_claude)
        except Exception as e:  # noqa: BLE001 - 1 ticker com erro não derruba os outros
            log.warning("biblioteca: %s.%s falhou (%s: %s)", ticker, campo, e.__class__.__name__, e)
            achado = None
        resultados.append({"ticker": ticker, "campo": campo, "achado": bool(achado),
                          "valor": (achado or {}).get("valor")})
        log.info("biblioteca: %s.%s -> %s", ticker, campo, (achado or {}).get("valor", "sem dado"))
    return resultados


def main(argv: list[str] | None = None) -> int:
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    p = argparse.ArgumentParser(description="Biblioteca própria de dados fundamentalistas (Issue #48, item 8)")
    sub = p.add_subparsers(dest="cmd", required=True)
    pa = sub.add_parser("atualizar", help="biblioteca -> Perplexity -> confirmação da API do Claude, por ticker")
    pa.add_argument("--tickers", required=True, help="arquivo JSON com a lista de tickers (ex.: utils/guidance_tickers.json)")
    pa.add_argument("--campo", default="lpa_atual")
    pa.add_argument("--ticker", default=None,
                    help="processa só este ticker (tem de estar no arquivo de --tickers) - pra testar um "
                         "ticker isolado (ex.: Run workflow manual) ou pro gatilho por Issue/fila de um só ticker, "
                         "sem gastar chamada de API nos outros")
    args = p.parse_args(argv)
    if args.cmd == "atualizar":
        tickers = json.loads(Path(args.tickers).read_text(encoding="utf-8"))
        if args.ticker:
            alvo = args.ticker.upper()
            tickers = [t for t in tickers if t.upper() == alvo]
            if not tickers:
                log.error("biblioteca: %s não está em %s", alvo, args.tickers)
                return 1
        resultados = atualizar_tickers(tickers, args.campo)
        achados = sum(r["achado"] for r in resultados)
        log.info("biblioteca: %d ticker(s) processado(s), %d com dado novo/confirmado", len(resultados), achados)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
