#!/usr/bin/env python3
"""
FINTAI - cálculo automático do TTM diário, com catch-up.

Uso:
    python utils/ttm_auto.py                 # processa de last_run+1 até hoje
    python utils/ttm_auto.py --hoje 2026-11-19
    python utils/ttm_auto.py --dir caminho/para/utils

Regras principais
-----------------
* Lê a lista de tickers de utils/guidance_tickers.json (nunca lista fixa).
* Lê utils/last_run.json; se não existir, cria com hoje - 7 dias.
* Processa CADA dia de last_run+1 até hoje (inclusive) e CADA ticker.
* Só recalcula o TTM quando há documento oficial novo no dia (ou quando o
  ticker ainda não tem histórico / está pendente). Sem documento novo, mantém
  o TTM anterior e atualiza só preço e P/L.
* Lucro e LPA só saem de fonte oficial: SEC (XBRL / 8-K / 6-K) ou CVM (ITR/DFP).
  Yahoo / Brapi / BCB servem apenas para cotação e dólar.
* Se um dado oficial não for encontrado, o campo fica vazio (null) e o status
  vira PENDENTE_*. Nada é estimado.
* last_run.json e ttm_diario.json só são gravados se a execução terminar sem
  erro. Se falhar, o próximo dia reprocessa os dias perdidos (catch-up).

Variáveis de ambiente
---------------------
SEC_USER_AGENT  obrigatório para a SEC (ex.: "FINTAI seu-email@dominio.com")
BRAPI_TOKEN     opcional (fallback de cotação BR / dólar)
FINTAI_HOJE     opcional, força a data de "hoje" (YYYY-MM-DD) para testes
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
import time
import zipfile
from datetime import date, datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from typing import Any

try:
    from zoneinfo import ZoneInfo
    TZ_BR = ZoneInfo("America/Sao_Paulo")
except Exception:  # pragma: no cover
    TZ_BR = timezone(timedelta(hours=-3))

# ---------------------------------------------------------------------------
# Configuração por ativo
# ---------------------------------------------------------------------------

DOMINIOS_OFICIAIS = ("sec.gov", "cvm.gov.br")

# Regras de cálculo por ticker. Ticker que não estiver aqui usa o padrão:
#   - termina com dígito (B3)  -> precisa de CNPJ, senão fica PENDENTE
#   - caso contrário (EUA)     -> XBRL padrão (NetIncomeLoss / EPS diluído)
ATIVOS: dict[str, dict[str, Any]] = {
    "AAPL": {"mercado": "EUA", "regra": "xbrl"},
    "ADM": {"mercado": "EUA", "regra": "xbrl"},
    "HSIC": {"mercado": "EUA", "regra": "xbrl"},
    "ACM": {
        "mercado": "EUA",
        "regra": "xbrl",
        # AECOM: lucro de OPERAÇÕES CONTÍNUAS (o total inclui descontinuadas)
        "tags_lucro": [
            "IncomeLossFromContinuingOperationsAttributableToParent",
            "IncomeLossFromContinuingOperations",
        ],
        "tags_lpa": ["IncomeLossFromContinuingOperationsPerDilutedShare"],
        "lpa_tipo": "diluido_operacoes_continuas",
    },
    "XP": {
        "mercado": "EUA",
        "regra": "xp_ajustado",  # lucro e LPA diluído AJUSTADOS (gerencial) do 6-K
        "moeda_lpa": "BRL",
        "moeda_preco": "USD",
    },
    "NVDA": {"mercado": "EUA", "regra": "guidance_receita"},
    "TGT": {
        "mercado": "EUA",
        "regra": "guidance_lpa",
        "lpa_guidance": 11.03,          # com reembolso de tarifas
        "lpa_limpo": 8.89,              # sem reembolso (anotado)
        "contexto": ["EPS"],
        "lpa_tipo": "guidance_com_reembolso_tarifas",
    },
    "PANW": {
        "mercado": "EUA",
        "regra": "guidance_lpa",
        "lpa_guidance": 4.28,
        "contexto": ["non-GAAP", "EPS"],
        "lpa_tipo": "guidance_nao_gaap",
    },
    "PETR4": {
        "mercado": "BR",
        "regra": "cvm",
        "cnpj": "33.000.167/0001-01",
        "acoes": 12.89e9,   # ~12,89 bi ações em circulação
        "yahoo": "PETR4.SA",
        "lpa_tipo": "lucro_atribuivel_div_acoes",
    },
    "BBAS3": {
        "mercado": "BR",
        "regra": "cvm",
        "cnpj": "00.000.000/0001-91",
        "acoes": 5.73e9,    # ~5,73 bi ações
        "yahoo": "BBAS3.SA",
        "lpa_tipo": "lucro_contabil_div_acoes",
    },
}

TAGS_LUCRO_PADRAO = ["NetIncomeLoss"]
TAGS_LPA_PADRAO = ["EarningsPerShareDiluted"]

FORMS_RESULTADO_EUA = {"10-Q", "10-K", "10-Q/A", "10-K/A", "20-F", "6-K"}
ITENS_8K_RESULTADO = {"2.02"}
ITENS_8K_GUIDANCE = {"2.02", "7.01"}

# Se o último trimestre oficial terminou mais de N dias antes do documento
# novo, o trimestre divulgado ainda não chegou ao XBRL/CVM -> pendente.
JANELA_TRIMESTRE_DIAS = 100


class ErroRede(Exception):
    """Falha transitória (rede/servidor). Faz a execução falhar -> catch-up amanhã."""


# ---------------------------------------------------------------------------
# Utilidades de data / arquivos
# ---------------------------------------------------------------------------

def _d(s: str) -> date:
    return date.fromisoformat(s[:10])


def hoje_brasilia() -> date:
    forcado = os.environ.get("FINTAI_HOJE")
    if forcado:
        return _d(forcado)
    return datetime.now(TZ_BR).date()


def dias_faltantes(last_run: date, hoje: date) -> list[date]:
    """Dias de last_run+1 até hoje, inclusive. Vazio se já rodou hoje."""
    dias = []
    d = last_run + timedelta(days=1)
    while d <= hoje:
        dias.append(d)
        d += timedelta(days=1)
    return dias


def ler_json(caminho: Path, padrao: Any) -> Any:
    if not caminho.exists():
        return padrao
    with caminho.open(encoding="utf-8") as f:
        return json.load(f)


def gravar_json_atomico(caminho: Path, dados: Any) -> None:
    tmp = caminho.with_suffix(caminho.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp.replace(caminho)


def ler_last_run(caminho: Path, hoje: date) -> date:
    """Lê last_run.json. Se não existir, cria com hoje - 7 dias."""
    if not caminho.exists():
        inicial = hoje - timedelta(days=7)
        gravar_json_atomico(caminho, {"last_run": inicial.isoformat(),
                                      "criado_automaticamente": True})
        return inicial
    dados = ler_json(caminho, {})
    return _d(dados["last_run"])


def link_oficial_valido(link: str | None) -> bool:
    if not link:
        return False
    m = re.match(r"https?://([^/]+)/", link + "/")
    if not m:
        return False
    host = m.group(1).lower()
    return any(host == dom or host.endswith("." + dom) for dom in DOMINIOS_OFICIAIS)


def _num(txt: str) -> float:
    return float(txt.replace(",", ""))


def _num_br(txt: str) -> float:
    return float(txt.replace(".", "").replace(",", "."))


def _html_para_texto(html: str) -> str:
    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    html = re.sub(r"(?i)</t[dh]>", " | ", html)
    html = re.sub(r"(?i)<br\s*/?>|</p>|</tr>|</div>", "\n", html)
    texto = unescape(re.sub(r"<[^>]+>", " ", html))
    texto = texto.replace("\xa0", " ")
    return re.sub(r"[ \t]+", " ", texto)


# ---------------------------------------------------------------------------
# Rede (camada isolada para os testes conseguirem simular)
# ---------------------------------------------------------------------------

class Rede:
    def __init__(self) -> None:
        import requests  # import tardio: os testes não precisam de rede
        self._requests = requests
        self.sessao = requests.Session()
        self.ua_sec = os.environ.get("SEC_USER_AGENT", "").strip()
        self._ultima_sec = 0.0

    def _get(self, url: str, headers: dict[str, str] | None = None,
             tentativas: int = 3, timeout: int = 60):
        ultimo_erro: Exception | None = None
        for i in range(tentativas):
            try:
                if "sec.gov" in url:
                    if not self.ua_sec:
                        raise ErroRede("Defina SEC_USER_AGENT (a SEC exige nome + e-mail).")
                    espera = 0.15 - (time.time() - self._ultima_sec)
                    if espera > 0:
                        time.sleep(espera)
                    self._ultima_sec = time.time()
                    headers = {**(headers or {}), "User-Agent": self.ua_sec}
                resp = self.sessao.get(url, headers=headers, timeout=timeout)
                if resp.status_code == 404:
                    return None
                if resp.status_code in (429,) or resp.status_code >= 500:
                    raise ErroRede(f"HTTP {resp.status_code} em {url}")
                if resp.status_code >= 400:
                    raise ErroRede(f"HTTP {resp.status_code} em {url}")
                return resp
            except ErroRede as e:
                ultimo_erro = e
            except self._requests.RequestException as e:
                ultimo_erro = ErroRede(f"{type(e).__name__} em {url}: {e}")
            time.sleep(2 * (i + 1))
        raise ultimo_erro or ErroRede(f"Falha em {url}")

    def json(self, url: str, headers: dict[str, str] | None = None) -> Any:
        r = self._get(url, headers)
        return None if r is None else r.json()

    def texto(self, url: str, headers: dict[str, str] | None = None) -> str | None:
        r = self._get(url, headers)
        return None if r is None else r.text

    def bytes(self, url: str, headers: dict[str, str] | None = None) -> bytes | None:
        r = self._get(url, headers, timeout=180)
        return None if r is None else r.content


# ---------------------------------------------------------------------------
# Trimestres a partir de fatos com período (XBRL ou CVM)
# ---------------------------------------------------------------------------

def _dur(f: dict) -> int:
    return (_d(f["end"]) - _d(f["start"])).days


def trimestres_de_fatos(fatos: list[dict]) -> list[dict]:
    """
    Recebe fatos {start, end, val, filed, ref} e devolve trimestres
    {start, end, val, ref, derivado} ordenados por data de fim.
    O 4º trimestre (ou qualquer trimestre faltante no fim do ano) é derivado:
      anual - acumulado 9M   (preferido)
      anual - 3 trimestres   (alternativa)
    """
    por_periodo: dict[tuple[str, str], dict] = {}
    for f in fatos:
        if not f.get("start") or not f.get("end") or f.get("val") is None:
            continue
        k = (f["start"][:10], f["end"][:10])
        atual = por_periodo.get(k)
        if atual is None or str(f.get("filed", "")) >= str(atual.get("filed", "")):
            por_periodo[k] = {**f, "start": k[0], "end": k[1]}

    tri: dict[str, dict] = {}
    for f in por_periodo.values():
        if 80 <= _dur(f) <= 100:
            tri[f["end"]] = {"start": f["start"], "end": f["end"], "val": float(f["val"]),
                             "ref": f.get("ref"), "derivado": False}

    for f in por_periodo.values():
        if not (350 <= _dur(f) <= 380) or f["end"] in tri:
            continue
        inicio_q4 = None
        val = None
        nove = [x for x in por_periodo.values()
                if x["start"] == f["start"] and 260 <= _dur(x) <= 285 and x["end"] < f["end"]]
        if nove:
            n = max(nove, key=lambda x: x["end"])
            val = float(f["val"]) - float(n["val"])
            inicio_q4 = _d(n["end"]) + timedelta(days=1)
        else:
            dentro = sorted([x for x in tri.values()
                             if x["start"] >= f["start"] and x["end"] < f["end"]],
                            key=lambda x: x["end"])
            if len(dentro) == 3:
                val = float(f["val"]) - sum(x["val"] for x in dentro)
                inicio_q4 = _d(dentro[-1]["end"]) + timedelta(days=1)
        if val is not None:
            tri[f["end"]] = {"start": inicio_q4.isoformat(), "end": f["end"],
                             "val": round(val, 6), "ref": f.get("ref"), "derivado": True}

    return sorted(tri.values(), key=lambda x: x["end"])


def ultimos_4_consecutivos(tri: list[dict]) -> list[dict] | None:
    if len(tri) < 4:
        return None
    ult = tri[-4:]
    for a, b in zip(ult, ult[1:]):
        gap = (_d(b["start"]) - _d(a["end"])).days
        if not (0 <= gap <= 8):
            return None
    return ult


# ---------------------------------------------------------------------------
# Fontes oficiais + cotações
# ---------------------------------------------------------------------------

class Fontes:
    """Tudo que depende de rede. Os testes substituem esta classe."""

    SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"

    def __init__(self, rede: Rede | None = None) -> None:
        self.rede = rede or Rede()
        self._cik: dict[str, str] | None = None
        self._subs: dict[str, dict] = {}
        self._cvm_cache: dict[str, list[dict]] = {}
        self._precos: dict[str, list[tuple[date, float]]] = {}
        self._dolar: list[tuple[date, float]] | None = None

    # ------------------------- SEC -------------------------

    def cik(self, ticker: str) -> str | None:
        if self._cik is None:
            dados = self.rede.json(self.SEC_TICKERS) or {}
            self._cik = {v["ticker"].upper(): str(v["cik_str"]).zfill(10)
                         for v in dados.values()}
        return self._cik.get(ticker.upper())

    def _submissions(self, cik: str) -> dict:
        if cik not in self._subs:
            self._subs[cik] = self.rede.json(
                f"https://data.sec.gov/submissions/CIK{cik}.json") or {}
        return self._subs[cik]

    def _filings_sec(self, cik: str) -> list[dict]:
        rec = self._submissions(cik).get("filings", {}).get("recent", {})
        n = len(rec.get("accessionNumber", []))
        cik_int = str(int(cik))
        saida = []
        for i in range(n):
            accn = rec["accessionNumber"][i]
            nodash = accn.replace("-", "")
            prim = rec.get("primaryDocument", [""] * n)[i]
            saida.append({
                "form": rec["form"][i],
                "data": rec["filingDate"][i],
                "report": rec.get("reportDate", [""] * n)[i],
                "itens": rec.get("items", [""] * n)[i] or "",
                "accn": accn,
                "pasta": f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{nodash}/",
                "link": f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{nodash}/{prim}",
            })
        return saida

    def documentos_novos(self, ticker: str, dia: date) -> list[dict]:
        cfg = config_ativo(ticker)
        if cfg["mercado"] == "BR":
            return self._docs_cvm(ticker, cfg, dia)
        cik = self.cik(ticker)
        if not cik:
            return []
        itens_ok = ITENS_8K_GUIDANCE if cfg["regra"].startswith("guidance") else ITENS_8K_RESULTADO
        novos = []
        for f in self._filings_sec(cik):
            if f["data"] != dia.isoformat():
                continue
            form = f["form"]
            if form == "8-K":
                itens = {x.strip() for x in f["itens"].split(",")}
                if not itens & itens_ok:
                    continue
            elif form not in FORMS_RESULTADO_EUA:
                continue
            novos.append({"form": form, "data": f["data"], "link": f["link"]})
        return novos

    def _fatos_xbrl(self, cik: str, tag: str, unidade: str) -> list[dict] | None:
        dados = self.rede.json(
            f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{tag}.json")
        if not dados:
            return None
        fatos = dados.get("units", {}).get(unidade, [])
        cik_int = str(int(cik))
        for f in fatos:
            f["ref"] = (f"https://www.sec.gov/Archives/edgar/data/{cik_int}/"
                        f"{f['accn'].replace('-', '')}/")
        return fatos

    def _ttm_xbrl(self, cik: str, tags: list[str], unidade: str) -> tuple[list[dict] | None, str | None]:
        for tag in tags:
            fatos = self._fatos_xbrl(cik, tag, unidade)
            if not fatos:
                continue
            q = ultimos_4_consecutivos(trimestres_de_fatos(fatos))
            if q:
                return q, tag
        return None, None

    def _texto_exhibit_991(self, pasta: str) -> tuple[str | None, str | None]:
        idx = self.rede.json(pasta + "index.json")
        if not idx:
            return None, None
        nomes = [i["name"] for i in idx.get("directory", {}).get("item", [])
                 if i["name"].lower().endswith((".htm", ".html"))]
        candidatos = [n for n in nomes if re.search(r"ex[-_]?99|99[-_.]?1|exhibit99", n.lower())]
        for nome in candidatos or nomes:
            html = self.rede.texto(pasta + nome)
            if html:
                return _html_para_texto(html), pasta + nome
        return None, None

    # ------------------------- cálculo do TTM -------------------------

    def calcular_ttm(self, ticker: str) -> dict:
        cfg = config_ativo(ticker)
        regra = cfg["regra"]
        if regra == "cvm":
            return self._ttm_cvm(ticker, cfg)
        if regra == "pendente":
            return vazio("PENDENTE_CONFIG", f"{ticker}: ativo sem configuração (CNPJ/CIK).")
        cik = self.cik(ticker)
        if not cik:
            return vazio("PENDENTE_CIK", f"{ticker}: CIK não encontrado em company_tickers.json.")
        if regra == "xbrl":
            return self._ttm_padrao(ticker, cfg, cik)
        if regra == "xp_ajustado":
            return self._ttm_xp(cik)
        if regra == "guidance_receita":
            return self._guidance_receita(cik)
        if regra == "guidance_lpa":
            return self._guidance_lpa(cik, cfg)
        return vazio("PENDENTE_CONFIG", f"Regra desconhecida: {regra}")

    def _ttm_padrao(self, ticker: str, cfg: dict, cik: str) -> dict:
        tl = cfg.get("tags_lucro", TAGS_LUCRO_PADRAO)
        tp = cfg.get("tags_lpa", TAGS_LPA_PADRAO)
        ql, tag_l = self._ttm_xbrl(cik, tl, "USD")
        qp, tag_p = self._ttm_xbrl(cik, tp, "USD/shares")
        res = vazio("ATUALIZADO")
        res.update(lucro_moeda="USD", lpa_moeda="USD",
                   lpa_tipo=cfg.get("lpa_tipo", "diluido_gaap"))
        if ql:
            res["lucro_ttm"] = round(sum(x["val"] for x in ql), 2)
        else:
            res["pendencias"].append(f"PENDENTE_XBRL: sem 4 trimestres consecutivos para {tl}")
        if qp:
            res["lpa_ttm"] = round(sum(x["val"] for x in qp), 4)
        else:
            res["pendencias"].append(f"PENDENTE_XBRL: sem 4 trimestres consecutivos para {tp}")
        if ql and qp and [x["end"] for x in ql] != [x["end"] for x in qp]:
            res["pendencias"].append("Trimestres do lucro e do LPA não coincidem.")
        base = qp or ql
        if base:
            res["trimestres"] = [x["end"] for x in base]
            res["derivados"] = [x["end"] for x in base if x["derivado"]]
            res["link_oficial"] = base[-1]["ref"]
            res["fonte"] = f"SEC XBRL ({tag_l or '-'} / {tag_p or '-'})"
        if res["pendencias"]:
            res["status"] = "PENDENTE_XBRL"
        return res

    def _ttm_xp(self, cik: str) -> dict:
        """Lucro e LPA diluído AJUSTADOS dos 4 últimos releases (6-K, Exhibit 99.1)."""
        res = vazio("ATUALIZADO")
        res.update(lucro_moeda="BRL", lpa_moeda="BRL", lpa_tipo="diluido_ajustado_gerencial")
        trimestres: dict[str, dict] = {}
        for f in self._filings_sec(cik):
            if len(trimestres) >= 4:
                break
            if f["form"] != "6-K":
                continue
            texto, link = self._texto_exhibit_991(f["pasta"])
            if not texto or "Reports" not in texto or "Quarter" not in texto:
                continue
            q = _extrair_xp(texto)
            if q and q["fim"] not in trimestres:
                q["link"] = link
                trimestres[q["fim"]] = q
        if len(trimestres) < 4:
            res["status"] = "PENDENTE_SEC"
            res["pendencias"].append(
                f"XP: só {len(trimestres)} release(s) 6-K com lucro/LPA ajustado legíveis.")
            return res
        ult = sorted(trimestres.values(), key=lambda x: x["fim"])[-4:]
        res["lucro_ttm"] = round(sum(x["lucro"] for x in ult), 2)
        res["lpa_ttm"] = round(sum(x["lpa"] for x in ult), 4)
        res["trimestres"] = [x["fim"] for x in ult]
        res["link_oficial"] = ult[-1]["link"]
        res["fonte"] = "SEC 6-K Exhibit 99.1 (release de resultados, valores ajustados)"
        return res

    def _ultimo_8k_guidance(self, cik: str) -> dict | None:
        for f in self._filings_sec(cik):
            if f["form"] == "8-K" and {x.strip() for x in f["itens"].split(",")} & ITENS_8K_GUIDANCE:
                return f
        return None

    def _guidance_receita(self, cik: str) -> dict:
        """NVDA: só receita/guidance. Nunca cria LPA."""
        res = vazio("SO_GUIDANCE_RECEITA")
        res["lpa_tipo"] = "nao_aplicavel_sem_guidance_oficial_de_lpa"
        f = self._ultimo_8k_guidance(cik)
        texto, link = self._texto_exhibit_991(f["pasta"]) if f else (None, None)
        m = re.search(r"Revenue is expected to be \$\s?([\d.,]+)\s*(billion|million)", texto or "", re.I)
        if not m:
            res["status"] = "PENDENTE_SEC"
            res["pendencias"].append("Guidance de receita não encontrado no 8-K Ex.99.1.")
            return res
        mult = 1e9 if m.group(2).lower() == "billion" else 1e6
        res["receita_guidance"] = _num(m.group(1)) * mult
        res["link_oficial"] = link
        res["fonte"] = "SEC 8-K Exhibit 99.1 (Outlook)"
        return res

    def _guidance_lpa(self, cik: str, cfg: dict) -> dict:
        """TGT/PANW: usa o LPA de guidance SOMENTE se o número aparece no 8-K oficial."""
        res = vazio("GUIDANCE_LPA")
        res.update(lpa_moeda="USD", lpa_tipo=cfg.get("lpa_tipo", "guidance"))
        f = self._ultimo_8k_guidance(cik)
        texto, link = self._texto_exhibit_991(f["pasta"]) if f else (None, None)
        texto = texto or ""
        if _valor_no_contexto(texto, cfg["lpa_guidance"], cfg.get("contexto", [])):
            res["lpa_ttm"] = cfg["lpa_guidance"]
            res["link_oficial"] = link
            res["fonte"] = "SEC 8-K Exhibit 99.1 (guidance de LPA)"
        else:
            res["status"] = "PENDENTE_SEC"
            res["pendencias"].append(
                f"LPA guidance {cfg['lpa_guidance']} não encontrado no último 8-K Ex.99.1.")
        if "lpa_limpo" in cfg:
            if _valor_no_contexto(texto, cfg["lpa_limpo"], cfg.get("contexto", [])):
                res["lpa_limpo"] = cfg["lpa_limpo"]
            else:
                res["pendencias"].append(f"LPA limpo {cfg['lpa_limpo']} não encontrado no 8-K.")
        # Lucro TTM oficial (XBRL) para referência; nenhum dividendo é criado.
        ql, _ = self._ttm_xbrl(cik, TAGS_LUCRO_PADRAO, "USD")
        if ql:
            res["lucro_ttm"] = round(sum(x["val"] for x in ql), 2)
            res["lucro_moeda"] = "USD"
            res["trimestres"] = [x["end"] for x in ql]
            res["link_lucro"] = ql[-1]["ref"]
        return res

    # ------------------------- CVM -------------------------

    def _cvm_zip(self, tipo: str, ano: int, filtro_cnpj: str, sufixo: str) -> list[dict]:
        """Linhas de um CSV dentro do zip de dados abertos da CVM, filtradas por CNPJ."""
        chave = f"{tipo}-{ano}-{sufixo}-{filtro_cnpj}"
        if chave in self._cvm_cache:
            return self._cvm_cache[chave]
        tipo_low = tipo.lower()
        url = (f"https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/{tipo}/DADOS/"
               f"{tipo_low}_cia_aberta_{ano}.zip")
        zbytes = self._zip_bruto(url)
        linhas: list[dict] = []
        if zbytes:
            with zipfile.ZipFile(io.BytesIO(zbytes)) as z:
                alvo = f"{tipo_low}_cia_aberta_{sufixo}{ano}.csv"
                nome = next((n for n in z.namelist() if n.lower() == alvo.lower()), None)
                if nome:
                    with z.open(nome) as fh:
                        leitor = csv.DictReader(io.TextIOWrapper(fh, encoding="latin-1"), delimiter=";")
                        for row in leitor:
                            cnpj = row.get("CNPJ_CIA") or row.get("CNPJ_Companhia") or ""
                            if cnpj == filtro_cnpj:
                                linhas.append(row)
        self._cvm_cache[chave] = linhas
        return linhas

    def _zip_bruto(self, url: str) -> bytes | None:
        chave = "zip:" + url
        if chave not in self._cvm_cache:
            self._cvm_cache[chave] = self.rede.bytes(url)  # type: ignore[assignment]
        return self._cvm_cache[chave]  # type: ignore[return-value]

    def _docs_cvm(self, ticker: str, cfg: dict, dia: date) -> list[dict]:
        if not cfg.get("cnpj"):
            return []
        novos = []
        for row in self._cvm_zip("IPE", dia.year, cfg["cnpj"], ""):
            if (row.get("Data_Entrega") or "")[:10] != dia.isoformat():
                continue
            texto = " ".join(row.get(k, "") or "" for k in ("Categoria", "Tipo", "Especie", "Assunto"))
            if re.search(r"ITR|DFP|Release|Resultado", texto, re.I):
                novos.append({"form": f"IPE: {row.get('Categoria')} - {row.get('Assunto', '')[:60]}",
                              "data": dia.isoformat(), "link": row.get("Link_Download")})
        for tipo in ("ITR", "DFP"):
            for row in self._cvm_zip(tipo, dia.year, cfg["cnpj"], ""):
                if (row.get("DT_RECEB") or "")[:10] == dia.isoformat():
                    novos.append({"form": tipo, "data": dia.isoformat(), "link": row.get("LINK_DOC")})
        return novos

    def _ttm_cvm(self, ticker: str, cfg: dict) -> dict:
        res = vazio("ATUALIZADO")
        res.update(lucro_moeda="BRL", lpa_moeda="BRL", lpa_tipo=cfg.get("lpa_tipo"))
        cnpj = cfg.get("cnpj")
        if not cnpj:
            res["status"] = "PENDENTE_CONFIRMAR_CVM"
            res["pendencias"].append(f"{ticker}: CNPJ não configurado.")
            return res
        ano = hoje_brasilia().year
        fatos: list[dict] = []
        links: dict[str, str] = {}
        for a in (ano - 1, ano):
            for tipo in ("ITR", "DFP"):
                dre = self._cvm_zip(tipo, a, cnpj, "DRE_con_")
                fatos.extend(_fatos_cvm(dre))
                for row in self._cvm_zip(tipo, a, cnpj, ""):
                    if row.get("LINK_DOC"):
                        links[(row.get("DT_REFER") or "")[:10]] = row["LINK_DOC"]
        q = ultimos_4_consecutivos(trimestres_de_fatos(fatos))
        if not q:
            res["status"] = "PENDENTE_CONFIRMAR_CVM"
            res["pendencias"].append("ITR/DFP da CVM sem 4 trimestres consecutivos (conta 3.11.01).")
            return res
        lucro = sum(x["val"] for x in q)
        res["lucro_ttm"] = round(lucro, 2)
        res["lpa_ttm"] = round(lucro / cfg["acoes"], 4)
        res["trimestres"] = [x["end"] for x in q]
        res["derivados"] = [x["end"] for x in q if x["derivado"]]
        res["link_oficial"] = links.get(q[-1]["end"]) or q[-1].get("ref")
        res["fonte"] = (f"CVM dados abertos ITR/DFP, DRE consolidada 3.11.01 "
                        f"÷ {cfg['acoes'] / 1e9:.2f} bi ações")
        if not link_oficial_valido(res["link_oficial"]):
            res["status"] = "PENDENTE_CONFIRMAR_CVM"
            res["pendencias"].append("Link oficial do ITR/DFP não encontrado na CVM.")
        return res

    # ------------------------- cotações -------------------------

    def preco_fechamento(self, ticker: str, dia: date) -> dict:
        """Último fechamento ANTES de `dia` (dia anterior útil). Yahoo; fallback Brapi (BR)."""
        cfg = config_ativo(ticker)
        simbolo = cfg.get("yahoo", ticker)
        serie = self._serie_yahoo(simbolo, dia)
        fonte = f"Yahoo Finance ({simbolo})"
        if not serie and cfg["mercado"] == "BR":
            serie = self._serie_brapi(ticker)
            fonte = f"Brapi ({ticker})"
        anteriores = [(d, v) for d, v in serie if d < dia]
        if not anteriores:
            raise ErroRede(f"Sem cotação de fechamento para {ticker} antes de {dia}.")
        d, v = anteriores[-1]
        moeda = "BRL" if cfg["mercado"] == "BR" else "USD"
        return {"preco": round(v, 4), "preco_data": d.isoformat(), "preco_moeda": moeda,
                "preco_fonte": fonte}

    def _serie_yahoo(self, simbolo: str, dia: date) -> list[tuple[date, float]]:
        chave = f"y:{simbolo}"
        if chave not in self._precos:
            fim = int(datetime.combine(hoje_brasilia() + timedelta(days=1), datetime.min.time(),
                                       tzinfo=timezone.utc).timestamp())
            ini = fim - 45 * 86400
            url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{simbolo}"
                   f"?period1={ini}&period2={fim}&interval=1d")
            serie: list[tuple[date, float]] = []
            try:
                dados = self.rede.json(url, {"User-Agent": "Mozilla/5.0"})
                r = (dados or {}).get("chart", {}).get("result") or []
                if r:
                    off = r[0].get("meta", {}).get("gmtoffset", 0)
                    ts = r[0].get("timestamp") or []
                    closes = r[0]["indicators"]["quote"][0].get("close") or []
                    for t, c in zip(ts, closes):
                        if c is not None:
                            serie.append((datetime.fromtimestamp(t + off, timezone.utc).date(), float(c)))
            except ErroRede:
                serie = []
            self._precos[chave] = serie
        return self._precos[chave]

    def _serie_brapi(self, ticker: str) -> list[tuple[date, float]]:
        token = os.environ.get("BRAPI_TOKEN", "")
        url = f"https://brapi.dev/api/quote/{ticker}?range=1mo&interval=1d"
        if token:
            url += f"&token={token}"
        dados = self.rede.json(url) or {}
        serie = []
        for r in dados.get("results", []):
            for p in r.get("historicalDataPrice", []):
                if p.get("close") is not None:
                    serie.append((datetime.fromtimestamp(p["date"], TZ_BR).date(), float(p["close"])))
        return sorted(serie)

    def dolar(self, dia: date) -> dict | None:
        """Dólar comercial (venda) do último dia útil antes de `dia`. BCB SGS 1; fallback Brapi."""
        if self._dolar is None:
            ini = (hoje_brasilia() - timedelta(days=45)).strftime("%d/%m/%Y")
            fim = hoje_brasilia().strftime("%d/%m/%Y")
            url = ("https://api.bcb.gov.br/dados/serie/bcdata.sgs.1/dados"
                   f"?formato=json&dataInicial={ini}&dataFinal={fim}")
            serie: list[tuple[date, float]] = []
            try:
                for p in self.rede.json(url) or []:
                    serie.append((datetime.strptime(p["data"], "%d/%m/%Y").date(), _num_br(p["valor"])
                                  if "," in p["valor"] else float(p["valor"])))
            except ErroRede:
                serie = []
            self._dolar = sorted(serie)
        anteriores = [(d, v) for d, v in self._dolar if d < dia]
        if anteriores:
            d, v = anteriores[-1]
            return {"usd_brl": v, "usd_brl_data": d.isoformat(), "usd_brl_fonte": "BCB SGS 1"}
        token = os.environ.get("BRAPI_TOKEN", "")
        url = "https://brapi.dev/api/v2/currency?currency=USD-BRL" + (f"&token={token}" if token else "")
        dados = self.rede.json(url) or {}
        moedas = dados.get("currency") or []
        if moedas:
            return {"usd_brl": float(moedas[0]["bidPrice"]), "usd_brl_data": None,
                    "usd_brl_fonte": "Brapi (cotação atual)"}
        return None


# ---------------------------------------------------------------------------
# Helpers de extração
# ---------------------------------------------------------------------------

_ORD = {"first": 1, "second": 2, "third": 3, "fourth": 4}
_FIM_TRI = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}


def _extrair_xp(texto: str) -> dict | None:
    """Extrai trimestre, lucro ajustado (R$ mi) e LPA diluído ajustado (R$) do release da XP."""
    m = re.search(r"results for the (first|second|third|fourth) quarter of (20\d\d)", texto, re.I)
    if not m:
        m2 = re.search(r"\b([1-4])Q(\d\d)\b", texto)
        if not m2:
            return None
        tri, ano = int(m2.group(1)), 2000 + int(m2.group(2))
    else:
        tri, ano = _ORD[m.group(1).lower()], int(m.group(2))
    lpa = re.search(r"Adjusted Diluted EPS was R\$\s?([\d.]+)", texto)
    if not lpa:
        lpa = re.search(r"(?:Adjusted )?Diluted EPS \(in R\$\)\s*\|?\s*([\d.]+)", texto)
    lucro = re.search(r"Adjusted Net Income\s*\|?\s*([\d,]{3,})\s*\|", texto)
    if not lucro:
        lucro = re.search(r"\bNet Income\s*\|?\s*([\d,]{3,})\s*\|", texto)
    if not (lpa and lucro):
        return None
    return {"fim": f"{ano}-{_FIM_TRI[tri]}",
            "lucro": _num(lucro.group(1)) * 1e6,   # tabela em R$ milhões
            "lpa": float(lpa.group(1))}


def _valor_no_contexto(texto: str, valor: float, termos: list[str], raio: int = 400) -> bool:
    alvo = f"{valor:.2f}"
    for m in re.finditer(re.escape(alvo), texto):
        trecho = texto[max(0, m.start() - raio): m.end() + raio]
        if all(t.lower() in trecho.lower() for t in termos):
            return True
    return False


def _fatos_cvm(linhas: list[dict]) -> list[dict]:
    """Converte linhas da DRE da CVM (conta 3.11.01) em fatos {start,end,val,filed}."""
    melhores: dict[tuple, dict] = {}
    for r in linhas:
        if (r.get("ORDEM_EXERC") or "").upper() not in ("ÚLTIMO", "ULTIMO"):
            continue
        conta = r.get("CD_CONTA", "")
        desc = (r.get("DS_CONTA") or "").lower()
        if conta != "3.11.01" and "atribuído a sócios da empresa controladora" not in desc:
            continue
        if conta.count(".") > 2:
            continue
        k = (r.get("DT_INI_EXERC"), r.get("DT_FIM_EXERC"))
        v = int(r.get("VERSAO") or 0)
        if k not in melhores or v >= int(melhores[k].get("VERSAO") or 0):
            melhores[k] = r
    fatos = []
    for (ini, fim), r in melhores.items():
        escala = 1000.0 if (r.get("ESCALA_MOEDA") or "").upper() == "MIL" else 1.0
        fatos.append({"start": ini, "end": fim, "val": float(r["VL_CONTA"]) * escala,
                      "filed": r.get("VERSAO", "0")})
    return fatos


# ---------------------------------------------------------------------------
# Registro de saída
# ---------------------------------------------------------------------------

def vazio(status: str, pendencia: str | None = None) -> dict:
    return {"lucro_ttm": None, "lucro_moeda": None, "lpa_ttm": None, "lpa_moeda": None,
            "lpa_tipo": None, "trimestres": [], "derivados": [], "fonte": None,
            "link_oficial": None, "status": status,
            "pendencias": [pendencia] if pendencia else []}


def config_ativo(ticker: str) -> dict:
    if ticker in ATIVOS:
        return ATIVOS[ticker]
    if ticker[-1:].isdigit():
        return {"mercado": "BR", "regra": "pendente", "yahoo": f"{ticker}.SA"}
    return {"mercado": "EUA", "regra": "xbrl"}


CAMPOS_TTM = ("lucro_ttm", "lucro_moeda", "lpa_ttm", "lpa_moeda", "lpa_tipo", "lpa_limpo",
              "receita_guidance", "trimestres", "derivados", "fonte", "link_oficial",
              "link_lucro", "status", "pendencias")

CAMPOS_NUMERICOS_OFICIAIS = ("lucro_ttm", "lpa_ttm", "lpa_limpo", "receita_guidance")


def validar_registro(reg: dict) -> dict:
    """Nenhum número oficial sem link SEC/CVM: se o link faltar, zera o campo e marca pendente."""
    descartados = []
    link_principal_ok = link_oficial_valido(reg.get("link_oficial"))
    for c in CAMPOS_NUMERICOS_OFICIAIS:
        if reg.get(c) is None:
            continue
        link = reg.get("link_lucro") if c == "lucro_ttm" and reg.get("link_lucro") else reg.get("link_oficial")
        if not link_oficial_valido(link):
            reg[c] = None
            descartados.append(c)
    if "lpa_ttm" in descartados:
        reg["pl"] = None
    if descartados:
        reg["status"] = "PENDENTE_SEM_LINK_OFICIAL"
        reg["pendencias"] = list(reg.get("pendencias") or []) + [
            f"Descartado por falta de link oficial SEC/CVM: {', '.join(descartados)}"]
    if not link_principal_ok and reg.get("link_oficial"):
        reg["link_oficial"] = None
    return reg


def calcular_pl(reg: dict, usd_brl: float | None) -> tuple[float | None, str | None]:
    lpa, preco = reg.get("lpa_ttm"), reg.get("preco")
    if lpa is None or preco is None:
        return None, None
    if reg.get("lpa_moeda") and reg.get("preco_moeda") and reg["lpa_moeda"] != reg["preco_moeda"]:
        if not usd_brl:
            return None, "Sem dólar para converter moedas."
        if reg["preco_moeda"] == "USD" and reg["lpa_moeda"] == "BRL":
            preco = preco * usd_brl
        elif reg["preco_moeda"] == "BRL" and reg["lpa_moeda"] == "USD":
            preco = preco / usd_brl
    if lpa <= 0:
        return None, f"P/L negativo (n/s): LPA {lpa}"
    return round(preco / lpa, 2), None


def _precisa_recalcular(prev: dict | None, docs: list[dict]) -> bool:
    if docs or prev is None:
        return True
    return str(prev.get("status", "")).startswith("PENDENTE")


def _marcar_lag(ttm: dict, docs: list[dict]) -> None:
    """Documento novo, mas o trimestre ainda não está no XBRL/CVM -> pendente."""
    if not docs or not ttm.get("trimestres"):
        return
    ultimo = _d(ttm["trimestres"][-1])
    for doc in docs:
        if ultimo < _d(doc["data"]) - timedelta(days=JANELA_TRIMESTRE_DIAS):
            prefixo = "PENDENTE_CONFIRMAR_CVM" if "IPE" in doc["form"] or doc["form"] in ("ITR", "DFP") \
                else "PENDENTE_XBRL"
            ttm["status"] = prefixo
            ttm["pendencias"].append(
                f"{prefixo}: {doc['form']} de {doc['data']} ainda não refletido nos dados "
                f"estruturados; TTM vai até {ultimo.isoformat()}.")
            return


# ---------------------------------------------------------------------------
# Execução principal
# ---------------------------------------------------------------------------

def executar(base: Path, hoje: date, fontes: Any) -> int:
    arq_tickers = base / "guidance_tickers.json"
    arq_last = base / "last_run.json"
    arq_saida = base / "ttm_diario.json"

    tickers = [t.strip().upper() for t in ler_json(arq_tickers, []) if str(t).strip()]
    if not tickers:
        print("ERRO: guidance_tickers.json vazio ou ausente.", file=sys.stderr)
        return 1

    last_run = ler_last_run(arq_last, hoje)
    dias = dias_faltantes(last_run, hoje)
    if not dias:
        print(f"Nada a fazer: last_run = {last_run.isoformat()} (hoje = {hoje.isoformat()}).")
        return 0

    print(f"Catch-up: last_run={last_run.isoformat()} -> processando "
          f"{', '.join(d.isoformat() for d in dias)} ({len(dias)} dia(s)) para {len(tickers)} tickers.")

    historico: list[dict] = ler_json(arq_saida, [])
    ultimo: dict[str, dict] = {}
    for r in sorted(historico, key=lambda x: x["data"]):
        ultimo[r["ticker"]] = r

    novos: list[dict] = []
    erros: list[str] = []
    gerado_em = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for dia in dias:
        try:
            usd = fontes.dolar(dia) or {}
        except ErroRede as e:
            erros.append(f"{dia} dólar: {e}")
            usd = {}
        for t in tickers:
            try:
                docs = fontes.documentos_novos(t, dia)
                prev = ultimo.get(t)
                if _precisa_recalcular(prev, docs):
                    ttm = fontes.calcular_ttm(t)
                    _marcar_lag(ttm, docs)
                    if prev and ttm["status"].startswith("PENDENTE") and ttm.get("lucro_ttm") is None \
                            and prev.get("lucro_ttm") is not None:
                        # Mantém o último TTM OFICIAL, sinalizando a pendência.
                        manter = {c: prev.get(c) for c in CAMPOS_TTM if c not in ("status", "pendencias")}
                        ttm = {**manter, "status": ttm["status"], "pendencias": ttm["pendencias"]}
                    origem = "RECALCULADO" if docs or prev is None else "RETENTATIVA_PENDENTE"
                else:
                    ttm = {c: prev.get(c) for c in CAMPOS_TTM}
                    ttm["status"] = "SEM_NOVO_DOCUMENTO"
                    ttm["pendencias"] = []
                    origem = "MANTIDO_TTM_ANTERIOR"

                reg: dict[str, Any] = {"data": dia.isoformat(), "ticker": t,
                                       "mercado": config_ativo(t)["mercado"]}
                reg.update({c: ttm.get(c) for c in CAMPOS_TTM})
                reg["origem_ttm"] = origem
                reg["documentos_novos"] = docs
                reg.update(fontes.preco_fechamento(t, dia))
                reg.update({k: usd.get(k) for k in ("usd_brl", "usd_brl_data", "usd_brl_fonte")})
                pl, obs = calcular_pl(reg, usd.get("usd_brl"))
                reg["pl"] = pl
                if obs:
                    reg["pendencias"] = list(reg.get("pendencias") or []) + [obs]
                reg["dias_catchup"] = len(dias)
                reg["gerado_em"] = gerado_em
                reg = validar_registro(reg)
                novos.append(reg)
                ultimo[t] = reg
            except ErroRede as e:
                erros.append(f"{dia} {t}: {e}")

    if erros:
        print("FALHOU — nada foi gravado; last_run mantido em "
              f"{last_run.isoformat()} para catch-up no próximo dia:", file=sys.stderr)
        for e in erros:
            print("  - " + e, file=sys.stderr)
        return 1

    chave = {(r["data"], r["ticker"]): r for r in historico}
    for r in novos:
        chave[(r["data"], r["ticker"])] = r
    saida = sorted(chave.values(), key=lambda r: (r["data"], r["ticker"]))
    gravar_json_atomico(arq_saida, saida)
    gravar_json_atomico(arq_last, {"last_run": hoje.isoformat(), "atualizado_em": gerado_em,
                                   "dias_processados": [d.isoformat() for d in dias]})

    for r in novos:
        if r["data"] == hoje.isoformat():
            print(f"{r['ticker']:6} lucro={r['lucro_ttm']} lpa={r['lpa_ttm']} preco={r['preco']} "
                  f"pl={r['pl']} status={r['status']} origem={r['origem_ttm']}")
    print(f"OK: {len(novos)} registros gravados; last_run = {hoje.isoformat()}.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="FINTAI - TTM diário com catch-up")
    ap.add_argument("--hoje", help="Data de hoje (YYYY-MM-DD). Padrão: hoje em Brasília.")
    ap.add_argument("--dir", default=str(Path(__file__).resolve().parent),
                    help="Pasta com guidance_tickers.json (padrão: utils/).")
    args = ap.parse_args()
    if args.hoje:
        os.environ["FINTAI_HOJE"] = args.hoje
    hoje = hoje_brasilia()
    try:
        fontes = Fontes()
    except ImportError:
        print("ERRO: instale requests (pip install requests).", file=sys.stderr)
        return 1
    return executar(Path(args.dir), hoje, fontes)


if __name__ == "__main__":
    sys.exit(main())
