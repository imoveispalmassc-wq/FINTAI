"""Busca automática de guidance oficial (projeção de lucro) das empresas da B3 e dos EUA.

Roda todo dia pelo GitHub Actions (.github/workflows/update-guidance.yml):

    python -m utils.fetch_guidance planejar --saida plano.json
    python -m utils.fetch_guidance aplicar plano.json --tipo commit
    python -m utils.fetch_guidance aplicar plano.json --tipo pr --resumo pr.md
    python -m utils.fetch_guidance resumo --dias 7 --saida resumo.md     (toda sexta)

Fluxo por ticker (lista em utils/guidance_tickers.json):
1. Acha o CNPJ pelo ticker no cadastro aberto da CVM (FCA, valores mobiliários).
2. Lista os documentos entregues à CVM (IPE: fatos relevantes, comunicados, resultados), do mais
   novo para o mais antigo. São os mesmos documentos que a B3 e o RI da empresa divulgam.
3. Lê o PDF e procura a faixa de lucro líquido projetada:
   a) primeiro por padrões de texto (grátis);
   b) só se os padrões acharem a faixa mas sem confiança, pede à API do Claude (precisa da
      variável ANTHROPIC_API_KEY, guardada nos Secrets do GitHub). O trecho devolvido tem de
      existir no documento, senão o resultado é descartado.
4. Decide como publicar (AUTOMÁTICO COM PROTEÇÃO, função avaliar_travas):
   - "commit" (publica sozinho e abre um aviso "Guidance publicado") só se passar nas 4 travas:
     1) fonte é o comunicado oficial da empresa (documento entregue à CVM ou 8-K/6-K na SEC);
     2) a mesma faixa aparece em 2 lugares do documento (texto e tabela);
     3) o LPA projetado mudou no máximo 20% contra o guidance que está no app;
     4) o P/L resultante é positivo e não absurdo contra o P/L de 12 meses do Yahoo;
     e sem dúvida: projeção do ano certo e documento com até 120 dias.
   - "pr" (travado): falhou alguma trava ou ficou dúvida. Não grava no app: abre um pull request
     explicando o que travou, e só entra se você aprovar.
   - nada muda quando não acha guidance ou não tem confiança: só registra no log.
   Cada decisão vai para utils/guidance_log.json, de onde sai o resumo de sexta (comando resumo).

O resultado vai para utils/guidance_auto.json, que utils/override.py lê. Um cadastro manual em
override.py sempre ganha do automático.

Ações dos EUA (ticker sem número, ex.: ADM, HSIC): SEC EDGAR. O robô lista os 8-K (e 6-K de empresas
estrangeiras) com o comunicado de resultados anexo (Exhibit 99.1, o mesmo press release da empresa) e
procura a faixa de LPA projetado ("adjusted EPS of $5.50 to $5.80") e o dividendo trimestral.
A SEC exige e-mail de contato no User-Agent: vem só da variável SEC_CONTACT_EMAIL (Secret do GitHub),
nunca do código. Sem ela, os tickers dos EUA ficam de fora com aviso no log.
"""
from __future__ import annotations

import argparse
import base64
import csv
import datetime as dt
import io
import json
import logging
import os
import re
import unicodedata
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ARQ_AUTO = RAIZ / "utils" / "guidance_auto.json"
ARQ_TICKERS = RAIZ / "utils" / "guidance_tickers.json"
ARQ_INICIAL = RAIZ / "utils" / "guidance_inicial.json"
ARQ_VISTOS = RAIZ / ".guidance_cache" / "vistos.json"   # persistido pelo cache do GitHub Actions

CVM = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC"
CABECALHO = {"User-Agent": "fintai-guidance/1.0 (+https://github.com/imoveispalmassc-wq/fintai)"}
LIMITE_AUTO = 0.20           # trava 3: publica sozinho só com variação do LPA projetado de até 20%
PL_MAXIMO = 100              # trava 4: P/L acima disso é absurdo
PL_FATOR = 3                 # trava 4: P/L novo fora de 1/3 a 3x o P/L de 12 meses do Yahoo é absurdo
ARQ_LOG = RAIZ / "utils" / "guidance_log.json"
ARQ_NAO_VALIDADO = RAIZ / "utils" / "queue_nao_validado.json"   # tickers da fila pública que não validaram
FILA_MAX_POR_RUN = 15    # tickers novos processados por execução, para não estourar o tempo do Actions
ARQ_OUTLOOK_TRI = RAIZ / "utils" / "guidance_trimestral_eua.json"   # guidance trimestral, só informativo
IDADE_MAXIMA_DIAS = 120      # documento mais velho que isso (mais de um trimestre) vai para revisão
MAX_DOCUMENTOS = 6           # documentos lidos por ticker, do mais novo para o mais antigo
MODELO = "claude-opus-5-5"

log = logging.getLogger("guidance")


# ------------------------------------------------------------ texto
def normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKC", texto or "").replace(" ", " ")
    return re.sub(r"\s+", " ", texto).strip()


def sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn").lower()


def numero_br(s: str) -> float:
    """'18,5' -> 18.5; '1.234,5' -> 1234.5; '18.5' -> 18.5; '1.234' -> 1234."""
    s = s.strip()
    if "," in s:
        return float(s.replace(".", "").replace(",", "."))
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        return float(s.replace(".", ""))
    return float(s)


def multiplicador(unidade: str | None) -> float | None:
    u = sem_acento(unidade or "")
    if u.startswith(("bilh", "bi")):
        return 1e9
    if u.startswith(("milh", "mi")):
        return 1e6
    return None


# ------------------------------------------------------------ extração por padrões de texto
@dataclass
class Extracao:
    lucro_min: float | None = None
    lucro_max: float | None = None
    payout: float | None = None
    ano: int | None = None
    trecho: str = ""
    confianca: str = "baixa"            # "alta" | "baixa"
    metodo: str = "padrões de texto"     # "padrões de texto" | "API do Claude"
    motivos: list[str] = field(default_factory=list)
    candidatos: int = 0                  # faixas de lucro distintas encontradas
    faixas: list = field(default_factory=list)   # todas as faixas (mín., máx.) achadas no documento
    historico: list = field(default_factory=list)   # até 4 guidances anteriores devolvidos pela API do Claude


RE_LUCRO = re.compile(r"lucro\s+l[ií]quido(?:\s+(?:ajustado|recorrente|cont[áa]bil|gerencial))?", re.I)
UNID = r"(bilh[õo]es|bilh[ãa]o|bi\b|milh[õo]es|milh[ãa]o|mi\b)"
NUM = r"(\d{1,3}(?:\.\d{3})*(?:,\d{1,2})?|\d+(?:\.\d{1,2})?)"
RE_FAIXA = re.compile(
    rf"(?:R\$\s*)?{NUM}\s*{UNID}?\s*(?:a|e|at[ée]|-|–|—)\s*(?:R\$\s*)?{NUM}\s*{UNID}?", re.I)
RE_UNIDADE_SOLTA = re.compile(rf"R\$\s*{UNID}|\(\s*R\$\s*{UNID}\s*\)|em\s+{UNID}\s+de\s+reais", re.I)
RE_ANO = re.compile(r"(?:guidance|proje[cç](?:[õo]es|[ãa]o)|estimativas?|perspectivas?)[^.]{0,80}?\b(20\d{2})\b", re.I)
RE_ANO_SOLTO = re.compile(r"\b(20\d{2})\b")
RE_PAYOUT = re.compile(
    r"payout[^%\d]{0,80}?(\d{1,3}(?:,\d+)?)\s*%(?:\s*(?:a|e|-|–)\s*(\d{1,3}(?:,\d+)?)\s*%)?", re.I)
RAIO_ANO_VIZINHANCA = 500   # caracteres antes/depois da faixa, no fallback de ano (trava 2 do pedido)


def _ano_unico(trecho: str) -> int | None:
    """Um único ano (20xx) claro no trecho; None se não achar nenhum ou achar mais de um diferente
    (nunca inventa: só usa quando não há ambiguidade)."""
    anos = {int(a) for a in RE_ANO_SOLTO.findall(trecho)}
    return anos.pop() if len(anos) == 1 else None


def extrair_por_padroes(texto: str, ano_alvo: int, titulo: str = "") -> Extracao | None:
    """Faixa de lucro líquido projetada, ano e payout. None se o texto não traz faixa de lucro.

    titulo: categoria/tipo/assunto do documento na CVM, usado só no fallback de ano (ver abaixo)."""
    t = normalizar(texto)
    titulo = normalizar(titulo)
    faixas: dict[tuple[float, float], str] = {}
    posicoes: dict[tuple[float, float], int] = {}   # posição em `t` de cada faixa, para o fallback de ano
    revisao = False
    for m in RE_LUCRO.finditer(t):
        janela = t[m.start(): m.start() + 260]
        antes = t[max(0, m.start() - 300): m.start()]

        def mult_de(f):
            mult = multiplicador(f.group(4) or f.group(2))
            if mult is None:                     # unidade de cabeçalho de tabela: "(R$ bilhões)"
                u = RE_UNIDADE_SOLTA.search(janela) or RE_UNIDADE_SOLTA.search(antes)
                mult = multiplicador(next((g for g in u.groups() if g), None)) if u else None
            return mult

        pos = 0
        achou = False
        while True:
            f = RE_FAIXA.search(janela, pos)
            if not f:
                break
            # depois da primeira faixa, só contam as faixas coladas a ela (mesma linha de tabela,
            # ex.: "18 a 22  9 a 11" = anterior e revisada); texto no meio encerra a menção
            if achou and janela[pos:f.start()].strip(" ;,/|()") != "":
                break
            mult = mult_de(f)
            pos = f.end()
            if mult is None:
                if achou:
                    break
                continue
            a, b = numero_br(f.group(1)) * mult, numero_br(f.group(3)) * mult
            if not (0 < a <= b <= a * 2):        # faixa de guidance: mínimo <= máximo, no máximo o dobro
                if achou:
                    break
                continue
            faixas.setdefault((a, b), janela[: f.end()].strip())
            posicoes.setdefault((a, b), m.start())
            achou = True
        if achou and re.search(r"anterior|revis|atualiza", antes[-160:] + janela, re.I):
            revisao = True
    if not faixas:
        return None

    ex = Extracao(candidatos=len(faixas), faixas=list(faixas))
    (ex.lucro_min, ex.lucro_max), ex.trecho = next(iter(faixas.items()))
    if len(faixas) > 1:
        ex.motivos.append(f"{len(faixas)} faixas de lucro diferentes no documento (ex.: anterior e revisada)")
    if revisao:
        ex.motivos.append("documento fala em projeção anterior ou revisada")

    ano_por_fallback = False
    anos = {int(a) for a in RE_ANO.findall(t)}
    if ano_alvo in anos:
        ex.ano = ano_alvo
    elif anos:
        ex.ano = max(anos)
        ex.motivos.append(f"projeção para {ex.ano}, não para {ano_alvo}")
    else:
        # não achou o ano perto de "guidance/projeção/...": tenta 2 lugares extras, nessa ordem, antes
        # de desistir (só usa se achar um ÚNICO ano claro em cada um; nunca inventa). Mesmo achando,
        # a confiança continua baixa (abaixo) — vai sempre para a 2ª camada confirmar, nunca publica sozinho.
        pos = posicoes.get((ex.lucro_min, ex.lucro_max), 0)
        vizinhanca = t[max(0, pos - RAIO_ANO_VIZINHANCA): pos + RAIO_ANO_VIZINHANCA]
        achado, onde = _ano_unico(titulo), "no título/cabeçalho do documento"
        if achado is None:
            achado, onde = _ano_unico(vizinhanca), "perto da faixa encontrada"
        if achado is not None:
            ex.ano, ano_por_fallback = achado, True
            ex.motivos.append(f"ano {achado} achado {onde} (não perto de 'guidance/projeção'): confirma pela API do Claude")
        else:
            ex.motivos.append("ano da projeção não encontrado")

    payouts = set()
    for p in RE_PAYOUT.finditer(t):
        v1 = numero_br(p.group(1))
        v2 = numero_br(p.group(2)) if p.group(2) else v1
        payouts.add(round((v1 + v2) / 2 / 100, 4))
    payouts = {p for p in payouts if 0 < p <= 1}
    if len(payouts) == 1:
        ex.payout = payouts.pop()
    elif len(payouts) > 1:
        ex.motivos.append("mais de um payout no documento: payout não usado")

    ex.confianca = "alta" if len(faixas) == 1 and ex.ano == ano_alvo and not revisao and not ano_por_fallback else "baixa"
    return ex


# ------------------------------------------------------------ API do Claude (só quando os padrões falham)
ESQUEMA_CLAUDE = {
    "type": "object",
    "properties": {
        "tem_guidance": {"type": "boolean"},
        "ano": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
        "lucro_min": {"anyOf": [{"type": "number"}, {"type": "null"}]},
        "lucro_max": {"anyOf": [{"type": "number"}, {"type": "null"}]},
        "lpa_min": {"anyOf": [{"type": "number"}, {"type": "null"}]},
        "lpa_max": {"anyOf": [{"type": "number"}, {"type": "null"}]},
        "payout": {"anyOf": [{"type": "number"}, {"type": "null"}]},
        "trecho": {"type": "string"},
        "pagina": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
        "historico": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "lpa_min": {"anyOf": [{"type": "number"}, {"type": "null"}]},
                    "lpa_max": {"anyOf": [{"type": "number"}, {"type": "null"}]},
                    "lucro_min": {"anyOf": [{"type": "number"}, {"type": "null"}]},
                    "lucro_max": {"anyOf": [{"type": "number"}, {"type": "null"}]},
                    "ano": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
                    "trecho_curto": {"type": "string"}
                },
                "required": ["lpa_min", "lpa_max", "lucro_min", "lucro_max", "ano", "trecho_curto"],
                "additionalProperties": False
            }
        }
    },
    "required": ["tem_guidance", "ano", "lucro_min", "lucro_max", "lpa_min", "lpa_max", "payout", "trecho", "pagina", "historico"],
    "additionalProperties": False,
}

INSTRUCAO_CLAUDE = """Você lê um documento oficial de uma empresa ({origem}) e extrai o guidance (projeção oficial da própria empresa) de LUCRO para o ano {ano}. Responda só com o JSON pedido.

REGRA DE OURO - HISTÓRICO ÚLTIMOS 4 / JANELA DESLIZANTE:
1. Você sempre devolve o histórico dos últimos 4 guidances em ordem cronológica.
2. Nunca reescreva o histórico antigo. Cada trimestre é um registro separado.
3. Quando entra 1 novo, sai o mais antigo. Só o ÚLTIMO registro é o guidance atual.
4. Os 3 anteriores servem SÓ para comparar se o pulo faz sentido.
   Ex: $7.50 -> $9.90 -> $10.65 = subida gradual = OK
   Ex: $8.00 -> $20.00 = pulo suspeito = NÃO CONFIRMAR
5. Se o documento traz "previously expected $7.50 to $7.80, now expects $9.90 to $10.65",
   então o histórico termina com [..., {{antigo: 7.50-7.80}}, {{novo: 9.90-10.65}}].
6. Se o documento só traz 1 guidance, devolva historico com 1 item só. Não invente os outros 3.

Regras:
- Use só o que está escrito no documento. Não estime, não calcule e não complete nada.
- Projeção de analistas, consenso de mercado ou resultado já realizado NÃO é guidance.
- Se houver projeção anterior e revisada, use a VIGENTE (a mais recente/revisada) como ÚLTIMO registro.
- lucro_min / lucro_max: lucro líquido projetado, na moeda do documento e em unidades por extenso
  (R$ 9 bilhões = 9000000000). Se a empresa projeta lucro por ação, use lpa_min / lpa_max (ex.: 5.50 e 5.80)
  e deixe lucro_min / lucro_max como null. Valor único: repita nos dois campos.
- payout: fração do lucro distribuída (30% = 0.30), só se o documento disser; senão null.
- trecho: copie EXATAMENTE, palavra por palavra, a frase ou linha de tabela de onde tirou a faixa ATUAL.
- pagina: número da página do PDF onde está o trecho (1 = primeira); null se não souber.
- historico: lista com até 4 itens. O último item TEM QUE SER igual ao guidance atual (lpa_min/lpa_max ou lucro_min/lucro_max).
- Sem guidance de lucro para {ano}: tem_guidance = false e todos os números null, historico = []."""



