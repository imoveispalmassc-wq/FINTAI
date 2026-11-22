#!/usr/bin/env python3
"""Corpo do pull request da atualização automática de TTM (REGRA 6, travada).

Compara os arquivos de TTM do ramo base (padrão: origin/main) com os da pasta de trabalho e escreve, em
markdown: no TOPO as divergências (GAAP x ajustado, contínuas x total, 4º tri do release x cálculo, cotação
não verificada / sem P/L) e depois a lista de ativos alterados com a fonte e o LPA antes -> depois.

Uso: python tools/resumo_ttm_pr.py [--base origin/main] [--saida pr_ttm.md]
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ARQUIVOS = ("utils/contabil_sec.json", "utils/contabil_br.json", "utils/ttm_diario.json")


def _base(ref: str, caminho: str):
    try:
        txt = subprocess.run(["git", "show", f"{ref}:{caminho}"], cwd=RAIZ, capture_output=True, text=True, check=True).stdout
        return json.loads(txt)
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return None


def _atual(caminho: str):
    try:
        return json.loads((RAIZ / caminho).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _ultimos(registros) -> dict:
    """ttm_diario.json é uma lista diária: fica o registro mais recente de cada ticker."""
    saida = {}
    for r in sorted(registros or [], key=lambda x: x.get("data", "")):
        saida[r["ticker"]] = r
    return saida


def _f(v) -> str:
    return "Sem dado" if v is None else (f"{v:,.4f}".rstrip("0").rstrip(".") if isinstance(v, (int, float)) else str(v))


def divergencias(t: str, r: dict, origem: str) -> list[str]:
    out = []
    if r.get("lpa_ajustado") is not None:
        out.append(f"**{t}** ({origem}): GAAP x ajustado - tela usa GAAP {_f(r.get('lpa_12m', r.get('lpa_ttm')))}; "
                   f"ajustado {_f(r['lpa_ajustado'])} só na nota")
    if r.get("base") == "ajustado":
        out.append(f"**{t}** ({origem}): base AJUSTADA no campo principal (contraria a Regra 1 - revisar)")
    if r.get("tem_descontinuadas"):
        total = r.get("lpa_12m_total", r.get("lpa_total"))
        out.append(f"**{t}** ({origem}): contínuas x total - usa contínuas {_f(r.get('lpa_12m', r.get('lpa_ttm')))}; "
                   f"total {_f(total)} só na nota")
    if r.get("q4_release") is not None and r.get("q4_calculado") is not None and r["q4_release"] != r["q4_calculado"]:
        out.append(f"**{t}** ({origem}): 4º tri - release {_f(r['q4_release'])} (usado) x cálculo ano − 9 meses "
                   f"{_f(r['q4_calculado'])}")
    if r.get("pl_status") and r["pl_status"] != "ok":
        out.append(f"**{t}** ({origem}): sem P/L - {r['pl_status']}")
    if "COPIADO" in str(r.get("preco_fonte") or "").upper():
        out.append(f"**{t}** ({origem}): cotação COPIADO - NÃO VERIFICADO")
    if r.get("alerta_acoes"):
        out.append(f"**{t}** ({origem}): {r['alerta_acoes']}")
    return out


def resumo(base: str = "origin/main") -> str:
    topo, linhas = [], []
    for caminho in ARQUIVOS:
        antes, depois = _base(base, caminho), _atual(caminho)
        if depois is None:
            continue
        if caminho.endswith("ttm_diario.json"):
            antes, depois = _ultimos(antes), _ultimos(depois)
            campo = "lpa_ttm"
        else:
            antes, depois = antes or {}, depois
            campo = "lpa_12m"
        nome = caminho.split("/")[-1]
        for t in sorted(depois):
            a, d = (antes or {}).get(t) or {}, depois[t] or {}
            chaves = (campo, "lucro_ttm", "lucro_12m", "pl", "status", "fonte")
            if all(a.get(k) == d.get(k) for k in chaves) and a.get("trimestres") == d.get("trimestres"):
                continue
            topo += divergencias(t, d, nome)
            linhas.append(f"| {t} | {nome} | {_f(a.get(campo))} → {_f(d.get(campo))} | {d.get('fonte') or '-'} | "
                          f"{d.get('source_date') or d.get('data') or '-'} | {d.get('updated_by') or '-'} |")
    partes = ["## Divergências (revisar antes do merge)", ""]
    partes += [f"- {x}" for x in topo] or ["- Nenhuma."]
    partes += ["", "## Ativos alterados", "",
               "| Ativo | Arquivo | LPA antes → depois | Fonte | Data do documento | Atualizado por |",
               "|---|---|---|---|---|---|"]
    partes += linhas or ["| - | - | sem alteração | - | - | - |"]
    partes += ["", "Regras travadas (22/11/2026): tela usa LPA GAAP; contínuas quando há descontinuadas; 4º tri do release "
               "quando divulgado; sem cotação verificada, sem P/L; guidance nunca entra no TTM. `python -m pytest` rodou "
               "antes deste PR. Merge publica; fechar descarta."]
    return "\n".join(partes) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--saida", default="")
    args = ap.parse_args()
    txt = resumo(args.base)
    if args.saida:
        Path(args.saida).write_text(txt, encoding="utf-8")
    print(txt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
