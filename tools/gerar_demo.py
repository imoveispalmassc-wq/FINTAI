"""Gera docs/index.html: a tela atual do app (tela/detalhe.*) com dados de EXEMPLO da Micron.

A página publicada no GitHub Pages não busca cotações. Os números abaixo são de exemplo,
fixos em 13/11/2026; as regras (zonas, decisão, Lynch, Simons) são as mesmas do app.

Uso:  python tools/gerar_demo.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from tela.dados import faixas_por_periodo, modo_simons, series_do_grafico  # noqa: E402
from calculos import graham_duas_versoes  # noqa: E402
from utils.lynch import crescimento_anual, peg, regra_prejuizo, veredito  # noqa: E402
from utils.percentile import percentil_na_faixa, zonas  # noqa: E402
from utils.seo import tags_og  # noqa: E402
from utils.signals import decidir_estado  # noqa: E402

# página publicada de verdade no GitHub Pages (padrão de URL de Pages a partir de /docs em main) -
# usada no og:url; a imagem (og:image) é o logo real do projeto, ver utils/seo.py
URL_PAGINA = "https://imoveispalmassc-wq.github.io/FINTAI/"

FIM = pd.Timestamp("2026-11-13")
PRECO, FECH_ANTERIOR = 778.31, 798.43            # -2,52% no dia
MIN52, MAX52, MIN30, MAX30 = 192.59, 1255.00, 650.00, 990.00
MM200, LPA, DIVIDENDO = 765.61, 74.33, 0.57


# ------------------------------------------------------------ séries de exemplo
def _caminho(ancoras: list[tuple[str, float]], ruido: float, semente: int) -> pd.Series:
    """Fechamentos diários passando exatamente pelas âncoras (data, preço)."""
    idx = pd.bdate_range(ancoras[0][0], ancoras[-1][0])
    datas = pd.to_datetime([a for a, _ in ancoras])
    pos = idx.get_indexer(datas, method="nearest")
    logs = np.interp(np.arange(len(idx)), pos, np.log([p for _, p in ancoras]))
    rng, w, desvio = np.random.default_rng(semente), 0.0, np.zeros(len(idx))
    for i in range(len(idx)):
        w = w * 0.85 + rng.normal(0, ruido)
        desvio[i] = w
    # o ruído some nas âncoras, para os valores travados ficarem exatos
    fase = np.zeros(len(idx))
    for a, b in zip(pos[:-1], pos[1:]):
        if b > a:
            fase[a:b + 1] = np.sin(np.pi * (np.arange(a, b + 1) - a) / (b - a))
    return pd.Series(np.exp(logs + desvio * fase), idx)


def historico() -> pd.DataFrame:
    ancoras = [
        ("1984-06-01", 1.5), ("1996-01-02", 8.0), ("2000-07-14", 95.0), ("2002-10-01", 9.0),
        ("2008-11-20", 2.5), ("2014-12-01", 34.0), ("2016-02-01", 11.0), ("2018-05-29", 60.0),
        ("2021-11-12", 75.54), ("2022-01-05", 95.0), ("2022-12-28", 68.38), ("2023-11-13", 74.05),
        ("2024-06-18", 150.0), ("2025-04-07", 68.0), ("2025-11-13", 236.95), ("2025-12-22", 199.50),
        ("2026-04-30", 560.0), ("2026-08-04", 1180.32), ("2026-10-14", 905.0), ("2026-10-21", 985.0),
        ("2026-11-03", 660.0), ("2026-11-10", 800.0), ("2026-11-11", 812.0),
        ("2026-11-12", FECH_ANTERIOR), ("2026-11-13", PRECO),
    ]
    c = _caminho(ancoras, 0.012, 7)
    ano, mes = c.index > FIM - pd.DateOffset(years=1), c.index > FIM - pd.Timedelta(days=30)
    c[ano] = c[ano].clip(199.5, 1180.32)
    c[mes] = c[mes].clip(655.0, 985.0)
    for data, valor in ancoras:
        c[pd.Timestamp(data)] = valor
    rng = np.random.default_rng(3)
    h = pd.DataFrame({"Open": c.shift(1).fillna(c), "High": c * 1.006, "Low": c * 0.994, "Close": c,
                      "Adj Close": c, "Volume": rng.integers(8e6, 4e7, len(c)).astype(float),
                      "Dividends": 0.0, "Stock Splits": 0.0})
    h.loc[mes, "High"] = h.loc[mes, "High"].clip(upper=MAX30)
    h.loc[mes, "Low"] = h.loc[mes, "Low"].clip(lower=MIN30)
    # extremos travados: mínima e máxima de 52 semanas e de 30 dias
    h.loc[pd.Timestamp("2025-12-22"), "Low"] = MIN52
    h.loc[pd.Timestamp("2026-08-04"), "High"] = MAX52
    h.loc[pd.Timestamp("2026-10-21"), "High"] = MAX30
    h.loc[pd.Timestamp("2026-11-03"), "Low"] = MIN30
    h["High"] = h[["High", "Open", "Close"]].max(axis=1)
    h["Low"] = h[["Low", "Open", "Close"]].min(axis=1)
    return h


def _intraday(pontos: list[tuple[int, float]], n: int, passo: str, semente: int, ruido: float) -> pd.DataFrame:
    idx = pd.date_range(end=pd.Timestamp("2026-11-13 16:00"), periods=n, freq=passo)
    logs = np.interp(np.arange(n), [i for i, _ in pontos], np.log([p for _, p in pontos]))
    rng, w, c = np.random.default_rng(semente), 0.0, np.zeros(n)
    for i in range(n):
        w = w * 0.8 + rng.normal(0, ruido)
        c[i] = np.exp(logs[i] + w * np.sin(np.pi * i / (n - 1)))
    c[-1] = PRECO
    return pd.DataFrame({"Open": np.r_[c[0], c[:-1]], "High": c * 1.001, "Low": c * 0.999, "Close": c,
                         "Volume": rng.integers(2e5, 2e6, n).astype(float)}, index=idx)


# ------------------------------------------------------------ pacote de exemplo
def pacote() -> dict:
    hist = historico()
    intraday = {
        "hoje": _intraday([(0, 795.0), (14, 786.0), (40, 771.2), (62, 783.0), (78, PRECO)], 79, "5min", 11, 0.0012),
        "1s": _intraday([(0, 742.0), (20, 801.0), (38, 812.0), (51, FECH_ANTERIOR), (64, PRECO)], 65, "30min", 12, 0.004),
        "1m": _intraday([(0, 905.0), (35, 985.0), (98, 660.0), (133, 800.0), (153, PRECO)], 154, "60min", 13, 0.006),
    }
    series = series_do_grafico(hist, intraday)
    faixa = zonas(MIN52, MAX52)
    direcao = "Alta" if PRECO > MM200 else "Baixa"

    # teste histórico das zonas (exemplo): nenhum dos dois sinais se validou
    lado = lambda vezes, retorno, acerto: {"vezes": vezes, "retorno": retorno, "acerto": acerto}
    bt5 = {"anos": 5.0, "insuficiente": False, "oportunidade": lado(74, 122, 87), "cara": lado(78, 157, 32),
           "referencia": {"retorno": 137, "subiu": 77}, "compraValidada": False, "vendaValidada": False}
    btmax = {"anos": 9.0, "insuficiente": False, "oportunidade": lado(121, 108, 90), "cara": lado(164, 76, 43),
             "referencia": {"retorno": 92, "subiu": 74}, "compraValidada": True, "vendaValidada": False}

    estado = decidir_estado(percentil_na_faixa(PRECO, MIN52, MAX52), MIN52, MAX52,
                            compra_validada=bt5["compraValidada"], simbolo="US$",
                            preco=PRECO, tendencia=direcao)

    pl = PRECO / LPA
    # Lucro e receita por ano fiscal: sem os valores reais, ficam vazios ("Sem dado").
    # Preencha aqui quando tiver os números: [(2024, lpa), (2025, lpa), (2026, lpa)]
    lpa_anos: list[tuple[int, float]] = [(2024, 0.70), (2025, 7.65), (2026, 75.38)]   # do app real, 15/11/2026
    receitas: list[tuple[int, float]] = []
    regra = regra_prejuizo([v for _, v in lpa_anos])
    graham = graham_duas_versoes(LPA, regra["media"] if regra["status"] in ("ok", "excluido") else None, 122.35)
    lucro_pass, anos_lucro = crescimento_anual(lpa_anos)
    rec_pass, anos_rec = crescimento_anual(receitas)
    # Estimativas do Yahoo: valores de EXEMPLO, marcados na tela, até entrarem os reais
    # Só valores com fonte. LPA estimado do ano fiscal 2027: consenso do Yahoo visto no app em 15/11/2026.
    # Crescimento de longo prazo e receita do próximo ano: sem o valor real, ficam vazios.
    lucro_longo, receita_prox, lpa_este_ano = None, None, 176.50
    peg_futuro = peg(pl, lucro_longo)
    sem_peg = veredito(peg_futuro, receita_prox, regra["status"], lucro_longo)
    if sem_peg["cor"] == "cinza":
        sem_peg = {**sem_peg, "titulo": "Sem PEG - Yahoo não tem o crescimento de longo prazo deste ativo"}
    arred = lambda v, casas=2: None if v is None else round(v, casas)

    comp = lambda nome, curto, artigo, moeda, v: {"nome": nome, "curto": curto, "artigo": artigo, "moeda": moeda, "v": v}
    um_ano = series["1a"]
    return {
        "ticker": "MU", "nome": "Micron", "razao": "Micron Technology, Inc.", "bolsa": "NASDAQ",
        "moeda": "US$", "codMoeda": "USD", "fonte": "Yahoo Finance",
        "data": "13/11/2026", "atualizado": "13/11/2026 às 19:13",
        "preco": PRECO, "varDia": -2.52, "after": {"preco": 751.14, "variacao": -3.49, "hora": "19:13"},
        "min52": MIN52, "max52": MAX52, "min30": MIN30, "max30": MAX30,
        "mm200": MM200, "tendencia": direcao, "forca": 42,
        "lpaAnos": [{"ano": a, "lpa": v} for a, v in lpa_anos],
        "regra": {"status": regra["status"], "media": arred(regra["media"], 4), "mensagem": regra["mensagem"]},
        # o que é exemplo meu, e não dado passado pelo dono do app, aparece marcado na tela
        "exemplos": {"simons": True, "backtestMax": True},
        "lynch": {
            "passado": {"lucro": arred(lucro_pass), "anosLucro": anos_lucro,
                        "receita": arred(rec_pass), "anosReceita": anos_rec},
            "futuro": {"lucroLongo": lucro_longo, "receitaProx": receita_prox, "lpaEsteAno": lpa_este_ano,
                       "lpaBaixa": None, "lpaAlta": None, "analistas": None, "analistasReceita": None},
            "pegFuturo": arred(peg_futuro, 4), "pegYahoo": None,
            "lucroTrimestre": None, "receitaTrimestre": None,
            "veredito": sem_peg,
        },
        "simons": modo_simons(hist),
        "pl": round(pl, 4), "plMedio12": 26.00, "plMetodo": "trimestral",
        "lpa": LPA, "lpaAgora": LPA, "lpa12Atras": 8.29, "baseLpa": "últimos 4 trimestres",
        "dividendo": DIVIDENDO, "dividendo12Atras": 0.46, "dyMedio12": 0.0949, "dividendos5Anos": 2.50,
        "acoes": 1.13e9, "vpa": 122.35, "plHistorico": 22.34, "plHistAnos": 5.0,
        "graham": arred(graham["usado"], 4), "grahamAtual": arred(graham["atual"], 4),
        "grahamMedia": arred(graham["media"], 4), "grahamBase": graham["base"], "grahamAviso": graham["aviso"],
        "lpaMedio3a": arred(regra["media"], 4), "justoPL": 1660.53, "bazin": 8.33, "divMedio5": 0.50,
        "retorno": {"periodos": ["1 ano", "3 anos", "5 anos"], "total": [228.8, 951, 931],
                    "preco": [228.47, 950.7, 930.3]},
        "preco1AnoAtras": um_ano["c"][0], "data1AnoAtras": "13/11/2025",
        # issue #47, item 16: ticker dos EUA só mostra comparadores em US$ (nunca Ibovespa/CDI/
        # Selic/IPCA/Poupança sem conversão) - "rendaFixa" fica vazio pra MU (sem fonte Fed/T-Bill).
        "comparadores": {
            "nasdaq": comp("Nasdaq", "Nasdaq", "do índice", "US$", [None, None, None]),   # sem o valor real ainda
            "sp500": comp("S&P 500", "S&P", "do índice", "US$", [14, 78, 73]),
        },
        "comparadorPadrao": "nasdaq",
        "rendaFixa": {},
        "backtest": {"5a": bt5, "max": btmax},
        "seloFundamentos": None,
        "decisao": {"codigo": estado.codigo, "rotulo": estado.rotulo, "texto": estado.texto,
                    "zona": estado.zona, "validado": estado.validado, "alerta": estado.alerta},
        "zOport": round(faixa.oportunidade_ate, 4), "zCara": round(faixa.cara_acima, 4),
        "faixas": faixas_por_periodo(hist, PRECO, compra_validada_52=bt5["compraValidada"], quebrou=False,
                                     motivo="", simbolo="US$", tendencia=direcao),
        "series": series,
    }


# ------------------------------------------------------------ página
def pagina(dados: dict) -> str:
    tela = RAIZ / "tela"
    css = (tela / "detalhe.css").read_text(encoding="utf-8").replace(":host {", ":root {", 1)
    # Tela dividida em 2 componentes no app real (27/11/2026, ver app.py) - a página estática
    # (fora do Streamlit, sem shadow DOM) precisa montar as 2 metades em containers PRÓPRIOS (não
    # direto no `document`): as 2 metades têm elementos com o MESMO id (ex. o modal "Ver como
    # calculamos", #fundo/#folha-t/#folha-c/#folha-x, duplicado em cada metade) - no Streamlit cada
    # componente tem seu próprio shadow root, então os ids nunca colidem; numa página só, sem shadow
    # DOM, colidiriam se as duas fossem montadas contra `document`. Cada metade também fica dentro
    # de uma IIFE própria (função isolada) porque as duas declaram os MESMOS nomes no nível do
    # arquivo (`tem`, `f`, `sinal`, `montar`, etc.) - sem isso, o 2º `<script>` daria erro de
    # "Identifier already declared" ao tentar redeclarar o que o 1º já declarou no mesmo escopo.
    js_a = (tela / "detalhe.js").read_text(encoding="utf-8")
    js_a = js_a[:js_a.index("export default function")]
    js_b = (tela / "detalhe_fundo.js").read_text(encoding="utf-8")
    js_b = js_b[:js_b.index("export default function")]
    assert ":root {" in css and "function montar(" in js_a and "function montar(" in js_b
    dados_json = json.dumps(dados, ensure_ascii=False, separators=(",", ":"))
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Fintai · Micron (exemplo)</title>
<meta name="description" content="Tela de detalhes da ação no Fintai, com dados de exemplo da Micron (MU).">
<meta name="theme-color" content="#0e1420">
{tags_og("Fintai · Micron (exemplo)",
         "Tela de detalhes da ação no Fintai, com dados de exemplo da Micron (MU).",
         url=URL_PAGINA)}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Space+Grotesk:wght@600;700&display=swap">
<style>
{css}
/* ---- página avulsa (fora do Streamlit) ---- */
html {{ background: var(--bg); }}
body {{ margin: 0; background: var(--bg); font-family: var(--corpo); }}
.app {{ margin: 0 auto; padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); padding-bottom: 40px; }}
.proto {{ max-width: 520px; margin: 10px auto 6px; }}
</style>
</head>
<body>
<div style="padding:0 16px"><div class="proto">Dados de exemplo · MU em 13/11/2026 · não são cotações reais</div></div>
<div id="parte-a">
{(tela / "detalhe.html").read_text(encoding="utf-8")}
</div>
<div id="parte-b">
{(tela / "detalhe_fundo.html").read_text(encoding="utf-8")}
</div>
<script>
(function() {{
{js_a}
montar(document.getElementById('parte-a'), {dados_json});
}})();
</script>
<script>
(function() {{
{js_b}
montar(document.getElementById('parte-b'), {dados_json});
}})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    destino = RAIZ / "docs" / "index.html"
    destino.parent.mkdir(exist_ok=True)
    destino.write_text(pagina(pacote()), encoding="utf-8")
    print(f"{destino} gerado ({destino.stat().st_size / 1024:.0f} KB)")