def _historico_txt(historico: list[dict]) -> str:
    """"LPA 7.50 a 7.80 (2026) -> LPA 9.90 a 10.65 (2026)", do mais antigo para o mais novo."""
    def item(h):
        if h.get("lpa_min") is not None:
            return f"LPA {h['lpa_min']:.2f} a {h['lpa_max']:.2f} ({h.get('ano')})"
        if h.get("lucro_min") is not None:
            return f"R$ {h['lucro_min'] / 1e9:.1f} a {h['lucro_max'] / 1e9:.1f} bi ({h.get('ano')})".replace(".", ",")
        return "?"
    return " -> ".join(item(h) for h in historico or [])


def _historico_bate_com_atual(historico: list[dict], a: float, b: float, campo: str) -> bool:
    """O último item do histórico devolvido pela API tem de ser o próprio guidance atual (mesma faixa);
    senão a API não seguiu a própria regra e a leitura não é confiável."""
    if not historico:
        return True                     # schema aceita 0 itens quando tem_guidance é novo/único; nada para conferir
    ultimo = historico[-1]
    x, y = ultimo.get(f"{campo}_min"), ultimo.get(f"{campo}_max")
    return x is not None and y is not None and abs(x - a) <= 0.01 * a and abs(y - b) <= 0.01 * b


def _so_letras_numeros(texto: str) -> str:
    return re.sub(r"[^a-z0-9]", "", sem_acento(texto))


def _confere(a: float, b: float, texto: str, trecho: str, faixas_do_documento) -> str | None:
    """Como a faixa devolvida pela API foi conferida no documento; None se não foi.

    1. A faixa é uma das que os padrões de texto acharam no próprio documento (mais forte).
    2. O trecho existe no documento, ignorando espaços, acentos e separadores de tabela."""
    for x, y in faixas_do_documento or []:
        if abs(x - a) <= 0.005 * a and abs(y - b) <= 0.005 * b:
            return "faixa encontrada no documento pelos padrões de texto"
    pedaco = _so_letras_numeros(trecho)[:80]
    if len(pedaco) >= 20 and pedaco in _so_letras_numeros(texto):
        return "trecho encontrado no documento"
    return None


def ler_com_claude(pdf: bytes | None, texto: str, ano_alvo: int, origem: str, chamar=None) -> dict | None:
    """2ª camada: pede à API do Claude o guidance em JSON (lucro_min, lucro_max, lpa_min, lpa_max, payout, trecho,
    pagina). A chave vem só de ANTHROPIC_API_KEY (Secret do GitHub) e nunca vai para o log.
    Devolve o JSON lido ou None (sem chave, erro da API, recusa ou sem guidance)."""
    if chamar is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            log.info("  sem ANTHROPIC_API_KEY: leitura pela API do Claude desligada")
            return None
        import anthropic

        client = anthropic.Anthropic()

        def chamar(conteudo):
            try:
                resposta = client.beta.messages.create(
                    model=MODELO, max_tokens=16000,
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default",
                    output_config={"format": {"type": "json_schema", "schema": ESQUEMA_CLAUDE}},
                    messages=[{"role": "user", "content": conteudo}],
                )
            except anthropic.APIStatusError as e:
                log.error("  API do Claude recusou a chamada (%s): %s", e.status_code, e.message)
                return None
            except anthropic.APIConnectionError:
                log.error("  API do Claude fora do alcance")
                return None
            if resposta.stop_reason in ("refusal", "max_tokens"):
                log.error("  API do Claude não concluiu a leitura (%s)", resposta.stop_reason)
                return None
            return next((b.text for b in resposta.content if b.type == "text"), "")
    conteudo = []
    if pdf and pdf.lstrip().startswith(b"%PDF") and len(pdf) < 30 * 1024 * 1024:
        conteudo.append({"type": "document", "source": {
            "type": "base64", "media_type": "application/pdf", "data": base64.standard_b64encode(pdf).decode()}})
    else:
        conteudo.append({"type": "text", "text": texto[:400_000]})
    conteudo.append({"type": "text", "text": INSTRUCAO_CLAUDE.format(ano=ano_alvo, origem=origem)})
    bruto = chamar(conteudo)
    if not bruto:
        return None
    try:
        dados = json.loads(bruto)
    except json.JSONDecodeError:
        log.error("  resposta da API do Claude fora do formato")
        return None
    if not dados.get("tem_guidance"):
        log.info("  API do Claude: documento sem guidance para %s", ano_alvo)
        return None
    return dados


def extrair_com_claude(pdf: bytes, texto: str, ano_alvo: int, faixas_do_documento=(), chamar=None) -> Extracao | None:
    """B3: faixa de LUCRO pela API do Claude, aceita só se conferida no documento."""
    dados = ler_com_claude(pdf, texto, ano_alvo, "brasileira, documento entregue à CVM", chamar)
    if not dados:
        return None
    a, b, trecho = dados.get("lucro_min"), dados.get("lucro_max"), normalizar(dados.get("trecho", ""))
    if not (a and b and 0 < a <= b <= a * 2):
        log.error("  API do Claude devolveu faixa de lucro inválida: %s a %s", a, b)
        return None
    historico = dados.get("historico") or []
    if not _historico_bate_com_atual(historico, a, b, "lucro"):
        log.error("  API do Claude: o último item do histórico não bate com a faixa atual devolvida "
                  "(%s): descartado", _historico_txt(historico))
        return None
    # a faixa tem de estar no documento: sem isso, o número pode ter sido inventado
    conferido = _confere(float(a), float(b), texto, trecho, faixas_do_documento)
    if not conferido:
        log.error("  API do Claude leu R$ %.1f a %.1f bi, mas a faixa não foi encontrada no documento: descartado",
                  a / 1e9, b / 1e9)
        return None
    log.info("  API do Claude leu R$ %.1f a %.1f bi (%s, página %s); histórico: %s", a / 1e9, b / 1e9,
             conferido, dados.get("pagina"), _historico_txt(historico) or "só a faixa atual")
    payout = dados.get("payout")
    motivos = [f"lido pela API do Claude ({conferido}, página {dados.get('pagina')}): precisa de revisão"]
    if len(historico) > 1:
        motivos.append(f"histórico devolvido pela API: {_historico_txt(historico)}")
    return Extracao(lucro_min=float(a), lucro_max=float(b),
                    payout=float(payout) if payout is not None and 0 < payout <= 1 else None,
                    ano=dados.get("ano"), trecho=trecho[:400], confianca="baixa", metodo="API do Claude",
                    motivos=motivos, candidatos=1, historico=historico)


def extrair_eps_com_claude(texto: str, ano_alvo: int, chamar=None) -> dict | None:
    """EUA: faixa de LPA pela API do Claude no press release; aceita só se o trecho estiver no documento."""
    dados = ler_com_claude(None, texto, ano_alvo, "dos EUA, press release no 8-K/6-K da SEC", chamar)
    if not dados:
        return None
    a, b, trecho = dados.get("lpa_min"), dados.get("lpa_max"), normalizar(dados.get("trecho", ""))
    if not (a and b and 0 < a <= b <= a * 2):
        log.error("  API do Claude devolveu faixa de LPA inválida: %s a %s", a, b)
        return None
    historico = dados.get("historico") or []
    if not _historico_bate_com_atual(historico, a, b, "lpa"):
        log.error("  API do Claude: o último item do histórico não bate com a faixa atual devolvida "
                  "(%s): descartado", _historico_txt(historico))
        return None
    pedaco = _so_letras_numeros(trecho)[:80]
    if len(pedaco) < 15 or pedaco not in _so_letras_numeros(texto):
        log.error("  API do Claude leu LPA %.2f a %.2f, mas o trecho não está no documento: descartado", a, b)
        return None
    log.info("  API do Claude leu LPA %.2f a %.2f (trecho conferido); histórico: %s", a, b,
             _historico_txt(historico) or "só a faixa atual")
    return {"lpa_min": float(a), "lpa_max": float(b), "ano": dados.get("ano") or ano_alvo, "trecho": trecho[:400],
            "pagina": dados.get("pagina"), "payout": dados.get("payout"), "historico": historico}


# ------------------------------------------------------------ CVM (dados abertos)
def _get(url: str, **kw):
    import requests

    r = requests.get(url, headers=CABECALHO, timeout=60, **kw)
    r.raise_for_status()
    return r


def _csv_do_zip(url: str, nome_contem: str) -> list[dict]:
    z = zipfile.ZipFile(io.BytesIO(_get(url).content))
    nome = next(n for n in z.namelist() if nome_contem in n)
    with z.open(nome) as f:
        linhas = csv.DictReader(io.TextIOWrapper(f, encoding="latin-1"), delimiter=";")
        return [{k.strip().lower(): (v or "").strip() for k, v in linha.items() if k} for linha in linhas]


def _campo(linha: dict, *pedacos: str) -> str:
    for chave, valor in linha.items():
        if all(p in chave for p in pedacos):
            return valor
    return ""


def cnpj_do_ticker(ticker: str, hoje: dt.date) -> tuple[str, str] | None:
    """CNPJ e nome da empresa pelo código de negociação (FCA da CVM, valores mobiliários)."""
    for ano in (hoje.year, hoje.year - 1):
        try:
            linhas = _csv_do_zip(f"{CVM}/FCA/DADOS/fca_cia_aberta_{ano}.zip", "valor_mobiliario")
        except Exception as e:  # noqa: BLE001 - arquivo do ano pode não existir ainda
            log.info("  cadastro FCA %s indisponível (%s)", ano, e.__class__.__name__)
            continue
        for linha in linhas:
            if _campo(linha, "codigo", "negociacao").upper() == ticker:
                return _campo(linha, "cnpj"), _campo(linha, "nome") or _campo(linha, "denom")
    return None


PALAVRAS_PROJECAO = re.compile(r"proje|guidance|estimativ|perspectiv", re.I)
PALAVRAS_RESULTADO = re.compile(r"resultado|desempenho|release", re.I)


def documentos_cvm(cnpj: str, hoje: dt.date) -> list[dict]:
    """Documentos IPE da empresa que podem trazer guidance, do mais novo para o mais antigo."""
    docs = []
    for ano in (hoje.year, hoje.year - 1):
        try:
            linhas = _csv_do_zip(f"{CVM}/IPE/DADOS/ipe_cia_aberta_{ano}.zip", "ipe_cia_aberta")
        except Exception as e:  # noqa: BLE001
            log.info("  documentos IPE %s indisponíveis (%s)", ano, e.__class__.__name__)
            continue
        for l in linhas:
            if re.sub(r"\D", "", _campo(l, "cnpj")) != re.sub(r"\D", "", cnpj):
                continue
            assunto = " ".join([_campo(l, "categoria"), _campo(l, "tipo"), _campo(l, "especie"), _campo(l, "assunto")])
            if not (PALAVRAS_PROJECAO.search(assunto) or PALAVRAS_RESULTADO.search(assunto)):
                continue
            docs.append({"data": _campo(l, "data", "entrega") or _campo(l, "data", "referencia"),
                         "categoria": _campo(l, "categoria"), "assunto": _campo(l, "assunto"),
                         "tipo": " ".join([_campo(l, "tipo"), _campo(l, "especie")]).strip(),
                         "link": _campo(l, "link")})
    docs = [d for d in docs if d["link"].startswith("http")]
    return sorted(docs, key=lambda d: d["data"], reverse=True)


def _baixar_pdf(link: str) -> bytes:
    pdf = _get(link).content
    if not pdf.lstrip().startswith(b"%PDF"):
        # o RAD da CVM às vezes devolve uma página HTML com o arquivo dentro
        inicio = pdf.find(b"%PDF")
        b64 = re.search(rb"JVBERi0[A-Za-z0-9+/=\s]{100,}", pdf)
        if inicio >= 0:
            pdf = pdf[inicio:]
        elif b64:
            pdf = base64.b64decode(re.sub(rb"\s", b"", b64.group(0)))
        else:
            titulo = re.search(rb"<title>(.*?)</title>", pdf, re.I | re.S)
            raise ValueError(f"não é PDF ({(titulo.group(1).strip()[:80] if titulo else pdf[:60])!r})")
    return pdf


def _texto_pdf(pdf: bytes) -> str:
    """pypdf; se falhar ou vier vazio, pdfplumber; depois PyMuPDF (os que estiverem instalados)."""
    erros = []
    try:
        from pypdf import PdfReader
        t = "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(pdf)).pages)
        if t.strip():
            return t
        erros.append("pypdf: texto vazio")
    except Exception as e:  # noqa: BLE001
        erros.append(f"pypdf: {e.__class__.__name__}")
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(pdf)) as doc:
            t = "\n".join((p.extract_text() or "") for p in doc.pages)
        if t.strip():
            return t
        erros.append("pdfplumber: texto vazio")
    except Exception as e:  # noqa: BLE001
        erros.append(f"pdfplumber: {e.__class__.__name__}")
    try:
        import fitz
        with fitz.open(stream=pdf, filetype="pdf") as doc:
            t = "\n".join(p.get_text() for p in doc)
        if t.strip():
            return t
        erros.append("PyMuPDF: texto vazio")
    except Exception as e:  # noqa: BLE001
        erros.append(f"PyMuPDF: {e.__class__.__name__}")
    raise ValueError("nenhum leitor de PDF conseguiu: " + "; ".join(erros))


def texto_do_pdf(link: str, tentativas: int = 3, espera: float = 4.0) -> tuple[bytes, str]:
    """Baixa e lê o PDF, com novas tentativas: o RAD da CVM às vezes devolve uma página no lugar do arquivo."""
    import time

    ultimo = None
    for n in range(tentativas):
        try:
            pdf = _baixar_pdf(link)
            return pdf, _texto_pdf(pdf)
        except Exception as e:  # noqa: BLE001
            ultimo = e
            if n < tentativas - 1:
                time.sleep(espera * (n + 1))
    raise ultimo


def acoes_yahoo(ticker: str) -> float | None:
    import yfinance as yf

    try:
        info = yf.Ticker(f"{ticker}.SA").info or {}
        return float(info.get("sharesOutstanding") or info.get("impliedSharesOutstanding") or 0) or None
    except Exception:  # noqa: BLE001
        return None


# ------------------------------------------------------------ plano e aplicação
def _data_br(data: str) -> str:
    try:
        return dt.date.fromisoformat(data[:10]).strftime("%d/%m/%Y")
    except ValueError:
        return data


def _data(texto: str | None) -> dt.date | None:
    """'2026-11-11', '2026-11-11 10:00' ou '11/11/2026' -> date."""
    texto = (texto or "").strip()
    for formato, tam in (("%Y-%m-%d", 10), ("%d/%m/%Y", 10)):
        try:
            return dt.datetime.strptime(texto[:tam], formato).date()
        except ValueError:
            continue
    return None


def _lpa(o: dict) -> float | None:
    try:
        if "lpa_min" in o:
            return (float(o["lpa_min"]) + float(o["lpa_max"])) / 2
        return (float(o["lucro_min"]) + float(o["lucro_max"])) / 2 / float(o["acoes"])
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None


# ------------------------------------------------------------ AUTOMÁTICO COM PROTEÇÃO: as 4 travas
HOSTS_OFICIAIS = ("cvm.gov.br", "sec.gov")
RE_FAIXA_USD = re.compile(r"\$?\s?(\d{1,3}\.\d{2})\s*(?:to|and|through|-|–|—|\|)\s*\$?\s?(\d{1,3}\.\d{2})", re.I)


def mercado_yahoo(ticker: str) -> dict | None:
    """Cotação e P/L de 12 meses do Yahoo (B3 com .SA). None se o Yahoo não responder."""
    import yfinance as yf

    simbolo = f"{ticker}.SA" if re.fullmatch(r"(?=.*[A-Z])[A-Z0-9]{4}\d{1,2}", ticker) else ticker
    try:
        info = yf.Ticker(simbolo).info or {}
    except Exception:  # noqa: BLE001
        return None
    preco = info.get("currentPrice") or info.get("regularMarketPrice")
    if not preco:
        return None
    return {"preco": float(preco), "pl": float(info["trailingPE"]) if info.get("trailingPE") else None}


def ocorrencias_da_faixa(texto: str, novo: dict) -> int:
    """Quantas vezes a faixa escolhida aparece no documento (ex.: no texto e na tabela)."""
    if "lpa_min" in novo:
        alvo = (round(float(novo["lpa_min"]), 2), round(float(novo["lpa_max"]), 2))
        return sum((round(float(m.group(1)), 2), round(float(m.group(2)), 2)) == alvo for m in RE_FAIXA_USD.finditer(texto))
    t = normalizar(texto)
    alvo = (float(novo["lucro_min"]), float(novo["lucro_max"]))
    n = 0
    for m in RE_FAIXA.finditer(t):
        if t[m.end(): m.end() + 2].lstrip().startswith("%"):
            continue                                   # "9% a 11%" é outra coisa
        a, b = numero_br(m.group(1)), numero_br(m.group(3))
        if any(abs(a * mult - alvo[0]) < 1 and abs(b * mult - alvo[1]) < 1 for mult in (1e9, 1e6, 1e3, 1)):
            n += 1
    return n


def _variacao(novo: dict, ref: dict) -> float | None:
    """Variação do guidance novo contra o do app (pelo lucro médio quando os dois são em lucro, senão pelo LPA)."""
    try:
        if "lucro_min" in novo and "lucro_min" in ref:
            a = (float(novo["lucro_min"]) + float(novo["lucro_max"])) / 2
            b = (float(ref["lucro_min"]) + float(ref["lucro_max"])) / 2
        else:
            a, b = _lpa(novo), _lpa(ref)
        return round(a / b - 1, 6) if a and b else None
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None


def avaliar_travas(ticker: str, novo: dict, referencia: dict | None, texto: str, hoje: dt.date,
                   duvidas: list[str], buscar_mercado=mercado_yahoo) -> dict:
    """As 4 travas do AUTOMÁTICO COM PROTEÇÃO. Publica sozinho só se as 4 passarem e não houver dúvida."""
    from urllib.parse import urlparse

    travas = []
    host = (urlparse(novo.get("url") or "").hostname or "").lower()
    oficial = any(host == h or host.endswith("." + h) for h in HOSTS_OFICIAIS)
    travas.append({"nome": "Fonte oficial", "ok": oficial,
                   "detalhe": f"comunicado da empresa em {host}" if oficial else f"documento fora da CVM/SEC ({host or 'sem link'})"})

    n = ocorrencias_da_faixa(texto, novo)
    travas.append({"nome": "Número em 2 lugares", "ok": n >= 2,
                   "detalhe": f"a faixa aparece {n} vez(es) no documento" + ("" if n >= 2 else "; precisa de 2 (texto + tabela)")})

    var = _variacao(novo, referencia) if referencia else None
    if var is None:
        travas.append({"nome": "Variação até 20%", "ok": False,
                       "detalhe": "sem guidance anterior no app para comparar" if not referencia else "não deu para comparar com o anterior"})
    else:
        travas.append({"nome": "Variação até 20%", "ok": abs(var) <= LIMITE_AUTO,
                       "detalhe": f"{var:+.1%} contra o guidance anterior ({referencia.get('data') or 'sem data'})"})

    lpa = _lpa(novo)
    mercado = None
    try:
        mercado = buscar_mercado(ticker)
    except Exception:  # noqa: BLE001
        mercado = None
    if not lpa or not mercado:
        travas.append({"nome": "P/L plausível", "ok": False, "detalhe": "sem cotação ou LPA para calcular o P/L"})
    else:
        pl = mercado["preco"] / lpa
        ref_pl = mercado.get("pl")
        if not ref_pl and referencia and _lpa(referencia):
            ref_pl = mercado["preco"] / _lpa(referencia)
        if pl <= 0 or pl > PL_MAXIMO:
            ok, det = False, f"P/L {pl:.1f} fora de 0 a {PL_MAXIMO}"
        elif not ref_pl or ref_pl <= 0:
            ok, det = False, f"P/L {pl:.1f}, mas sem P/L de referência no Yahoo para comparar"
        else:
            ok = ref_pl / PL_FATOR <= pl <= ref_pl * PL_FATOR
            det = f"P/L {pl:.1f} (cotação {mercado['preco']:.2f} ÷ LPA {lpa:.2f}) contra {ref_pl:.1f} de 12 meses"
            if not ok:
                det += f": fora de 1/{PL_FATOR} a {PL_FATOR}x"
        travas.append({"nome": "P/L plausível", "ok": ok, "detalhe": det})

    publica = all(t["ok"] for t in travas) and not duvidas
    falhas = [f"{t['nome']}: {t['detalhe']}" for t in travas if not t["ok"]] + [f"Dúvida: {d}" for d in duvidas]
    return {"publica": publica, "travas": travas, "duvidas": list(duvidas),
            "motivo": "passou nas 4 travas" if publica else "TRAVADO - " + "; ".join(falhas)}


def _decidir(item: dict, ticker: str, novo: dict, referencia: dict | None, texto: str, hoje: dt.date,
             data_doc: dt.date | None, duvidas: list[str], buscar_mercado, extras=()) -> dict:
    idade = (hoje - data_doc).days if data_doc else None
    if idade is None or idade > IDADE_MAXIMA_DIAS:
        duvidas = duvidas + [f"documento de {novo['data']}, com mais de {IDADE_MAXIMA_DIAS} dias: "
                             "pode existir guidance mais novo que o robô não leu"]
    av = avaliar_travas(ticker, novo, referencia, texto, hoje, duvidas, buscar_mercado)
    item.update(acao="commit" if av["publica"] else "pr", novo=novo, travas=av["travas"], duvidas=av["duvidas"],
                motivo="; ".join([av["motivo"], *[e for e in extras if e]]))
    return item


def planejar_ticker(ticker: str, hoje: dt.date, anterior: dict | None, vistos: set[str], *,
                    buscar_cnpj=cnpj_do_ticker, buscar_docs=documentos_cvm, ler_pdf=texto_do_pdf,
                    buscar_acoes=acoes_yahoo, ler_com_claude=extrair_com_claude,
                    buscar_mercado=mercado_yahoo, referencia: dict | None = None) -> dict:
    """Decide o que fazer com um ticker. Não grava nada.

    referencia: guidance que está no app (o automático salvo ou o cadastro manual), base da trava de 20%."""
    referencia = referencia or anterior
    item = {"ticker": ticker, "acao": "nada", "motivo": "", "novo": None, "anterior": anterior}
    if not re.fullmatch(r"(?=.*[A-Z])[A-Z0-9]{4}\d{1,2}", ticker):
        return planejar_ticker_eua(ticker, hoje, anterior, vistos=vistos, buscar_mercado=buscar_mercado,
                                   referencia=referencia)
    empresa = buscar_cnpj(ticker, hoje)
    if not empresa:
        item.update(acao="erro", motivo="CNPJ não encontrado no cadastro da CVM")
        return item
    cnpj, nome = empresa
    ano = hoje.year
    tentou_claude = False
    for doc in buscar_docs(cnpj, hoje)[:MAX_DOCUMENTOS]:
        if anterior and anterior.get("documento") == doc["link"]:
            item["motivo"] = "guidance já atualizado com o documento mais recente"
            return item
        data_doc, data_ant = _data(doc["data"]), _data((anterior or {}).get("data"))
        if data_doc and data_ant and data_doc < data_ant:
            # documentos vêm do mais novo para o mais antigo: daqui para trás, tudo é anterior
            # ao guidance que já está no app (ex.: a faixa de maio depois da revisão de novembro)
            item["motivo"] = f"documento de {_data_br(doc['data'])} é mais antigo que o guidance atual ({anterior['data']}): descartado"
            return item
        try:
            pdf, texto = ler_pdf(doc["link"])
        except Exception as e:  # noqa: BLE001
            log.info("  não abriu documento de %s (%s: %s)", _data_br(doc["data"]), e.__class__.__name__, e)
            continue
        assunto = f"{doc.get('categoria', '')} {doc.get('tipo', '')} {doc.get('assunto', '')}"
        ex = extrair_por_padroes(texto, ano, titulo=assunto)
        if ex is None:
            # 2ª camada: o regex não achou faixa num documento de projeção -> API do Claude (uma vez por documento)
            if not tentou_claude and PALAVRAS_PROJECAO.search(assunto) and doc["link"] not in vistos:
                tentou_claude = True
                vistos.add(doc["link"])
                ex = ler_com_claude(pdf, texto, ano, ())
            if ex is None:
                continue                               # documento sem faixa de lucro: tenta o anterior
        # este é o documento mais novo com faixa de lucro: nunca volta para um mais antigo
        if ex.confianca != "alta" and ex.metodo != "API do Claude":
            if doc["link"] in vistos:
                item["motivo"] = "documento já tentado sem confiança; aguardando documento novo"
                return item
            vistos.add(doc["link"])
            ex = ler_com_claude(pdf, texto, ano, ex.faixas) or ex
            if ex.metodo != "API do Claude":
                item.update(acao="erro", motivo="faixa de lucro encontrada sem confiança: " + "; ".join(ex.motivos))
                return item
        acoes = buscar_acoes(ticker)
        if not acoes:
            item.update(acao="erro", motivo="número de ações indisponível no Yahoo Finance")
            return item
        novo = {"lucro_min": ex.lucro_min, "lucro_max": ex.lucro_max, "acoes": acoes, "payout": ex.payout,
                "fonte": f"{nome}, {doc['categoria'] or 'documento'} de {_data_br(doc['data'])} (CVM)",
                "data": _data_br(doc["data"]), "url": doc["link"], "documento": doc["link"],
                "ano": ex.ano, "metodo": ex.metodo, "trecho": ex.trecho[:400], "acoes_fonte": "Yahoo Finance"}
        if ex.historico:
            novo["historico"] = ex.historico
        if anterior and all(anterior.get(k) == novo[k] for k in ("lucro_min", "lucro_max", "payout", "ano")):
            item["motivo"] = "mesma faixa do guidance atual"
            return item
        duvidas = [] if ex.ano == ano else [f"projeção para {ex.ano}, não para {ano}"]
        return _decidir(item, ticker, novo, referencia, texto, hoje, data_doc, duvidas, buscar_mercado,
                        extras=[ex.metodo if ex.metodo == "API do Claude" else ""])
    item["motivo"] = "sem guidance (regex e API do Claude não acharam nos documentos recentes); mantido o anterior"
    return item


# ------------------------------------------------------------ EUA: SEC EDGAR (8-K / 6-K + press release)
SEC_ARQUIVOS = "https://www.sec.gov"
SEC_DADOS = "https://data.sec.gov"
FORMS_SEC = ("8-K", "6-K")


def cabecalho_sec() -> dict | None:
    """User-Agent exigido pela SEC, com o e-mail do Secret SEC_CONTACT_EMAIL. None se não houver."""
    email = (os.environ.get("SEC_CONTACT_EMAIL") or "").strip()
    if not email or "@" not in email:
        return None
    return {"User-Agent": f"fintai/1.0 (contato: {email})", "Accept-Encoding": "gzip, deflate"}


def _get_sec(url: str, cab: dict):
    import requests

    r = requests.get(url, headers=cab, timeout=60)
    r.raise_for_status()
    return r


def tickers_sec(cab: dict) -> dict:
    """Lista oficial da SEC (ticker -> cik/title), um único arquivo (~10 mil empresas, poucos MB).
    É a mesma lista para qualquer ticker: quem chama isto repetidas vezes seguidas (ex. o app, a
    cada ticker dos EUA digitado) deve cachear o resultado e passar em `mapa`, em vez de baixar o
    arquivo inteiro de novo a cada ticker."""
    return _get_sec(f"{SEC_ARQUIVOS}/files/company_tickers.json", cab).json()


def cik_do_ticker(ticker: str, cab: dict, mapa: dict | None = None) -> tuple[str, str] | None:
    """CIK (10 dígitos) e nome da empresa pelo ticker (lista oficial da SEC). `mapa` opcional: o
    resultado já buscado de `tickers_sec`, para não baixar a lista de novo."""
    dados = mapa if mapa is not None else tickers_sec(cab)
    for linha in dados.values():
        if str(linha.get("ticker", "")).upper() == ticker.upper():
            return f"{int(linha['cik_str']):010d}", str(linha.get("title", ticker))
    return None


def documentos_sec(cik: str, cab: dict) -> list[dict]:
    """8-K/6-K mais recentes com o anexo de comunicado (Exhibit 99.x), do mais novo para o mais antigo."""
    sub = _get_sec(f"{SEC_DADOS}/submissions/CIK{cik}.json", cab).json()
    rec = sub.get("filings", {}).get("recent", {})
    docs = []
    for form, data, acc, itens in zip(rec.get("form", []), rec.get("filingDate", []),
                                      rec.get("accessionNumber", []), rec.get("items", [""] * len(rec.get("form", [])))):
        if form not in FORMS_SEC:
            continue
        # 8-K: só resultados (2.02) ou comunicados (7.01/8.01); 6-K não tem itens
        if form == "8-K" and itens and not any(x in itens for x in ("2.02", "7.01", "8.01")):
            continue
        docs.append({"form": form, "data": data, "acc": acc, "cik": cik})
        if len(docs) >= MAX_DOCUMENTOS:
            break
    return docs


def _exhibit_99_pela_pagina_indice(pasta: str, acc: str, cab: dict, form: str = "") -> str | None:
    """Nome do arquivo marcado como Exhibit 99.x na página de índice da SEC (coluna "Type"), não só
    pelo nome do arquivo: várias empresas (ex. NVIDIA: "q3fy27pr.htm") nomeiam o press release de um
    jeito que não bate com o padrão "ex99", e aí a leitura por nome falha silenciosamente.

    Emissores estrangeiros em 6-K (ex. Novo Nordisk/NVO) às vezes não têm Exhibit 99 nenhum: o
    comunicado vem direto no corpo do próprio formulário. Nesse caso (só pra 6-K - o 8-K sempre tem
    um exhibit separado, então não vale o mesmo risco lá) aceita o documento do tipo "6-K" como
    alternativa, se não achar nenhum Exhibit 99."""
    html = _get_sec(f"{pasta}/{acc}-index.htm", cab).text
    candidatos, alternativa_6k = [], None
    for m in re.finditer(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I):
        celulas = re.findall(r"<td[^>]*>(.*?)</td>", m.group(1), re.S | re.I)
        if len(celulas) < 4:
            continue
        tipo = re.sub(r"<[^>]+>", "", celulas[3]).strip().upper()
        link = re.search(r'href="([^"]+)"', celulas[2])
        if not link:
            continue
        if re.match(r"EX-?99", tipo, re.I):
            candidatos.append((tipo, link.group(1).rsplit("/", 1)[-1]))
        elif form == "6-K" and tipo == "6-K" and alternativa_6k is None:
            alternativa_6k = link.group(1).rsplit("/", 1)[-1]
    if candidatos:
        return next((n for t, n in candidatos if t in ("EX-99.1", "EX-99")), candidatos[0][1])
    return alternativa_6k


def anexo_sec(doc: dict, cab: dict) -> tuple[str, str] | None:
    """Link e texto do Exhibit 99.1 (press release) de um 8-K/6-K - ou do próprio corpo do 6-K,
    quando o emissor estrangeiro não usa um exhibit separado (ver _exhibit_99_pela_pagina_indice)."""
    pasta = f"{SEC_ARQUIVOS}/Archives/edgar/data/{int(doc['cik'])}/{doc['acc'].replace('-', '')}"
    try:
        alvo = _exhibit_99_pela_pagina_indice(pasta, doc["acc"], cab, doc.get("form", ""))
    except Exception as e:  # noqa: BLE001
        log.info("  não consegui ler a página de índice (%s): tento pelo nome do arquivo", e.__class__.__name__)
        alvo = None
    if not alvo:
        itens = _get_sec(f"{pasta}/index.json", cab).json().get("directory", {}).get("item", [])
        nomes = [i["name"] for i in itens if i.get("name", "").lower().endswith((".htm", ".html", ".txt"))]
        alvo = next((n for n in nomes if re.search(r"ex[-_]?99[-_.]?0?1|ex991|exhibit991|dex991", n, re.I)), None) \
            or next((n for n in nomes if re.search(r"ex[-_]?99|exhibit99", n, re.I)), None)
    if not alvo:
        return None
    html = _get_sec(f"{pasta}/{alvo}", cab).text
    return f"{pasta}/{alvo}", texto_de_html(html)


def texto_de_html(html: str) -> str:
    import html as h

    t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", h.unescape(t)).strip()


# "adjusted EPS of approximately $5.50 to $5.80", "non-GAAP diluted EPS ... $5.42 to $5.48",
# "adjusted EPS of between $6.15 and $6.35"
RE_EPS_FAIXA = re.compile(
    r"((?:adjusted|non-gaap)[^.$]{0,60}?\b(?:eps|earnings per (?:diluted )?share)\b[^.$]{0,80}?)"
    r"\$\s?(\d{1,3}\.\d{2})\s*(?:to|and|-|–)\s*\$\s?(\d{1,3}\.\d{2})", re.I)
RE_ANO_EUA = re.compile(r"\b(fiscal(?:\s+year)?\s+|fy\s?|full[- ]year\s+|year\s+)?(20\d{2})\b", re.I)
RE_DIV_TRI = re.compile(r"quarterly (?:cash )?dividend[^.$]{0,120}?\$\s?(\d{1,2}\.\d{2,4})\s*per (?:common )?share", re.I)
RE_CONTEXTO_GUIDANCE = re.compile(r"guidance|outlook|expects?|forecast|range", re.I)
# faixa nova x faixa antiga quando o comunicado traz as duas (ex.: ADM 03/11/2026)
RE_FAIXA_NOVA = re.compile(r"\bupdated\b|\brevised\b|\bnow (?:expects?|anticipates?|sees|projects?)\b|"
                           r"outlook (?:is )?updated|\braising\b|\braised\b|\blowering\b|\blowered\b", re.I)
RE_FAIXA_ANTIGA = re.compile(r"\bpreviously\b|\bprevious\b|\bprior (?:outlook|guidance|range|expectation)s?\b|"
                             r"\bprior\b|\bearlier\b", re.I)


def _contexto_da_faixa(texto: str, inicio: int) -> str:
    """Trecho da mesma frase antes da faixa (até 160 caracteres), para ver se ela é a nova ou a antiga."""
    antes = texto[max(0, inicio - 160): inicio]
    # corta no fim da frase anterior (". " seguido de maiúscula), em "; " ou na abertura de parêntese
    cortes = [m.end() for m in re.finditer(r"\.\s+(?=[A-Z])|;\s|\(", antes)]
    return antes[cortes[-1]:] if cortes else antes


def extrair_eps_eua(texto: str, ano_minimo: int) -> dict | None:
    """Faixa de LPA projetado num comunicado dos EUA. None se não houver nenhuma faixa.

    Confiança alta: uma única faixa distinta, com palavra de projeção por perto e ano >= ano_minimo."""
    achados = []
    for m in RE_EPS_FAIXA.finditer(texto):
        a, b = float(m.group(2)), float(m.group(3))
        if not 0 < a <= b < 1000:
            continue
        janela = texto[max(0, m.start() - 250): m.end() + 120]
        anos = [(bool(x.group(1)), int(x.group(2))) for x in RE_ANO_EUA.finditer(janela)]
        anos_ok = [(f, y) for f, y in anos if ano_minimo <= y <= ano_minimo + 2]
        fiscal, ano = max(anos_ok, key=lambda x: x[1]) if anos_ok else (False, None)
        frase = _contexto_da_faixa(texto, m.start()) + m.group(1)
        achados.append({"lpa_min": a, "lpa_max": b, "ano": ano, "fiscal": fiscal,
                        "contexto": bool(RE_CONTEXTO_GUIDANCE.search(janela)),
                        "nova": bool(RE_FAIXA_NOVA.search(frase)), "antiga": bool(RE_FAIXA_ANTIGA.search(frase)),
                        "trecho": texto[max(0, m.start() - 120): m.end() + 40].strip()})
    if not achados:
        return None
    distintos = {(x["lpa_min"], x["lpa_max"]) for x in achados if x["ano"]}
    melhor = next((x for x in achados if x["ano"] and x["contexto"]), achados[0])
    escolha = ""
    if len(distintos) > 1:
        # duas ou mais faixas: ignora as marcadas como antigas (previously, prior...) e, se ainda
        # sobrar mais de uma, fica com as marcadas como novas (updated, now expects, raising...)
        restantes = [x for x in achados if x["ano"] and not x["antiga"]]
        if len({(x["lpa_min"], x["lpa_max"]) for x in restantes}) > 1:
            restantes = [x for x in restantes if x["nova"]]
        faixas_restantes = {(x["lpa_min"], x["lpa_max"]) for x in restantes}
        if len(faixas_restantes) == 1:
            melhor = next(x for x in restantes)
            ignoradas = sorted(distintos - faixas_restantes)
            escolha = "faixa nova escolhida; ignorada(s): " + ", ".join(f"{a:.2f} a {b:.2f}" for a, b in ignoradas)
            distintos = faixas_restantes
    motivos = []
    if not melhor["ano"]:
        motivos.append(f"faixa de LPA sem ano {ano_minimo} ou seguinte por perto")
    if not melhor["contexto"]:
        motivos.append("faixa sem palavra de projeção (guidance/outlook/expects) por perto")
    if len(distintos) > 1:
        # tabela "anterior x atual" ou várias métricas: pode ser o guidance velho
        motivos.append(f"{len(distintos)} faixas de LPA diferentes no documento")
    div = {round(float(x), 4) for x in RE_DIV_TRI.findall(texto)}
    periodo = (f"FY{melhor['ano']}" if melhor["fiscal"] and "fiscal" in melhor["trecho"].lower() else str(melhor["ano"] or ""))
    return {**melhor, "periodo": periodo, "confianca": "baixa" if motivos else "alta", "motivos": motivos, "escolha": escolha,
            "dividendo": round(div.pop() * 4, 4) if len(div) == 1 else None, "faixas": sorted(distintos)}


# -------------------------------------------- outlook trimestral (EUA) - só informativo
RE_OUTLOOK_TRI = re.compile(
    r"(?:(?:guidance\s+for\s+the|(?:’s|'s)\s+outlook\s+for\s+the)\s+(first|second|third|fourth)\s+quarter"
    r"\s+of\s+(?:fiscal\s+)?(\d{4}))"
    r"|(?:for\s+the\s+fiscal\s+(first|second|third|fourth)\s+quarter\s+(\d{4}),?\s+we\s+expect)"
    r"|(?:for\s+the\s+(first|second|third|fourth)\s+quarter\s+of\s+(?:fiscal\s+)?(\d{4}),?\s+[A-Z][\w.&]*\s+expects)"
    # "ASML expects Q4 2026 total net sales..." (abreviado "QN AAAA", sem "quarter" por extenso - ex. ASML)
    r"|(?:[A-Z][\w.&]*\s+expects\s+Q([1-4])\s+(\d{4}))",
    re.I)
_ORDINAL_TRI = {"first": 1, "second": 2, "third": 3, "fourth": 4, "1": 1, "2": 2, "3": 3, "4": 4}
_NUM_TRI = r"\$?\s*([\d][\d,]*\.?\d*)"
_ESCALA_TRI = {"billion": 1e9, "million": 1e6}


def _faixa_tri(rotulo: str, texto: str, unidade: bool = False) -> tuple[float, float] | None:
    """Acha a faixa de 'rotulo' logo depois do rótulo, em qualquer um destes formatos:
    'X ± Y [bilhão/milhão]', 'X to Y [bilhão/milhão]', ou 'X, plus or minus Z%' (faixa por
    percentual do valor central). Devolve já convertido pela unidade (bilhão/milhão), se houver."""
    pad_unid = r"\s*(billion|million)?" if unidade else ""
    m = re.search(rf"{rotulo}\D{{0,25}}{_NUM_TRI}{pad_unid}\s*±\s*{_NUM_TRI}", texto, re.I)
    if m:
        unid = m.group(2) if unidade else None
        delta_i = 3 if unidade else 2
        meio, delta = float(m.group(1).replace(",", "")), float(m.group(delta_i).replace(",", ""))
        fator = _ESCALA_TRI.get(unid, 1)
        return (meio - delta) * fator, (meio + delta) * fator
    m = re.search(rf"{rotulo}\D{{0,25}}{_NUM_TRI}{pad_unid}\s*,?\s*plus or minus\s*([\d.]+)\s*%", texto, re.I)
    if m:
        unid = m.group(2) if unidade else None
        pct_i = 3 if unidade else 2
        meio, pct = float(m.group(1).replace(",", "")), float(m.group(pct_i)) / 100
        fator = _ESCALA_TRI.get(unid, 1)
        return meio * (1 - pct) * fator, meio * (1 + pct) * fator
    m = re.search(rf"{rotulo}\D{{0,25}}{_NUM_TRI}{pad_unid}\s*(?:to|-|–)\s*{_NUM_TRI}", texto, re.I)
    if m:
        unid = m.group(2) if unidade else None
        b_i = 3 if unidade else 2
        a, b = float(m.group(1).replace(",", "")), float(m.group(b_i).replace(",", ""))
        fator = _ESCALA_TRI.get(unid, 1)
        return min(a, b) * fator, max(a, b) * fator
    # "between X [bilhão] and Y [bilhão]" (ex.: ASML) - unidade pode repetir em cada lado
    m = re.search(rf"{rotulo}\D{{0,25}}between\s+{_NUM_TRI}{pad_unid}\s+and\s+{_NUM_TRI}{pad_unid}", texto, re.I)
    if m:
        unid = (m.group(2) or m.group(4)) if unidade else None
        b_i = 3 if unidade else 2
        a, b = float(m.group(1).replace(",", "")), float(m.group(b_i).replace(",", ""))
        fator = _ESCALA_TRI.get(unid, 1)
        return min(a, b) * fator, max(a, b) * fator
    return None


def _margem_tri(texto: str) -> float | None:
    """Margem bruta guiada: um valor único (ex. 'Approximately 86%') ou uma faixa ('between 71% and
    72%'); nesse caso devolve o ponto médio (o card mostra o trecho original para conferência)."""
    m = re.search(r"[Gg]ross margins?\D{0,45}between\s+([\d.]+)\s*%\s+and\s+([\d.]+)\s*%", texto, re.I)
    if m:
        return round((float(m.group(1)) + float(m.group(2))) / 2, 2)
    m = re.search(r"[Gg]ross margins?\D{0,45}([\d.]+)\s*%", texto, re.I)
    return float(m.group(1)) if m else None


def extrair_outlook_trimestral_eua(texto: str) -> dict | None:
    """Guidance TRIMESTRAL da própria empresa (receita, margem bruta, LPA do próximo trimestre),
    direto do texto do earnings release (8-K/6-K Exhibit 99.1 na SEC). Informativo: não participa
    do "Previsão atual"/P/L nem do selo GUIDANCE OFICIAL (aquele é guidance ANUAL, campo diferente -
    usar o LPA de 1 trimestre como se fosse do ano inteiro distorceria o P/L). Só pelos padrões de
    texto (sem API do Claude, sem as 4 travas): sem achar com segurança, devolve None e a tela
    simplesmente não mostra o card - nunca inventa um número. Nem toda empresa dá guidance de LPA
    (algumas só dão receita/margem): o que não for achado fica None, sem travar o resto.

    Devolve {"periodo", "receita_min", "receita_max" (em dólares, já convertido pela unidade),
    "margem_bruta" (%, opcional), "lpa_min", "lpa_max", "trecho"} ou None."""
    texto = normalizar(texto)
    m = RE_OUTLOOK_TRI.search(texto)
    if not m:
        return None
    ordinal, ano_txt = next((m.group(i), m.group(i + 1)) for i in (1, 3, 5, 7) if m.group(i))
    tri, ano = _ORDINAL_TRI[ordinal.lower()], int(ano_txt)
    janela = texto[m.end(): m.end() + 2000]   # a tabela/lista de outlook vem logo depois do título
    receita = _faixa_tri(r"(?:Revenue|[Tt]otal net sales|[Nn]et sales)", janela, unidade=True)
    lpa = _faixa_tri(r"Diluted(?:\s+non-GAAP)?\s+(?:net income per share|earnings per share)", janela)
    if not receita and not lpa:
        return None
    return {"periodo": f"{tri}T FY{ano}",
            "receita_min": receita[0] if receita else None, "receita_max": receita[1] if receita else None,
            "margem_bruta": _margem_tri(janela),
            "lpa_min": lpa[0] if lpa else None, "lpa_max": lpa[1] if lpa else None,
            "trecho": texto[m.start(): m.end() + 300].strip()[:400]}


def atualizar_outlook_trimestral_eua(tickers: list[str] | None = None, *, cabecalho=cabecalho_sec,
                                     buscar_cik=cik_do_ticker, buscar_docs=documentos_sec,
                                     ler_anexo=anexo_sec, max_docs: int = 3) -> dict[str, dict]:
    """Guidance TRIMESTRAL (receita, margem, LPA do próximo trimestre) de cada ticker dos EUA já
    cadastrado em guidance_tickers.json OU já travado em queue_nao_validado.json (sem guidance ANUAL
    confirmado) - só informativo (ver extrair_outlook_trimestral_eua: não participa do P/L nem do
    selo GUIDANCE OFICIAL). Inclui os travados de propósito: é exatamente o caso de empresas como a
    MU e a AMD, que não têm guidance anual mas dão guidance trimestral a cada earnings release -
    sem isso, o card trimestral delas nunca apareceria sozinho. Olha os `max_docs` earnings releases
    mais recentes de cada ticker até achar um com a tabela de outlook; sem achar em nenhum, mantém o
    que já estava gravado (uma tentativa sem sucesso nunca apaga um valor bom). Grava em
    utils/guidance_trimestral_eua.json e devolve a tabela completa (gravada ou não)."""
    if tickers is None:
        candidatos = set(_ler_json(ARQ_TICKERS, [])) | set(_ler_json(ARQ_NAO_VALIDADO, {}))
        tickers = [t.strip().upper() for t in candidatos
                   if not re.fullmatch(r"(?=.*[A-Z])[A-Z0-9]{4}\d{1,2}", t.strip().upper())]
    tab = _ler_json(ARQ_OUTLOOK_TRI, {})
    cab = cabecalho()
    if not cab:
        log.warning("outlook trimestral: sem SEC_CONTACT_EMAIL (Secret do GitHub): pulado")
        return tab
    mudou = False
    for t in tickers:
        try:
            empresa = buscar_cik(t, cab)
        except Exception as e:  # noqa: BLE001
            log.info("  outlook %s: não consegui achar o CIK (%s)", t, e.__class__.__name__)
            continue
        if not empresa:
            continue
        cik, nome = empresa
        achou = None
        try:
            docs = buscar_docs(cik, cab)[:max_docs]
        except Exception as e:  # noqa: BLE001
            log.info("  outlook %s: não consegui listar os documentos (%s)", t, e.__class__.__name__)
            continue
        for doc in docs:
            try:
                anexo = ler_anexo(doc, cab)
            except Exception as e:  # noqa: BLE001
                log.info("  outlook %s: não abriu %s de %s (%s)", t, doc["form"], _data_br(doc["data"]), e.__class__.__name__)
                continue
            if not anexo:
                continue
            link, texto = anexo
            dados = extrair_outlook_trimestral_eua(texto)
            if dados:
                achou = {**dados, "fonte": f"{nome}, Form {doc['form']} Exhibit 99.1 de {_data_br(doc['data'])} (SEC)",
                        "data": _data_br(doc["data"]), "url": link}
                break
        if achou and tab.get(t) != achou:
            tab[t] = achou
            mudou = True
            log.info("  outlook %s: %s", t, achou["periodo"])
        elif not achou:
            log.info("  outlook %s: sem tabela de outlook nos %d comunicados mais recentes (mantido o anterior)", t, max_docs)
    if mudou:
        ARQ_OUTLOOK_TRI.write_text(json.dumps(dict(sorted(tab.items())), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return tab


def planejar_ticker_eua(ticker: str, hoje: dt.date, anterior: dict | None, *,
                        cabecalho=cabecalho_sec, buscar_cik=cik_do_ticker, buscar_docs=documentos_sec,
                        ler_anexo=anexo_sec, ler_claude=extrair_eps_com_claude, vistos: set | None = None,
                        buscar_mercado=mercado_yahoo, referencia: dict | None = None) -> dict:
    """Mesmo critério do Brasil, com documentos da SEC. Não grava nada."""
    referencia = referencia or anterior
    item = {"ticker": ticker, "acao": "nada", "motivo": "", "novo": None, "anterior": anterior}
    cab = cabecalho()
    if not cab:
        item.update(acao="erro", motivo="sem SEC_CONTACT_EMAIL (Secret do GitHub): a SEC exige e-mail de contato")
        return item
    empresa = buscar_cik(ticker, cab)
    if not empresa:
        item.update(acao="erro", motivo="ticker não encontrado na lista da SEC")
        return item
    cik, nome = empresa
    vistos = set() if vistos is None else vistos
    primeiro = None                                   # comunicado mais novo, para a 2ª camada (API do Claude)
    for doc in buscar_docs(cik, cab):
        data_doc, data_ant = _data(doc["data"]), _data((anterior or {}).get("data"))
        if data_doc and data_ant and data_doc < data_ant:
            item["motivo"] = f"documento de {_data_br(doc['data'])} é mais antigo que o guidance atual ({anterior['data']}): descartado"
            return item
        try:
            anexo = ler_anexo(doc, cab)
        except Exception as e:  # noqa: BLE001
            log.info("  não abriu %s de %s (%s)", doc["form"], _data_br(doc["data"]), e.__class__.__name__)
            continue
        if not anexo:
            continue
        link, texto = anexo
        if anterior and anterior.get("documento") == link:
            item["motivo"] = "guidance já atualizado com o documento mais recente"
            return item
        primeiro = primeiro or (doc, link, texto)
        ex = extrair_eps_eua(texto, hoje.year)
        if ex is None:
            continue                                   # comunicado sem faixa de LPA: tenta o anterior
        if ex["confianca"] != "alta":
            # 2ª camada: regex achou faixa sem confiança -> API do Claude neste comunicado (uma vez por documento)
            lido = None
            if link not in vistos:
                vistos.add(link)
                lido = ler_claude(texto, hoje.year)
            if not lido:
                item.update(acao="erro", motivo="faixa de LPA encontrada sem confiança: " + "; ".join(ex["motivos"])
                            + "; API do Claude não confirmou")
                return item
            ex = {**ex, **lido, "periodo": ex.get("periodo") or str(lido["ano"]), "confianca": "baixa",
                  "dividendo": None, "metodo": "API do Claude"}
        novo = {"lpa_min": ex["lpa_min"], "lpa_max": ex["lpa_max"], "periodo": ex["periodo"],
                "lucro_tipo": "LPA ajustado", "fonte": f"{nome}, Form {doc['form']} Exhibit 99.1 de {_data_br(doc['data'])} (SEC)",
                "data": _data_br(doc["data"]), "url": link, "documento": link, "ano": ex["ano"],
                "metodo": ex.get("metodo", "padrões de texto (SEC)"), "trecho": ex["trecho"][:400]}
        if ex.get("historico"):
            novo["historico"] = ex["historico"]
        if ex["dividendo"]:
            novo["dividendo"] = ex["dividendo"]
        if anterior and all(anterior.get(k) == novo.get(k) for k in ("lpa_min", "lpa_max", "dividendo", "ano")):
            item["motivo"] = "mesma faixa do guidance atual"
            return item
        if ex.get("escolha"):
            novo["escolha"] = ex["escolha"]
        duvidas = [] if ex.get("ano") and int(ex["ano"]) >= hoje.year else [f"projeção para {ex.get('ano')}, não para {hoje.year} ou depois"]
        return _decidir(item, ticker, novo, referencia, texto, hoje, data_doc, duvidas, buscar_mercado,
                        extras=["API do Claude" if novo["metodo"] == "API do Claude" else "", ex.get("escolha")])
    # 2ª camada: regex não achou faixa em nenhum comunicado -> API do Claude no mais novo (uma vez por documento)
    if primeiro and primeiro[1] not in vistos:
        doc, link, texto = primeiro
        vistos.add(link)
        lido = ler_claude(texto, hoje.year)
        if lido:
            novo = {"lpa_min": lido["lpa_min"], "lpa_max": lido["lpa_max"], "periodo": str(lido["ano"]),
                    "lucro_tipo": "LPA ajustado", "fonte": f"{nome}, Form {doc['form']} Exhibit 99.1 de {_data_br(doc['data'])} (SEC)",
                    "data": _data_br(doc["data"]), "url": link, "documento": link, "ano": lido["ano"],
                    "metodo": "API do Claude", "trecho": lido["trecho"]}
            if lido.get("historico"):
                novo["historico"] = lido["historico"]
            duvidas = [] if lido.get("ano") and int(lido["ano"]) >= hoje.year else [f"projeção para {lido.get('ano')}"]
            return _decidir(item, ticker, novo, referencia, texto, hoje, _data(doc["data"]), duvidas, buscar_mercado,
                            extras=[f"API do Claude, página {lido.get('pagina')}"])
    item["motivo"] = "sem guidance (regex e API do Claude não acharam nos comunicados recentes); mantido o anterior"
    return item


# ------------------------------------------------------------ contábil 12 meses pela SEC (EPS diluído GAAP)
ARQ_CONTABIL = RAIZ / "utils" / "contabil_sec.json"
CONTABIL_IDADE_MAX = 200    # último trimestre com mais de 200 dias: a SEC está atrasada/incompleta


def lpa_anual_sec(fatos: dict) -> list[dict]:
    """LPA diluído (GAAP) de cada ano fiscal fechado, direto do 10-K na SEC — não passa pelo
    income_stmt do Yahoo (que costuma trazer só ~4 anos). A SEC é a fonte primária. Só ano fiscal
    completo (350-380 dias) de 10-K ou 10-K/A; reapresentação (10-K/A) mais recente ganha do 10-K
    original do mesmo ano.

    Devolve [{"ano", "lpa", "fim" (DD/MM/AAAA), "form"}, ...], do mais antigo para o mais novo —
    sem limite de anos (a SEC costuma ter mais histórico que os ~4 anos do Yahoo gratuito)."""
    eps = (((fatos.get("facts") or {}).get("us-gaap") or {}).get("EarningsPerShareDiluted") or {}).get("units", {}).get("USD/shares", [])
    anuais: dict[dt.date, dict] = {}
    for e in eps:
        if e.get("form") not in ("10-K", "10-K/A") or "start" not in e or "end" not in e:
            continue
        ini, fim = _data(e["start"]), _data(e["end"])
        if not ini or not fim or not 350 <= (fim - ini).days <= 380:
            continue
        if fim not in anuais or e.get("filed", "") > anuais[fim].get("filed", ""):
            anuais[fim] = e
    return [{"ano": fim.year, "lpa": round(float(anuais[fim]["val"]), 4), "fim": f"{fim:%d/%m/%Y}",
            "form": anuais[fim].get("form", "")} for fim in sorted(anuais)]


def lpa_ttm_sec(fatos: dict, hoje: dt.date) -> dict:
    """LPA diluído (GAAP) dos últimos 12 meses = soma dos últimos 4 trimestres dos 10-Q/10-K.

    Trimestres de 3 meses vêm direto dos 10-Q; o 4º trimestre fiscal = ano (10-K) - 9 meses acumulados (10-Q).
    Devolve {"status": "ok", "lpa_12m", "trimestres", ...} ou {"status": "incompleto", "motivo"}."""
    eps = (((fatos.get("facts") or {}).get("us-gaap") or {}).get("EarningsPerShareDiluted") or {}).get("units", {}).get("USD/shares", [])
    if not eps:
        return {"status": "incompleto", "motivo": "SEC sem EarningsPerShareDiluted"}
    por_periodo = {}
    for e in eps:
        if e.get("form") not in ("10-Q", "10-K", "10-Q/A", "10-K/A") or "start" not in e or "end" not in e:
            continue
        ini, fim = _data(e["start"]), _data(e["end"])
        if not ini or not fim:
            continue
        chave = (ini, fim)
        # a versão mais recente do mesmo período ganha (reapresentações)
        if chave not in por_periodo or e.get("filed", "") > por_periodo[chave].get("filed", ""):
            por_periodo[chave] = e
    tri, longos = {}, []
    for (ini, fim), e in por_periodo.items():
        dias = (fim - ini).days
        if 80 <= dias <= 100:
            tri[fim] = (float(e["val"]), e.get("filed", ""), e.get("form", ""))
        elif 255 <= dias <= 285 or 350 <= dias <= 380:
            longos.append((ini, fim, dias, float(e["val"]), e.get("filed", ""), e.get("form", "")))
    # 4º trimestre: ano fiscal menos os 9 meses do mesmo ano fiscal
    for ini, fim, dias, val, filed, form in longos:
        if dias < 350 or fim in tri:
            continue
        nove = next((l for l in longos if l[0] == ini and 255 <= l[2] <= 285), None)
        if nove:
            tri[fim] = (val - nove[3], filed, form)
    fins = sorted(tri)
    if len(fins) < 4:
        return {"status": "incompleto", "motivo": f"só {len(fins)} trimestre(s) na SEC"}
    ultimos = fins[-4:]
    if any(not 80 <= (b - a).days <= 100 for a, b in zip(ultimos, ultimos[1:])):
        return {"status": "incompleto", "motivo": "trimestres da SEC não são consecutivos"}
    if (hoje - ultimos[-1]).days > CONTABIL_IDADE_MAX:
        return {"status": "incompleto", "motivo": f"último trimestre na SEC termina em {ultimos[-1]:%d/%m/%Y}"}
    return {"status": "ok", "lpa_12m": round(sum(tri[f][0] for f in ultimos), 4),
            "trimestres": [{"fim": f"{f:%d/%m/%Y}", "lpa": round(tri[f][0], 4), "form": tri[f][2]} for f in ultimos],
            "fonte": "SEC 10-Q/10-K, lucro por ação diluído (GAAP)",
            "data": _data_br(max(tri[f][1] for f in ultimos)), "atualizado": f"{hoje:%d/%m/%Y}"}


# LPA ajustado do trimestre no press release (8-K Exhibit 99.1): "Third quarter adjusted EPS of $1.77"
RE_EPS_AJUSTADO_TRI = re.compile(
    r"adjusted\s+(?:net\s+)?(?:diluted\s+)?(?:earnings\s+per\s+(?:diluted\s+)?share|eps)\b[^$.]{0,60}?\$\s?(-?\d{1,3}\.\d{2})", re.I)
RE_NAO_TRIMESTRE = re.compile(r"full[- ]year|year[- ]to[- ]date|\bytd\b|nine months|six months|annual|outlook|guidance|"
                              r"expects?|forecast|\b20\d{2}\s+adjusted", re.I)


def extrair_eps_ajustado_trimestre(texto: str) -> float | None:
    """Primeiro LPA ajustado do comunicado que é do trimestre (não do ano, do acumulado nem da projeção)."""
    for m in RE_EPS_AJUSTADO_TRI.finditer(texto):
        antes = texto[max(0, m.start() - 90): m.start()] + m.group(0)
        if RE_NAO_TRIMESTRE.search(antes):
            continue
        return float(m.group(1))
    return None


def contabil_ajustado(gaap: dict, ajustados: dict) -> dict:
    """Soma dos 4 últimos trimestres de LPA AJUSTADO (8-K Exhibit 99.1).

    gaap: resultado de lpa_ttm_sec (dá os 4 trimestres e o GAAP de cada um).
    ajustados: {"DD/MM/AAAA" (fim do trimestre): {"lpa", "fonte", "data", "url"}}.
    Trimestre sem ajustado usa o GAAP daquele trimestre e conta em "trimestres_gaap"."""
    if gaap.get("status") != "ok":
        return gaap
    tri, n_gaap = [], 0
    for t in gaap["trimestres"]:
        a = ajustados.get(t["fim"])
        if a and a.get("lpa") is not None:
            tri.append({"fim": t["fim"], "lpa": round(float(a["lpa"]), 4), "tipo": "ajustado",
                        "fonte": a.get("fonte", "SEC 8-K Exhibit 99.1"), "data": a.get("data", ""), "url": a.get("url", "")})
        else:
            n_gaap += 1
            tri.append({"fim": t["fim"], "lpa": t["lpa"], "tipo": "GAAP", "fonte": f"SEC {t.get('form') or '10-Q/10-K'} (GAAP)",
                        "data": gaap.get("data", ""), "url": ""})
    fonte = "SEC 8-K Exhibit 99.1, LPA Ajustado"
    if n_gaap:
        fonte += f" ({n_gaap} trimestre{'s' if n_gaap > 1 else ''} GAAP por falta de Ajustado)"
    return {"status": "ok", "base": "ajustado" if n_gaap < 4 else "GAAP", "lpa_12m": round(sum(t["lpa"] for t in tri), 4),
            "trimestres": tri, "trimestres_gaap": n_gaap, "fonte": fonte if n_gaap < 4 else "SEC 10-Q/10-K, lucro por ação diluído (GAAP)",
            "data": max((t["data"] for t in tri if t["data"]), default=gaap.get("data", "")), "atualizado": gaap.get("atualizado", "")}


def ajustados_sec(cik: str, cab: dict, fins: list[str], *, buscar_docs=None, ler=None) -> dict:
    """Para cada fim de trimestre, o 8-K de resultado (2.02) dos 100 dias seguintes e o LPA ajustado do release."""
    buscar_docs = buscar_docs or documentos_sec_periodo
    ler = ler or anexo_sec
    saida = {}
    for fim in fins:
        d = _data(fim)
        for doc in buscar_docs(cik, cab, d + dt.timedelta(days=1), d + dt.timedelta(days=100)):
            if doc["form"] not in ("8-K", "6-K"):
                continue
            try:
                lido = ler(doc, cab)
            except Exception:  # noqa: BLE001
                continue
            if not lido:
                continue
            v = extrair_eps_ajustado_trimestre(lido[1])
            if v is not None:
                saida[fim] = {"lpa": v, "fonte": f"SEC Form {doc['form']} Exhibit 99.1 de {_data_br(doc['data'])}, LPA Ajustado",
                              "data": _data_br(doc["data"]), "url": lido[0]}
                break
    return saida


def contabil_eua(ticker: str, hoje: dt.date, *, cabecalho=cabecalho_sec, buscar_cik=cik_do_ticker) -> dict:
    cab = cabecalho()
    if not cab:
        return {"status": "incompleto", "motivo": "sem SEC_CONTACT_EMAIL"}
    empresa = buscar_cik(ticker, cab)
    if not empresa:
        return {"status": "incompleto", "motivo": "ticker não encontrado na SEC"}
    fatos = _get_sec(f"{SEC_DADOS}/api/xbrl/companyfacts/CIK{empresa[0]}.json", cab).json()
    gaap = lpa_ttm_sec(fatos, hoje)
    if gaap.get("status") != "ok":
        return gaap
    return contabil_ajustado(gaap, ajustados_sec(empresa[0], cab, [t["fim"] for t in gaap["trimestres"]]))


BRASILIA = dt.timezone(dt.timedelta(hours=-3))       # Brasília não tem horário de verão
MESES = ("jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez")
CAMPOS_ATUALIZACAO = ("atualizado_em", "trimestre_ref", "trimestre_data")


def carimbo_atualizacao(c: dict, agora: dt.datetime) -> dict:
    """Indicador de atualização no fim do JSON: "17/11 18:32" (Brasília), "3T26" e "set/26".

    B3 já traz o trimestre em "tri" (ex. "3T26"); EUA só tem "fim" (DD/MM/AAAA) em cada trimestre,
    daí o trimestre é calculado a partir do mês, na mesma notação."""
    base = {k: v for k, v in c.items() if k not in CAMPOS_ATUALIZACAO}
    ultimo = (c.get("trimestres") or [{}])[-1]
    tri, fim = ultimo.get("tri"), None
    if tri:
        fim = fim_do_trimestre(tri)
    elif ultimo.get("fim"):
        fim = _data(ultimo["fim"])
        if fim:
            tri = f"{(fim.month - 1) // 3 + 1}T{fim:%y}"
    return {**base, "atualizado_em": agora.astimezone(BRASILIA).strftime("%d/%m %H:%M"),
            "trimestre_ref": tri, "trimestre_data": f"{MESES[fim.month - 1]}/{fim:%y}" if fim else None}


def aplicar_contabil_br(plano: list[dict], agora: dt.datetime | None = None) -> int:
    """Grava o contábil da B3. Pendente não apaga um valor bom já gravado: só registra o motivo.

    atualizado_em só muda quando a leitura dá certo: pendente mantém a hora da última leitura boa."""
    agora = agora or dt.datetime.now(BRASILIA)
    tab, n = _ler_json(ARQ_CONTABIL_BR, {}), 0
    for i in plano:
        c = i.get("contabil_br")
        if not c:
            continue
        atual = tab.get(i["ticker"]) or {}
        if c.get("status") == "ok":
            novo = carimbo_atualizacao(c, agora)
        elif atual.get("status") != "ok":
            novo = c
        else:
            base = {k: v for k, v in atual.items() if k not in CAMPOS_ATUALIZACAO}
            novo = {**base, "ultima_tentativa": c.get("motivo"), **{k: atual[k] for k in CAMPOS_ATUALIZACAO if k in atual}}
        if novo != atual:
            tab[i["ticker"]] = novo
            n += 1
    if n:
        ARQ_CONTABIL_BR.write_text(json.dumps(dict(sorted(tab.items())), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return n


def aplicar_contabil(plano: list[dict], agora: dt.datetime | None = None) -> int:
    """Grava o contábil da SEC. "incompleto" não apaga um valor bom já gravado, igual à B3:
    atualizado_em só muda quando a leitura dá certo."""
    agora = agora or dt.datetime.now(BRASILIA)
    tab, n = _ler_json(ARQ_CONTABIL, {}), 0
    for i in plano:
        c = i.get("contabil")
        if not c:
            continue
        atual = tab.get(i["ticker"]) or {}
        if c.get("status") == "ok":
            novo = carimbo_atualizacao(c, agora)
        elif atual.get("status") != "ok":
            novo = c
        else:
            base = {k: v for k, v in atual.items() if k not in CAMPOS_ATUALIZACAO}
            novo = {**base, "ultima_tentativa": c.get("motivo"), **{k: atual[k] for k in CAMPOS_ATUALIZACAO if k in atual}}
        if novo != atual:
            tab[i["ticker"]] = novo
            n += 1
    if n:
        ARQ_CONTABIL.write_text(json.dumps(dict(sorted(tab.items())), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return n


# ------------------------------------------------------------ contábil 12 meses da B3 (release de resultados, CVM)
ARQ_CONTABIL_BR = RAIZ / "utils" / "contabil_br.json"
ARQ_CONTABIL_BR_CFG = RAIZ / "utils" / "contabil_br_config.json"   # ticker -> linha do lucro e nome da fonte
RE_TRI = re.compile(r"\b([1-4])T(\d{2})\b")


def trimestre_do_documento(data: dt.date) -> str:
    """Trimestre divulgado num documento entregue nesta data: o último trimestre já encerrado (ex.: 11/11/2026 -> 3T26)."""
    t = (data.month - 1) // 3          # trimestres encerrados no ano
    return f"4T{(data.year - 1) % 100:02d}" if t == 0 else f"{t}T{data.year % 100:02d}"


def fim_do_trimestre(tri: str) -> dt.date:
    q, a = int(tri[0]), 2000 + int(tri[2:])
    return dt.date(a, 12, 31) if q == 4 else dt.date(a, q * 3 + 1, 1) - dt.timedelta(days=1)


def tri_anterior(tri: str) -> str:
    q, a = int(tri[0]), int(tri[2:])
    return f"4T{a - 1:02d}" if q == 1 else f"{q - 1}T{a:02d}"


def _valor_reais(numero: str, unidade: str) -> float:
    return numero_br(numero) * (1e9 if unidade.lower().startswith("bilh") else 1e6)


RE_ACUMULADO = re.compile(r"acumulad|no\s+ano\b|do\s+ano\b|em\s+20\d{2}\b|exerc[íi]cio|semestre|\b[1-2]S\d{2}\b|"
                         r"\b(?:6|9|12)M\d{2}\b|nove\s+meses|seis\s+meses|12\s+meses|doze\s+meses|"
                         r"janeiro\s+a|de\s+jan|at[ée]\s+(?:junho|setembro|dezembro)", re.I)
LUCRO_MINIMO = 1e6         # lucro trimestral abaixo de R$ 1 milhão (ex.: 0,00) = leitura inválida


RE_RELATORIO = re.compile(r"an[áa]lise\s+gerencial|an[áa]lise\s+do\s+desempenho|relat[óo]rio|release|press|"
                          r"divulga[çc][ãa]o\s+de\s+resultados|resultado", re.I)


def ler_lucro_trimestre(texto: str, tri: str, linha: str = "Lucro Líquido Ajustado", tabela_vence: bool = False) -> dict:
    """Lucro da `linha` no trimestre `tri` (ex.: "3T26"), em reais, no release de resultados.

    Leituras: (1) frase do texto ("lucro líquido ajustado de R$ 1,27 bilhão no 3T26", "No 3T26, o lucro líquido
    ajustado foi de R$ 1,3 bilhão", "... R$ 1,3 bilhão no trimestre"); (2) linha da tabela, usando o grupo de
    colunas de trimestres que contém `tri` (releases do BB têm "3T25 2T26 3T26 Var.% ... 9M25 9M26").
    Devolve {"frase", "tabela", "valor", "motivo"}; divergência de mais de 3% = sem valor."""
    t = normalizar(texto)
    nome = re.escape(linha).replace(r"\ ", r"\s+").replace(" ", r"\s+").replace("í", "[ií]").replace("Í", "[IÍ]")
    out = {"frase": None, "tabela": None, "valor": None, "motivo": ""}
    # NUM e UNID já são grupos: 1-2, 3-4 e 5-6 nas três formas da frase
    padrao = (rf"{nome}[^.]{{0,80}}?R\$\s*{NUM}\s*{UNID}[^.]{{0,40}}?\b{tri}\b"
              rf"|\b{tri}\b[^.]{{0,60}}?{nome}[^.]{{0,40}}?R\$\s*{NUM}\s*{UNID}"
              rf"|{nome}[^.]{{0,60}}?R\$\s*{NUM}\s*{UNID}[^.]{{0,12}}?\bno\s+(?:trimestre|período)\b")
    for m in re.finditer(padrao, t, re.I):
        g = m.groups()
        num, uni = next(((g[i], g[i + 1]) for i in (0, 2, 4) if g[i]), (None, None))
        # só o trimestre isolado: frase com acumulado, ano, semestre, 9M/12M é descartada
        contexto = t[max(0, m.start() - 60): m.end() + 50]
        if RE_ACUMULADO.search(contexto):
            continue
        if num and multiplicador(uni):
            out["frase"] = _valor_reais(num, uni)
            break
    # tabela
    for m in re.finditer(rf"{nome}\s+((?:\(?-?\d{{1,3}}(?:\.\d{{3}})*(?:,\d+)?\)?%?\s+){{1,12}})", t, re.I):
        antes = t[max(0, m.start() - 2500): m.start()]
        # grupo de colunas TRIMESTRAIS (1T..4T) que contém o trimestre; grupos acumulados (9M, 12M) não servem
        grupos = [g for g in re.finditer(r"((?:\b[1-4]T\d{2}\b[\s/]*){1,10})", antes)
                  if tri in re.findall(r"\b[1-4]T\d{2}\b", g.group(1))]
        if not grupos:
            continue
        colunas = re.findall(r"\b[1-4]T\d{2}\b", grupos[-1].group(1))
        valores = [v for v in m.group(1).split() if not v.endswith("%")]
        if len(valores) < len(colunas):
            continue
        bruto = valores[colunas.index(tri)]
        num = numero_br(bruto.strip("()")) * (-1 if bruto.startswith("(") else 1)
        unids = re.findall(r"R\$\s*(milh|bilh)|(milh|bilh)[õo]es\s+de\s+reais|em\s+(milh|bilh)[õo]es", antes[-1500:], re.I)
        if unids:
            uni = "bilh" if "bilh" in "".join(unids[-1]).lower() else "milh"
        elif out["frase"]:
            # sem unidade escrita: a que deixa a tabela mais perto da frase
            uni = min(("milh", "bilh"), key=lambda u: abs(num * (1e9 if u == "bilh" else 1e6) - out["frase"]))
        elif abs(num) >= 100:
            uni = "milh"                      # 3.906 sem unidade = R$ milhões
        else:
            continue                          # "3,9" sem unidade e sem frase: ambíguo, não usa
        valor = num * (1e9 if uni == "bilh" else 1e6)
        if abs(valor) < LUCRO_MINIMO:
            continue                          # 0,00 bi: leitura inválida, tenta outra linha / outro documento
        out["tabela"] = valor
        break
    if out["frase"] is not None and abs(out["frase"]) < LUCRO_MINIMO:
        out["frase"] = None
    f, tb = out["frase"], out["tabela"]
    if f is None and tb is None:
        out["motivo"] = f"linha '{linha}' do {tri} não encontrada (nem frase nem tabela)"
    elif tabela_vence and tb is not None:
        # release/relatório de resultados: a tabela trimestral vence sempre; a frase só ajudou na unidade
        out["valor"] = tb
        out["motivo"] = "tabela do relatório" + (f" (frase {f / 1e9:.2f} bi descartada: diverge {abs(f / tb - 1):.1%})"
                                                 if f is not None and abs(f / tb - 1) > 0.10 else "")
    elif f is not None and tb is not None and abs(f / tb - 1) > 0.03:
        out["motivo"] = f"frase ({f / 1e9:.2f} bi) e tabela ({tb / 1e9:.2f} bi) divergem {abs(f / tb - 1):.1%}"
    else:
        out["valor"] = tb if tb is not None else f
        out["motivo"] = "tabela" if tb is not None else "frase"
    return out


def extrair_lucro_trimestre(texto: str, tri: str, linha: str = "Lucro Líquido Ajustado") -> tuple[float | None, str]:
    r = ler_lucro_trimestre(texto, tri, linha)
    return r["valor"], r["motivo"]


def contabil_br_de_trimestres(trimestres: list[dict], acoes: float | None, fonte: str, hoje: dt.date) -> dict:
    """4 trimestres consecutivos -> lucro de 12 meses, LPA = soma ÷ ações. Senão: pendente."""
    if len(trimestres) < 4:
        return {"status": "pendente", "motivo": f"só {len(trimestres)} trimestre(s) lidos dos releases"}
    ult = sorted(trimestres, key=lambda x: fim_do_trimestre(x["tri"]))[-4:]
    if any(tri_anterior(b["tri"]) != a["tri"] for a, b in zip(ult, ult[1:])):
        return {"status": "pendente", "motivo": "trimestres lidos não são consecutivos"}
    if not acoes:
        return {"status": "pendente", "motivo": "número de ações indisponível"}
    soma = sum(x["lucro"] for x in ult)
    return {"status": "ok", "base": "ajustado", "lucro_12m": soma, "acoes": acoes, "lpa_12m": round(soma / acoes, 4),
            "trimestres": ult, "fonte": fonte, "data": ult[-1]["data"], "atualizado": f"{hoje:%d/%m/%Y}"}


def contabil_br(ticker: str, hoje: dt.date, cfg: dict, *, buscar_cnpj=cnpj_do_ticker, buscar_docs=documentos_cvm,
                ler_pdf=texto_do_pdf, buscar_acoes=acoes_yahoo, registrar=None) -> dict:
    """Lê o lucro do trimestre no release de cada um dos 4 últimos trimestres (documentos da CVM).

    Escreve no log uma linha por documento lido: "BBAS3 3T26: frase=... tabela=... divergência=... gravou=..."."""
    registrar = registrar or (lambda msg: (log.info(msg), print(msg, flush=True) if os.environ.get("GITHUB_ACTIONS") else None))
    empresa = buscar_cnpj(ticker, hoje)
    if not empresa:
        registrar(f"{ticker}: CNPJ não encontrado na CVM")
        return {"status": "pendente", "motivo": "CNPJ não encontrado na CVM"}
    linha, fonte = cfg.get("linha", "Lucro Líquido Ajustado"), cfg.get("fonte", f"{ticker}, Divulgação de Resultados")
    docs = buscar_docs(empresa[0], hoje)
    registrar(f"{ticker}: {len(docs)} documento(s) de resultado/projeção na CVM")
    # na mesma data, o release de resultados vem antes de fato relevante, ITR etc.
    prioridade = re.compile(r"resultado|desempenho|release|press", re.I)
    docs = sorted(docs, key=lambda d: (d["data"], bool(prioridade.search(f"{d.get('categoria','')} {d.get('tipo','')} {d.get('assunto','')}"))), reverse=True)
    lidos, textos_lidos = {}, []
    for doc in docs:                                           # do mais novo para o mais antigo
        d = _data(doc["data"])
        if not d:
            continue
        tri = trimestre_do_documento(d)
        if tri in lidos:
            continue
        nome_doc = f"{_data_br(doc['data'])} {doc.get('categoria', '')} / {doc.get('tipo', '')} / {doc.get('assunto', '')}".strip()
        try:
            _, texto = ler_pdf(doc["link"])
        except Exception as e:  # noqa: BLE001
            registrar(f"{ticker} {tri}: doc={nome_doc} link={doc['link']} gravou=não motivo=não abriu ({e.__class__.__name__})")
            continue
        relatorio = bool(RE_RELATORIO.search(f"{doc.get('categoria', '')} {doc.get('tipo', '')} {doc.get('assunto', '')}"))
        if relatorio:
            textos_lidos.append((tri, nome_doc, doc, texto))
        r = ler_lucro_trimestre(texto, tri, linha, tabela_vence=relatorio)
        bi = lambda v: "—" if v is None else f"{v / 1e9:.2f} bi"
        div = "—" if r["frase"] is None or r["tabela"] is None else f"{abs(r['frase'] / r['tabela'] - 1):.1%}"
        registrar(f"{ticker} {tri}: frase={bi(r['frase'])} tabela={bi(r['tabela'])} divergência={div} "
                  f"gravou={'sim' if r['valor'] is not None else 'não'} motivo={r['motivo']} doc={nome_doc} link={doc['link']}")
        if r["valor"] is None:
            continue
        lidos[tri] = {"tri": tri, "fim": f"{fim_do_trimestre(tri):%d/%m/%Y}", "lucro": r["valor"], "fonte": fonte,
                      "data": _data_br(doc["data"]), "url": doc["link"], "leitura": r["motivo"]}
        ordem = sorted(lidos, key=fim_do_trimestre)
        if len(ordem) >= 4 and all(tri_anterior(b) == a for a, b in zip(ordem[-4:], ordem[-3:])):
            break
    if lidos:
        alvo = [max(lidos, key=fim_do_trimestre)]
        while len(alvo) < 4:
            alvo.append(tri_anterior(alvo[-1]))
        for tri_falta in [x for x in alvo if x not in lidos]:
            # último recurso: a coluna desse trimestre na tabela de um release posterior (ex.: 2T26 traz "1T26 2T26")
            for tri_doc, nome_doc, doc, texto in textos_lidos:
                if fim_do_trimestre(tri_doc) <= fim_do_trimestre(tri_falta):
                    continue
                r = ler_lucro_trimestre(texto, tri_falta, linha, tabela_vence=True)
                if r["tabela"] is not None and r["valor"] is not None:
                    lidos[tri_falta] = {"tri": tri_falta, "fim": f"{fim_do_trimestre(tri_falta):%d/%m/%Y}", "lucro": r["valor"],
                                        "fonte": fonte, "data": _data_br(doc["data"]), "url": doc["link"],
                                        "leitura": f"tabela do release do {tri_doc}"}
                    registrar(f"{ticker} {tri_falta}: tabela={r['valor'] / 1e9:.2f} bi gravou=sim motivo=coluna {tri_falta} "
                              f"na tabela do release do {tri_doc} doc={nome_doc}")
                    break
            else:
                registrar(f"{ticker} {tri_falta}: gravou=não motivo=nenhum documento com o lucro do trimestre lido")
    resultado = contabil_br_de_trimestres(list(lidos.values()), buscar_acoes(ticker), fonte, hoje)
    resultado["lidos"] = {k: round(v["lucro"] / 1e9, 4) for k, v in sorted(lidos.items(), key=lambda x: fim_do_trimestre(x[0]))}
    registrar(f"{ticker}: contábil {resultado['status']}"
              + (f" lucro 12m {resultado['lucro_12m'] / 1e9:.2f} bi, LPA {resultado['lpa_12m']:.2f}" if resultado["status"] == "ok"
                 else f" ({resultado.get('motivo')})"))
    return resultado


# ------------------------------------------------------------ projeção do início do ano (congelada)
def _janela_inicial(ano: str) -> tuple[dt.date, dt.date, int]:
    """Período em que sai o primeiro guidance do ano: release do 4T do ano anterior (jan-abr) e o 10-K.
    Ano fiscal (FY2027): o ano fiscal pode começar no meio do ano anterior, então a janela começa em julho."""
    fiscal = ano.upper().startswith("FY")
    n = int(re.sub(r"\D", "", ano))
    inicio = dt.date(n - 1, 7, 1) if fiscal else dt.date(n, 1, 1)
    return inicio, dt.date(n, 4, 30), n


def documentos_sec_periodo(cik: str, cab: dict, inicio: dt.date, fim: dt.date) -> list[dict]:
    """8-K de resultado (2.02), 6-K e 10-K entre as datas, do MAIS ANTIGO para o mais novo."""
    sub = _get_sec(f"{SEC_DADOS}/submissions/CIK{cik}.json", cab).json()
    rec = sub.get("filings", {}).get("recent", {})
    n = len(rec.get("form", []))
    docs = []
    for i in range(n):
        form, data = rec["form"][i], rec["filingDate"][i]
        itens = (rec.get("items") or [""] * n)[i]
        d = _data(data)
        if not d or not inicio <= d <= fim:
            continue
        if form == "8-K" and "2.02" not in (itens or ""):
            continue
        if form not in ("8-K", "6-K", "10-K"):
            continue
        docs.append({"form": form, "data": data, "acc": rec["accessionNumber"][i], "cik": cik,
                     "principal": (rec.get("primaryDocument") or [""] * n)[i]})
    return sorted(docs, key=lambda x: x["data"])


def texto_sec(doc: dict, cab: dict) -> tuple[str, str] | None:
    """8-K/6-K: o press release (Exhibit 99.1). 10-K: o documento principal."""
    if doc["form"] == "10-K" and doc.get("principal"):
        url = f"{SEC_ARQUIVOS}/Archives/edgar/data/{int(doc['cik'])}/{doc['acc'].replace('-', '')}/{doc['principal']}"
        return url, texto_de_html(_get_sec(url, cab).text)
    return anexo_sec(doc, cab)


def buscar_inicial_eua(ticker: str, ano: str, *, cabecalho=cabecalho_sec, buscar_cik=cik_do_ticker,
                       buscar_docs=documentos_sec_periodo, ler=texto_sec) -> tuple[dict | None, str]:
    """Primeiro guidance de LPA para o ano (`2026` ou `FY2027`). Devolve (novo, motivo)."""
    cab = cabecalho()
    if not cab:
        return None, "sem SEC_CONTACT_EMAIL"
    empresa = buscar_cik(ticker, cab)
    if not empresa:
        return None, "ticker não encontrado na SEC"
    cik, nome = empresa
    inicio, fim, n = _janela_inicial(ano)
    for doc in buscar_docs(cik, cab, inicio, fim):
        try:
            lido = ler(doc, cab)
        except Exception as e:  # noqa: BLE001
            log.info("  inicial: não abriu %s de %s (%s)", doc["form"], _data_br(doc["data"]), e.__class__.__name__)
            continue
        if not lido:
            continue
        link, texto = lido
        ex = extrair_eps_eua(texto, n)
        if not ex or ex["ano"] != n:
            continue
        if ex["confianca"] != "alta":
            return None, "projeção inicial encontrada sem confiança: " + "; ".join(ex["motivos"])
        return ({"lpa_min": ex["lpa_min"], "lpa_max": ex["lpa_max"], "lucro_tipo": "LPA ajustado",
                 "fonte": f"{nome}, Form {doc['form']}{' Exhibit 99.1' if doc['form'] != '10-K' else ''} de {_data_br(doc['data'])} (SEC)",
                 "data": _data_br(doc["data"]), "url": link, "metodo": "robô (primeiro documento do ano)",
                 "trecho": ex["trecho"][:400]}, "")
    return None, "sem projeção inicial encontrada"


def buscar_inicial_br(ticker: str, ano: str, *, buscar_cnpj=cnpj_do_ticker, buscar_docs=documentos_cvm,
                      ler_pdf=texto_do_pdf, buscar_acoes=acoes_yahoo) -> tuple[dict | None, str]:
    """Primeiro guidance de lucro do ano nos documentos da CVM (jan a abr). Só com confiança alta."""
    n = int(re.sub(r"\D", "", ano))
    empresa = buscar_cnpj(ticker, dt.date(n, 12, 31))
    if not empresa:
        return None, "CNPJ não encontrado na CVM"
    cnpj, nome = empresa
    docs = [d for d in buscar_docs(cnpj, dt.date(n, 12, 31))
            if (x := _data(d["data"])) and dt.date(n, 1, 1) <= x <= dt.date(n, 4, 30)]
    for doc in sorted(docs, key=lambda d: d["data"]):
        try:
            _, texto = ler_pdf(doc["link"])
        except Exception:  # noqa: BLE001
            continue
        ex = extrair_por_padroes(texto, n)
        if ex is None or ex.ano != n:
            continue
        if ex.confianca != "alta":
            return None, "projeção inicial encontrada sem confiança: " + "; ".join(ex.motivos)
        acoes = buscar_acoes(ticker)
        if not acoes:
            return None, "número de ações indisponível"
        return ({"lucro_min": ex.lucro_min, "lucro_max": ex.lucro_max, "acoes": acoes,
                 "fonte": f"{nome}, {doc['categoria'] or 'documento'} de {_data_br(doc['data'])} (CVM)",
                 "data": _data_br(doc["data"]), "url": doc["link"], "metodo": "robô (primeiro documento do ano)",
                 "trecho": ex.trecho[:400]}, "")
    return None, "sem projeção inicial encontrada"


def ano_alvo(ticker: str, hoje: dt.date) -> str:
    """Ano da projeção: o período do guidance atual (ex.: FY2027) ou o ano corrente."""
    from utils.override import tabela
    return str((tabela().get(ticker) or {}).get("periodo") or hoje.year)


def planejar_inicial(ticker: str, hoje: dt.date, iniciais: dict) -> dict | None:
    """Busca a projeção inicial só se ainda não houver uma gravada (congelada)."""
    from utils.override import _tem_projecao
    ano = ano_alvo(ticker, hoje)
    if _tem_projecao((iniciais.get(ticker) or {}).get(ano)):
        return None                                      # já travada: nunca busca de novo
    br = bool(re.fullmatch(r"(?=.*[A-Z])[A-Z0-9]{4}\d{1,2}", ticker))
    novo, motivo = (buscar_inicial_br if br else buscar_inicial_eua)(ticker, ano)
    return {"ano": ano, "novo": novo, "motivo": motivo}


def _ler_json(caminho: Path, padrao):
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return padrao



# ------------------------------------------------------------ fila pública de tickers novos (Issues do GitHub)
def processar_fila(hoje: dt.date | None = None, *, token: str | None = None, max_por_run: int = FILA_MAX_POR_RUN,
                   listar=None, fechar=None, planejar_br=planejar_ticker, planejar_us=planejar_ticker_eua) -> list[dict]:
    """Processa a fila pública (Issues "fila-ticker", ver utils/fila_github.py): tenta validar o
    guidance de cada ticker novo com as MESMAS travas de "Fonte oficial" e "Número em 2 lugares"
    usadas no AUTOMÁTICO COM PROTEÇÃO. Validado -> entra em guidance_tickers.json (o robô diário
    passa a acompanhar; o primeiro guidance ainda precisa da sua aprovação no PR, igual qualquer
    ticker novo). Não validado -> fica registrado para sempre em queue_nao_validado.json, e o app
    para de mostrar "ainda não verificado" para ele. Nunca inventa número: na dúvida, não cadastra.

    Processa no máximo `max_por_run` por execução (a mais pedida primeiro); o resto fica na fila
    para a próxima execução do workflow."""
    hoje = hoje or dt.date.today()
    token = token or os.environ.get("GITHUB_QUEUE_TOKEN")
    if not token:
        log.warning("fila: sem GITHUB_QUEUE_TOKEN (Secret do GitHub): não processei a fila pública")
        return []
    import utils.fila_github as fgh
    listar = listar or (lambda tok: fgh.listar_fila(tok))
    fechar = fechar or (lambda n, tok, c: fgh.fechar_issue(n, tok, c))

    registrados = set(t.upper() for t in _ler_json(ARQ_TICKERS, []))
    nao_validados = _ler_json(ARQ_NAO_VALIDADO, {})
    try:
        fila = listar(token)
    except Exception as e:  # noqa: BLE001
        log.warning("fila: não consegui ler a fila (%s: %s)", e.__class__.__name__, e)
        return []
    candidatos = [f for f in fila if f["ticker"].upper() not in registrados and f["ticker"].upper() not in nao_validados]
    resultados = []
    for item in candidatos[:max_por_run]:
        ticker = item["ticker"].strip().upper()
        log.info("fila: %s (%d pedido(s))", ticker, item["pedidos"])
        if not re.fullmatch(r"[A-Z0-9.]{1,10}", ticker):
            fechar(item["numero"], token, "Ticker com formato inválido: ignorado, não processado.")
            continue
        try:
            plano = (planejar_br(ticker, hoje, None, set()) if re.fullmatch(r"(?=.*[A-Z])[A-Z0-9]{4}\d{1,2}", ticker)
                     else planejar_us(ticker, hoje, None))
        except Exception as e:  # noqa: BLE001
            plano = {"acao": "erro", "motivo": f"{e.__class__.__name__}: {e}", "travas": []}
        motivo = plano.get("motivo", "")
        if "SEC_CONTACT_EMAIL" in motivo:
            log.warning("fila: %s pulado (%s) — problema de configuração, não do ticker; tenta de novo na próxima execução", ticker, motivo)
            continue
        travas = {t["nome"]: t["ok"] for t in plano.get("travas", [])}
        validado = bool(travas.get("Fonte oficial") and travas.get("Número em 2 lugares"))
        data_txt = f"{hoje:%d/%m/%Y}"
        resultados.append({"ticker": ticker, "pedidos": item["pedidos"], "data": data_txt, "motivo": motivo, "validado": validado})
        if validado:
            registrados.add(ticker)
            fechar(item["numero"], token,
                  "✅ Validado: a fonte é o documento oficial e o número aparece confirmado nele. "
                  f"**{ticker}** foi adicionado a `utils/guidance_tickers.json` — o robô diário passa a "
                  "acompanhar. O guidance em si ainda precisa da sua aprovação no pull request (mesma regra "
                  "de qualquer ticker novo: a primeira leitura nunca publica sozinha).")
        else:
            nao_validados[ticker] = {"motivo": motivo or "guidance não encontrado com segurança", "data": data_txt}
            fechar(item["numero"], token,
                  f"🔒 Não validado: {motivo or 'não encontrei um guidance confirmado com segurança no documento oficial'}. "
                  f"**{ticker}** não foi cadastrado — nenhum número é mostrado sem confirmação. "
                  "O app passa a mostrar só os dados do Yahoo Finance para este ticker.")
    if any(r["validado"] for r in resultados):
        ARQ_TICKERS.write_text(json.dumps(sorted(registrados), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if any(not r["validado"] for r in resultados):
        ARQ_NAO_VALIDADO.write_text(json.dumps(dict(sorted(nao_validados.items())), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return resultados


def planejar(hoje: dt.date | None = None) -> list[dict]:
    hoje = hoje or dt.date.today()
    tickers = [t.strip().upper() for t in _ler_json(ARQ_TICKERS, [])]
    auto = _ler_json(ARQ_AUTO, {})
    vistos_por_ticker = _ler_json(ARQ_VISTOS, {})
    iniciais = _ler_json(ARQ_INICIAL, {})
    registro = _ler_json(ARQ_LOG, [])
    try:
        from utils.override import OVERRIDE as manuais
    except Exception:  # noqa: BLE001
        manuais = {}
    plano = []
    for t in tickers:
        log.info("%s", t)
        vistos = set(vistos_por_ticker.get(t, []))
        try:
            # base da trava de 20%: o guidance que o app mostra (cadastro manual ganha do automático)
            item = planejar_ticker(t, hoje, auto.get(t), vistos, referencia=manuais.get(t) or auto.get(t))
        except Exception as e:  # noqa: BLE001 - um ticker com erro não derruba os outros
            item = {"ticker": t, "acao": "erro", "motivo": f"{e.__class__.__name__}: {e}", "novo": None, "anterior": auto.get(t)}
        try:
            ini = planejar_inicial(t, hoje, iniciais)
        except Exception as e:  # noqa: BLE001
            ini = {"ano": ano_alvo(t, hoje), "novo": None, "motivo": f"{e.__class__.__name__}: {e}"}
        cfg_br = _ler_json(ARQ_CONTABIL_BR_CFG, {})
        if t in cfg_br:
            try:
                item["contabil_br"] = contabil_br(t, hoje, cfg_br[t])
            except Exception as e:  # noqa: BLE001
                item["contabil_br"] = {"status": "pendente", "motivo": f"{e.__class__.__name__}: {e}"}
            log.info("  contábil B3: %s", item["contabil_br"].get("lpa_12m") or item["contabil_br"].get("motivo"))
        if not re.fullmatch(r"(?=.*[A-Z])[A-Z0-9]{4}\d{1,2}", t):
            try:
                item["contabil"] = contabil_eua(t, hoje)
            except Exception as e:  # noqa: BLE001
                item["contabil"] = {"status": "incompleto", "motivo": f"{e.__class__.__name__}: {e}"}
            log.info("  contábil SEC: %s", item["contabil"].get("lpa_12m") or item["contabil"].get("motivo"))
        if ini:
            item["inicial"] = ini
            log.info("  projeção inicial %s: %s", ini["ano"], "achada" if ini["novo"] else ini["motivo"])
        vistos_por_ticker[t] = sorted(vistos)[-50:]
        if item["acao"] == "pr":
            item["ja_avisado"] = ja_avisado(registro, item)
        for tr in item.get("travas", []):
            log.info("  [%s] %s: %s", "ok" if tr["ok"] else "TRAVOU", tr["nome"], tr["detalhe"])
        if item["acao"] == "pr" and os.environ.get("GITHUB_ACTIONS"):
            print(f"::warning title=Guidance {t} travado::{item['motivo']}", flush=True)
        nivel = logging.ERROR if item["acao"] == "erro" else logging.INFO
        log.log(nivel, "  -> %s: %s", item["acao"], item["motivo"])
        if item["acao"] in ("nada", "erro") and os.environ.get("GITHUB_ACTIONS"):
            anterior = auto.get(t)
            print(f"{t}: sem guidance novo; " + ("mantido o anterior de " + str(anterior.get("data")) if anterior else "nenhum guidance gravado"),
                  flush=True)
        if item["acao"] == "erro" and os.environ.get("GITHUB_ACTIONS"):
            # aparece como aviso amarelo no resumo da execução, mesmo com o robô terminando "verde"
            print(f"::warning title=Guidance {t} não gravado::{item['motivo']}", flush=True)
        plano.append(item)
    ARQ_VISTOS.parent.mkdir(exist_ok=True)
    ARQ_VISTOS.write_text(json.dumps(vistos_por_ticker, ensure_ascii=False, indent=2), encoding="utf-8")
    return plano


def aplicar(plano: list[dict], tipo: str, hoje: dt.date | None = None) -> list[dict]:
    """"commit": grava em guidance_auto.json o que passou nas 4 travas e registra no log tudo o que foi
    publicado ou travado. "pr": grava os travados (vão para o pull request), só se houver algum ainda não avisado."""
    auto = _ler_json(ARQ_AUTO, {})
    aplicados = [i for i in plano if i["acao"] == tipo and i["novo"]]
    if tipo == "pr" and all(i.get("ja_avisado") for i in aplicados):
        return []                                  # nada novo travado: não abre de novo o mesmo aviso
    for i in aplicados:
        auto[i["ticker"]] = i["novo"]
    if aplicados:
        ARQ_AUTO.write_text(json.dumps(dict(sorted(auto.items())), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if tipo == "commit":
        registrar(plano, hoje or dt.date.today())
        aplicar_iniciais(plano)
        aplicar_contabil(plano)
        aplicar_contabil_br(plano)
    return aplicados


# ------------------------------------------------------------ log de decisões e resumo de sexta
def _faixa_txt(n: dict) -> str:
    if "lpa_min" in n:
        return f"LPA {n['lpa_min']:.2f} a {n['lpa_max']:.2f} ({n.get('periodo') or n.get('ano')})"
    if "lucro_min" in n and "lucro_max" in n:
        return f"lucro R$ {n['lucro_min'] / 1e9:.1f} a {n['lucro_max'] / 1e9:.1f} bi ({n.get('ano')})".replace(".", ",")
    return "faixa não informada"


def ja_avisado(registro: list[dict], item: dict) -> bool:
    """Mesmo documento e mesma faixa já travados antes: não avisa de novo todo dia."""
    n = item.get("novo") or {}
    return any(r.get("ticker") == item["ticker"] and r.get("decisao") == "travado"
               and r.get("documento") == n.get("documento") and r.get("faixa") == _faixa_txt(n) for r in registro)


def registrar(plano: list[dict], hoje: dt.date) -> list[dict]:
    """Acrescenta em guidance_log.json o que foi publicado sozinho e o que travou (sem repetir travados)."""
    registro = _ler_json(ARQ_LOG, [])
    novos = []
    for i in plano:
        if i["acao"] not in ("commit", "pr") or not i.get("novo") or (i["acao"] == "pr" and ja_avisado(registro, i)):
            continue
        n = i["novo"]
        novos.append({"data": hoje.isoformat(), "ticker": i["ticker"],
                      "decisao": "publicado" if i["acao"] == "commit" else "travado",
                      "faixa": _faixa_txt(n), "fonte": n.get("fonte"), "url": n.get("url"), "documento": n.get("documento"),
                      "travas": i.get("travas", []), "duvidas": i.get("duvidas", []), "motivo": i["motivo"]})
    if novos:
        registro = (registro + novos)[-500:]
        ARQ_LOG.write_text(json.dumps(registro, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return novos


def _linhas_travas(i: dict) -> list[str]:
    return [f"  - {'✅' if t['ok'] else '❌'} {t['nome']}: {t['detalhe']}" for t in i.get("travas", [])] + \
           [f"  - ❓ Dúvida: {d}" for d in i.get("duvidas", [])]


def aviso_publicado(itens: list[dict]) -> str:
    linhas = ["O robô publicou sozinho no app (passou nas 4 travas do AUTOMÁTICO COM PROTEÇÃO).", ""]
    for i in itens:
        n, ref = i["novo"], i.get("anterior") or {}
        linhas += [f"## {i['ticker']}: {_faixa_txt(n)}", "",
                   f"- **Anterior no robô:** " + (_faixa_txt(ref) if ref.get("lpa_min") or ref.get("lucro_min") else "nenhum"),
                   f"- **Fonte:** [{n['fonte']}]({n['url']})",
                   f"- **Trecho:** \"{n['trecho']}\"", "- **Travas:**", *_linhas_travas(i), ""]
    linhas.append("Se algo estiver errado, cadastre o valor certo em utils/override.py (o manual ganha do automático).")
    return "\n".join(linhas)


def resumo_semana(registro: list[dict], hoje: dt.date, dias: int = 7) -> str:
    inicio = hoje - dt.timedelta(days=dias - 1)
    semana = [r for r in registro if inicio.isoformat() <= r.get("data", "") <= hoje.isoformat()]
    pub = [r for r in semana if r["decisao"] == "publicado"]
    trav = [r for r in semana if r["decisao"] == "travado"]
    linhas = [f"Semana de {inicio:%d/%m/%Y} a {hoje:%d/%m/%Y}.", "",
              f"## Publicado sozinho ({len(pub)})", ""]
    linhas += [f"- **{r['ticker']}** ({_data_br(r['data'])}): {r['faixa']}. [{r['fonte']}]({r['url']})" for r in pub] or ["- Nada."]
    linhas += ["", f"## Travado para você decidir ({len(trav)})", ""]
    for r in trav:
        linhas += [f"- **{r['ticker']}** ({_data_br(r['data'])}): {r['faixa']}. [{r['fonte']}]({r['url']})", *_linhas_travas(r)]
    if not trav:
        linhas.append("- Nada.")
    else:
        linhas += ["", "Os travados estão no pull request \"Guidance para revisar\": aprovar (merge) publica; fechar descarta."]
    return "\n".join(linhas)


def aplicar_iniciais(plano: list[dict]) -> int:
    """Grava as projeções iniciais achadas (ou o aviso de que não achou). Nunca sobrescreve uma já gravada."""
    from utils.override import gravar_inicial
    tab, n = _ler_json(ARQ_INICIAL, {}), 0
    for i in plano:
        ini = i.get("inicial")
        if not ini:
            continue
        tab, gravou = gravar_inicial(tab, i["ticker"], ini["ano"], ini["novo"])
        n += gravou
    if n:
        ARQ_INICIAL.write_text(json.dumps(dict(sorted(tab.items())), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return n


def resumo_pr(itens: list[dict]) -> str:
    def bi(v):
        return f"R$ {v / 1e9:,.1f} bi".replace(",", "X").replace(".", ",").replace("X", ".")

    linhas = ["AUTOMÁTICO COM PROTEÇÃO: estes guidances NÃO foram publicados porque falharam em alguma trava "
              "(ou ficou dúvida). Nada mudou no app. Aprovar (merge) publica; fechar descarta.", ""]
    for i in itens:
        n, a = i["novo"], i.get("anterior") or {}
        payout = "—" if n.get("payout") is None else f"{n['payout']:.0%}"
        novo_txt = (f"LPA de {n['lpa_min']:.2f} a {n['lpa_max']:.2f} ({n.get('periodo') or n.get('ano')})"
                    + (f", dividendo anual {n['dividendo']:.2f}" if n.get("dividendo") else "")) if "lpa_min" in n \
            else f"lucro de {bi(n['lucro_min'])} a {bi(n['lucro_max'])} ({n.get('ano')}), payout {payout}"
        linhas += [f"## {i['ticker']}", "",
                   f"- **Novo:** {novo_txt}, LPA projetado {_lpa(n):.2f}",
                   f"- **Anterior:** " + (f"LPA {_lpa(a):.2f}" if _lpa(a) else "nenhum"),
                   f"- **O que travou:** {i['motivo']}",
                   *(["- **Travas:**", *_linhas_travas(i)] if i.get("travas") else []),
                   *(["- Já avisado antes (mesmo documento)."] if i.get("ja_avisado") else []),
                   f"- **Método:** {n['metodo']}",
                   *([f"- **Histórico devolvido pela API:** {_historico_txt(n['historico'])}"] if n.get("historico") else []),
                   f"- **Fonte:** [{n['fonte']}]({n['url']})",
                   f"- **Trecho do documento:** \"{n['trecho']}\"", ""]
    linhas.append("Confira o trecho no documento original antes de aprovar. Se estiver errado, feche o PR sem juntar.")
    return "\n".join(linhas)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    pp = sub.add_parser("planejar")
    pp.add_argument("--saida", default="plano.json")
    pa = sub.add_parser("aplicar")
    pa.add_argument("plano")
    pa.add_argument("--tipo", choices=["commit", "pr"], required=True)
    pa.add_argument("--resumo")
    pa.add_argument("--aviso", help="arquivo com o aviso dos publicados sozinho (vira issue)")
    pr = sub.add_parser("resumo", help="resumo da semana: publicados e travados")
    pr.add_argument("--dias", type=int, default=7)
    pr.add_argument("--saida", default="resumo.md")
    pf = sub.add_parser("fila", help="processa a fila pública de tickers novos (Issues do GitHub)")
    pf.add_argument("--max", type=int, default=FILA_MAX_POR_RUN)
    sub.add_parser("outlook-trimestral", help="guidance trimestral (EUA), só informativo")
    args = p.parse_args(argv)
    if args.cmd == "outlook-trimestral":
        tab = atualizar_outlook_trimestral_eua()
        log.info("outlook trimestral: %d ticker(s) com dado", len(tab))
        return 0
    if args.cmd == "resumo":
        Path(args.saida).write_text(resumo_semana(_ler_json(ARQ_LOG, []), dt.date.today(), args.dias), encoding="utf-8")
        return 0
    if args.cmd == "fila":
        resultados = processar_fila(max_por_run=args.max)
        validados = sum(r["validado"] for r in resultados)
        log.info("fila: %d ticker(s) processado(s), %d validado(s), %d travado(s)",
                 len(resultados), validados, len(resultados) - validados)
        return 0
    if args.cmd == "planejar":
        plano = planejar()
        Path(args.saida).write_text(json.dumps(plano, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("plano: %s", ", ".join(f"{i['ticker']}={i['acao']}" for i in plano) or "nenhum ticker")
        return 0
    plano = json.loads(Path(args.plano).read_text(encoding="utf-8"))
    aplicados = aplicar(plano, args.tipo)
    log.info("%s: %d ticker(s) gravado(s)", args.tipo, len(aplicados))
    if args.resumo and aplicados:
        Path(args.resumo).write_text(resumo_pr(aplicados), encoding="utf-8")
    if args.aviso and aplicados and args.tipo == "commit":
        Path(args.aviso).write_text(aviso_publicado(aplicados), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
