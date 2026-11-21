import datetime as dt
import json

import pytest

import utils.fetch_guidance as fg
from utils.fetch_guidance import Extracao, extrair_por_padroes, numero_br, planejar_ticker

HOJE = dt.date(2026, 11, 16)

# Linha do tempo do guidance de 2026 do Banco do Brasil (lucro líquido ajustado):
#   fev/2026: R$ 22 a 26 bi (payout 30%)  ->  13/05/2026: R$ 18 a 22 bi  ->  11/11/2026: R$ 9 a 11 bi (payout 25%)
# O vigente é o de 11/11/2026. A faixa de maio (18 a 22) é antiga e nunca pode ir para o app.
FATO_BB_FEV = """BANCO DO BRASIL S.A. FATO RELEVANTE Divulgação de Projeções Corporativas 2026.
O Banco do Brasil informa as projeções corporativas para 2026: Lucro Líquido Ajustado entre
R$ 22 bilhões e R$ 26 bilhões. Margem Financeira Bruta: crescimento entre 4% e 8%.
O Conselho de Administração aprovou payout de 30% para o exercício de 2026."""

FATO_BB_MAI = """BANCO DO BRASIL S.A. Projeções Corporativas 2026: Lucro Líquido Ajustado entre
R$ 18 bilhões e R$ 22 bilhões."""

FATO_BB_NOV = """BANCO DO BRASIL S.A. FATO RELEVANTE Projeções Corporativas 2026.
Lucro Líquido Ajustado entre R$ 9 bilhões e R$ 11 bilhões. Payout de 25% para o exercício de 2026."""

TABELA_BB_NOV = """Projeções Corporativas 2026 (R$ bilhões) Anterior Revisado
Lucro Líquido Ajustado 18 a 22 9 a 11  Custo do Crédito 65 a 70 80 a 83  Payout 25%"""

RELEASE_SEM_GUIDANCE = "Divulgação de resultados do 3T26. Lucro líquido de R$ 3,9 bilhões no trimestre."


def test_numero_br():
    assert numero_br("18,5") == 18.5 and numero_br("1.234,5") == 1234.5
    assert numero_br("1.234") == 1234 and numero_br("18.5") == 18.5 and numero_br("22") == 22


def test_fato_relevante_com_faixa_unica_tem_confianca_alta():
    ex = extrair_por_padroes(FATO_BB_NOV, 2026)
    assert (ex.lucro_min, ex.lucro_max) == (9e9, 11e9)
    assert ex.ano == 2026 and ex.payout == pytest.approx(0.25)
    assert ex.confianca == "alta" and ex.candidatos == 1
    assert "9 bilhões" in ex.trecho


def test_tabela_com_anterior_e_revisado_fica_sem_confianca():
    ex = extrair_por_padroes(TABELA_BB_NOV, 2026)
    assert ex is not None and ex.confianca == "baixa" and ex.candidatos == 2
    assert ex.lucro_min == 18e9            # a primeira faixa é a antiga; por isso não pode ir direto para o app


def test_release_sem_faixa_nao_e_guidance():
    assert extrair_por_padroes(RELEASE_SEM_GUIDANCE, 2026) is None


def test_projecao_de_outro_ano_fica_sem_confianca():
    ex = extrair_por_padroes(FATO_BB_NOV.replace("2026", "2027"), 2026)
    assert ex.confianca == "baixa" and ex.ano == 2027


def test_valor_em_milhoes():
    ex = extrair_por_padroes("Guidance 2026: lucro líquido ajustado de R$ 800 milhões a R$ 950 milhões.", 2026)
    assert (ex.lucro_min, ex.lucro_max) == (800e6, 950e6) and ex.confianca == "alta"


# ------------------------------------------------------------ decisão: AUTOMÁTICO COM PROTEÇÃO (sem rede)
# release oficial completo: a faixa aparece no texto e na tabela (trava 2)
FATO_BB_NOV_TABELA = FATO_BB_NOV + "\nTabela: Projeções 2026 (R$ bilhões) Lucro Líquido Ajustado 9 a 11"
MERCADO_BB = {"preco": 14.86, "pl": 5.9}      # cotação e P/L de 12 meses do Yahoo (falsos, só para o teste)


def _planejar(docs_datados, anterior=None, claude=None, vistos=None, mercado=MERCADO_BB, referencia=None):
    """docs_datados: [(data ISO, texto)], do mais novo para o mais antigo."""
    docs = [{"data": data, "categoria": "Fato Relevante", "assunto": "Projeções",
             "link": f"https://www.rad.cvm.gov.br/doc{i}.pdf"} for i, (data, _) in enumerate(docs_datados)]
    paginas = {d["link"]: texto for d, (_, texto) in zip(docs, docs_datados)}
    return planejar_ticker(
        "BBAS3", HOJE, anterior, set() if vistos is None else vistos,
        buscar_cnpj=lambda t, h: ("00.000.000/0001-91", "BANCO DO BRASIL S.A."),
        buscar_docs=lambda c, h: docs, ler_pdf=lambda link: (b"%PDF", paginas[link]),
        buscar_acoes=lambda t: 5.73e9, ler_com_claude=claude or (lambda *args: None),
        buscar_mercado=lambda t: mercado, referencia=referencia)


def _travou(item, nome):
    return any(tr["nome"] == nome and not tr["ok"] for tr in item["travas"])


NOV, MAI, FEV = "2026-11-11", "2026-05-13", "2026-02-12"
GUIDANCE_NOV = {"lucro_min": 9e9, "lucro_max": 11e9, "acoes": 5.73e9, "payout": 0.25, "ano": 2026,
                "data": "11/11/2026", "documento": "https://www.rad.cvm.gov.br/release-3t26.pdf"}
GUIDANCE_APROVADO = {"lucro_min": 9.5e9, "lucro_max": 11.5e9, "acoes": 5.73e9, "payout": 0.25, "ano": 2026,
                     "data": "15/08/2026", "documento": "https://www.rad.cvm.gov.br/antigo.pdf"}


def test_passa_nas_4_travas_e_publica_sozinho():
    item = _planejar([(NOV, FATO_BB_NOV_TABELA)], anterior=GUIDANCE_APROVADO)     # lucro de 10,5 para 10 bi: -4,8%
    assert item["acao"] == "commit" and item["motivo"].startswith("passou nas 4 travas")
    assert [t["nome"] for t in item["travas"]] == ["Fonte oficial", "Número em 2 lugares", "Variação até 20%", "P/L plausível"]
    assert all(t["ok"] for t in item["travas"])
    n = item["novo"]
    assert (n["lucro_min"], n["lucro_max"], n["payout"], n["acoes"]) == (9e9, 11e9, 0.25, 5.73e9)
    assert n["fonte"] == "BANCO DO BRASIL S.A., Fato Relevante de 11/11/2026 (CVM)"


def test_numero_so_uma_vez_no_documento_trava():
    item = _planejar([(NOV, FATO_BB_NOV)], anterior=GUIDANCE_APROVADO)
    assert item["acao"] == "pr" and _travou(item, "Número em 2 lugares") and "1 vez" in item["motivo"]


def test_primeira_gravacao_sem_guidance_no_app_trava():
    item = _planejar([(NOV, FATO_BB_NOV_TABELA)])
    assert item["acao"] == "pr" and _travou(item, "Variação até 20%") and "sem guidance anterior" in item["motivo"]
    assert item["novo"]["lucro_min"] == 9e9            # vai para o PR, você decide


def test_cadastro_manual_serve_de_referencia_para_a_trava_de_20():
    manual = {"lucro_min": 9e9, "lucro_max": 11e9, "payout": 0.25, "data": "11/11/2026"}
    item = _planejar([(NOV, FATO_BB_NOV_TABELA)], referencia=manual)
    assert item["acao"] == "commit" and "+0.0%" in item["travas"][2]["detalhe"]


def test_documento_fora_da_cvm_ou_sec_trava():
    item = planejar_ticker(
        "BBAS3", HOJE, GUIDANCE_APROVADO, set(), buscar_cnpj=lambda t, h: ("x", "BANCO DO BRASIL S.A."),
        buscar_docs=lambda c, h: [{"data": NOV, "categoria": "Fato Relevante", "assunto": "Projeções",
                                   "link": "https://blog.exemplo.com/bb.pdf"}],
        ler_pdf=lambda link: (b"%PDF", FATO_BB_NOV_TABELA), buscar_acoes=lambda t: 5.73e9,
        buscar_mercado=lambda t: MERCADO_BB)
    assert item["acao"] == "pr" and _travou(item, "Fonte oficial")


@pytest.mark.parametrize("mercado,trecho", [(None, "sem cotação"), ({"preco": 14.86, "pl": 40.0}, "fora de 1/3"),
                                             ({"preco": 14.86, "pl": None}, "sem P/L de referência")])
def test_p_l_sem_dado_ou_absurdo_trava(mercado, trecho):
    ref = {**GUIDANCE_APROVADO}
    if mercado and mercado["pl"] is None:
        ref = {"lucro_min": 9.5e9, "lucro_max": 11.5e9, "data": "x"}       # sem ações: não dá o P/L do anterior
    item = _planejar([(NOV, FATO_BB_NOV_TABELA)], anterior=GUIDANCE_APROVADO, mercado=mercado, referencia=ref)
    assert item["acao"] == "pr" and _travou(item, "P/L plausível") and trecho in item["motivo"]


def test_documento_mais_novo_sem_guidance_e_pulado():
    item = _planejar([("2026-11-14", RELEASE_SEM_GUIDANCE), (NOV, FATO_BB_NOV_TABELA)], anterior=GUIDANCE_APROVADO)
    assert item["acao"] == "commit" and item["novo"]["lucro_min"] == 9e9


def test_faixa_de_maio_e_descartada_quando_o_app_ja_tem_a_de_novembro():
    item = _planejar([(MAI, FATO_BB_MAI), (FEV, FATO_BB_FEV)], anterior=GUIDANCE_NOV)
    assert item["acao"] == "nada" and item["novo"] is None and "mais antigo" in item["motivo"]


def test_documento_com_mais_de_120_dias_e_duvida_e_trava_mesmo_passando_nas_travas():
    ant = {**GUIDANCE_APROVADO, "lucro_min": 17e9, "lucro_max": 21e9, "data": "01/04/2026"}
    item = _planejar([(MAI, FATO_BB_MAI + " Tabela: Lucro Líquido Ajustado 18 a 22")], referencia=ant,
                     mercado={"preco": 14.86, "pl": 5.0})
    assert all(t["ok"] for t in item["travas"])
    assert item["acao"] == "pr" and "120 dias" in item["motivo"] and item["duvidas"]


def test_nunca_volta_para_documento_antigo_quando_o_novo_e_ambiguo():
    item = _planejar([(NOV, TABELA_BB_NOV), (MAI, FATO_BB_MAI), (FEV, FATO_BB_FEV)])
    assert item["acao"] == "erro" and item["novo"] is None


def test_ambiguo_lido_pela_api_do_claude_passa_pelas_travas():
    lido = Extracao(lucro_min=9e9, lucro_max=11e9, payout=0.25, ano=2026,
                    trecho="Lucro Líquido Ajustado 18 a 22 9 a 11", metodo="API do Claude")
    item = _planejar([(NOV, TABELA_BB_NOV)], claude=lambda *args: lido, anterior=GUIDANCE_APROVADO)
    # "9 a 11" aparece uma vez só na tabela: trava 2 segura
    assert item["acao"] == "pr" and _travou(item, "Número em 2 lugares") and "API do Claude" in item["motivo"]
    assert item["novo"]["metodo"] == "API do Claude"


def test_documento_ja_tentado_nao_chama_a_api_de_novo():
    chamadas = []
    item = _planejar([(NOV, TABELA_BB_NOV)], claude=lambda *a: chamadas.append(a),
                     vistos={"https://www.rad.cvm.gov.br/doc0.pdf"})
    assert not chamadas and item["acao"] == "nada"


GUIDANCE_MAI = {"lucro_min": 18e9, "lucro_max": 22e9, "acoes": 5.73e9, "payout": 0.30, "ano": 2026,
                "data": "13/05/2026", "documento": "x"}


def test_corte_de_50_por_cento_trava():
    # o corte real do BB: de 18 a 22 (maio) para 9 a 11 (novembro)
    item = _planejar([(NOV, FATO_BB_NOV_TABELA)], anterior=GUIDANCE_MAI)
    assert item["acao"] == "pr" and _travou(item, "Variação até 20%") and "-50.0%" in item["motivo"]


@pytest.mark.parametrize("anterior,acao", [((12e9, 13e9), "commit"),     # 12,5 -> 10 bi: -20,0% (no limite)
                                           ((12e9, 14e9), "pr")])        # 13 -> 10 bi: -23%
def test_corte_de_20_por_cento(anterior, acao):
    ant = {**GUIDANCE_APROVADO, "lucro_min": anterior[0], "lucro_max": anterior[1]}
    assert _planejar([(NOV, FATO_BB_NOV_TABELA)], anterior=ant)["acao"] == acao


def test_mesmo_documento_ja_aplicado_nao_muda_nada():
    anterior = {**GUIDANCE_NOV, "documento": "https://www.rad.cvm.gov.br/doc0.pdf"}
    assert _planejar([(NOV, FATO_BB_NOV_TABELA)], anterior=anterior)["acao"] == "nada"


def test_ocorrencias_contam_texto_e_tabela_mas_nao_percentual():
    assert fg.ocorrencias_da_faixa(FATO_BB_NOV_TABELA, {"lucro_min": 9e9, "lucro_max": 11e9}) == 2
    assert fg.ocorrencias_da_faixa("crescimento entre 9% a 11%", {"lucro_min": 9e9, "lucro_max": 11e9}) == 0
    txt = "now expects 2026 adjusted EPS of $5.50 to $5.80. Outlook table: Adjusted EPS | $5.50 - $5.80"
    assert fg.ocorrencias_da_faixa(txt, {"lpa_min": 5.5, "lpa_max": 5.8}) == 2


# ------------------------------------------------------------ EUA (SEC)
ADM_TXT = ("ADM Reports Third Quarter 2026 Results. ... The Company now expects 2026 adjusted EPS of approximately "
           "$5.50 to $5.80, compared to prior guidance.")
ACM_TXT = ("Fiscal 2027 guidance: adjusted EPS of between $6.15 and $6.35 and adjusted EBITDA of $1,350 to $1,390 million. "
           "The Board increased the quarterly dividend by 10% to $0.34 per share.")
HSIC_TXT = ("Henry Schein is updating its 2026 financial guidance: non-GAAP diluted EPS for full year 2026 is now expected "
            "to be $5.42 to $5.48, compared with previously announced guidance.")


def test_sem_email_da_sec_os_eua_ficam_de_fora(monkeypatch):
    monkeypatch.delenv("SEC_CONTACT_EMAIL", raising=False)
    item = planejar_ticker("AAPL", HOJE, None, set())
    assert item["acao"] == "erro" and "SEC_CONTACT_EMAIL" in item["motivo"]


def test_user_agent_da_sec_vem_do_secret(monkeypatch):
    monkeypatch.setenv("SEC_CONTACT_EMAIL", "contato@exemplo.com")
    assert fg.cabecalho_sec()["User-Agent"] == "fintai/1.0 (contato: contato@exemplo.com)"
    import pathlib, re
    codigo = pathlib.Path(fg.__file__).read_text(encoding="utf-8")
    # nenhum e-mail escrito no código do robô
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", codigo.replace("41898282+github-actions[bot]@users.noreply.github.com", ""))


@pytest.mark.parametrize("texto,faixa,periodo,div", [(ADM_TXT, (5.50, 5.80), "2026", None),
                                                     (ACM_TXT, (6.15, 6.35), "FY2027", 1.36),
                                                     (HSIC_TXT, (5.42, 5.48), "2026", None)])
def test_extrai_lpa_de_comunicados_dos_eua(texto, faixa, periodo, div):
    ex = fg.extrair_eps_eua(texto, 2026)
    assert (ex["lpa_min"], ex["lpa_max"]) == faixa and ex["periodo"] == periodo
    assert ex["confianca"] == "alta" and ex["dividendo"] == div


ADM_DUAS = ("ADM Reports Third Quarter 2026 Results. The Company now expects 2026 adjusted EPS of approximately "
            "$5.50 to $5.80. In the second quarter, the Company had previously expected 2026 adjusted EPS of "
            "$5.15 to $5.60.")


def test_adm_com_faixa_antiga_e_nova_escolhe_a_nova():
    ex = fg.extrair_eps_eua(ADM_DUAS, 2026)
    assert (ex["lpa_min"], ex["lpa_max"]) == (5.50, 5.80) and ex["confianca"] == "alta"
    assert "5.15 a 5.60" in ex["escolha"]
    # mesma coisa com a faixa antiga primeiro no texto e entre parênteses
    txt = ("Outlook updated: 2026 adjusted EPS of $5.50 to $5.80 (prior guidance: adjusted EPS of $5.15 to $5.60) for 2026.")
    ex2 = fg.extrair_eps_eua(txt, 2026)
    assert (ex2["lpa_min"], ex2["lpa_max"]) == (5.50, 5.80) and ex2["confianca"] == "alta"


def test_duas_faixas_sem_marca_de_nova_ou_antiga_continua_sem_confianca():
    txt = ("The Company expects 2026 adjusted EPS of $5.50 to $5.80. Segment guidance: adjusted EPS of "
           "$4.10 to $4.30 for 2026 in Nutrition.")
    ex = fg.extrair_eps_eua(txt, 2026)
    assert ex["confianca"] == "baixa" and any("2 faixas" in m for m in ex["motivos"])


def test_duas_faixas_novas_diferentes_continua_sem_confianca():
    txt = ("The Company now expects 2026 adjusted EPS of $5.50 to $5.80. The Company raised 2026 adjusted EPS "
           "for the segment to $4.10 to $4.30.")
    assert fg.extrair_eps_eua(txt, 2026)["confianca"] == "baixa"


def _planejar_adm(texto, referencia, mercado={"preco": 60.0, "pl": 12.0}):
    doc = {"form": "8-K", "data": "2026-11-03", "acc": "0000007084-26-000054", "cik": "0000007084"}
    return fg.planejar_ticker_eua("ADM", HOJE, None, cabecalho=lambda: {"User-Agent": "x"},
                                  buscar_cik=lambda t, c: ("0000007084", "ARCHER-DANIELS-MIDLAND CO"),
                                  buscar_docs=lambda cik, c: [doc],
                                  ler_anexo=lambda d, c: ("https://www.sec.gov/Archives/edgar/data/7084/ex991.htm", texto),
                                  buscar_mercado=lambda t: mercado, referencia=referencia)


def test_planejar_eua_primeira_gravacao_trava():
    item = _planejar_adm(ADM_TXT, None)
    assert item["acao"] == "pr" and item["novo"]["lpa_min"] == 5.50 and item["novo"]["data"] == "03/11/2026"
    assert "SEC" in item["novo"]["fonte"] and _travou(item, "Variação até 20%")


def test_planejar_eua_passa_nas_4_travas_e_publica():
    txt = ADM_TXT + " 2026 Outlook table: Adjusted EPS $5.50 - $5.80"
    item = _planejar_adm(txt, {"lpa_min": 5.40, "lpa_max": 5.80, "data": "03/11/2026"})   # 5,60 -> 5,65: +0,9%
    assert item["acao"] == "commit", item["motivo"]
    # P/L 60 / 5,65 = 10,6 contra 12 de 12 meses: plausível
    assert "10.6" in item["travas"][3]["detalhe"]


def test_aplicar_grava_so_o_tipo_pedido(tmp_path, monkeypatch):
    monkeypatch.setattr(fg, "ARQ_AUTO", tmp_path / "auto.json")
    monkeypatch.setattr(fg, "ARQ_LOG", tmp_path / "log.json")
    plano = [{"ticker": "BBAS3", "acao": "commit", "novo": {"lucro_min": 1}, "motivo": ""},
             {"ticker": "ITUB4", "acao": "pr", "novo": {"lucro_min": 2}, "motivo": ""},
             {"ticker": "VALE3", "acao": "erro", "novo": None, "motivo": ""}]
    assert [i["ticker"] for i in fg.aplicar(plano, "commit")] == ["BBAS3"]
    assert json.loads((tmp_path / "auto.json").read_text()) == {"BBAS3": {"lucro_min": 1}}
    fg.aplicar(plano, "pr")
    assert set(json.loads((tmp_path / "auto.json").read_text())) == {"BBAS3", "ITUB4"}


# ------------------------------------------------------------ conferência da leitura pela API do Claude
from utils.fetch_guidance import _confere


def test_faixa_da_api_conferida_pelas_faixas_do_proprio_documento():
    ex = extrair_por_padroes(TABELA_BB_NOV, 2026)
    # trecho com formatação diferente da extraída do PDF (como aconteceu na primeira execução real)
    assert _confere(9e9, 11e9, TABELA_BB_NOV, "Lucro Líquido Ajustado | R$ 9 a 11 bi", ex.faixas)


def test_faixa_da_api_que_nao_esta_no_documento_e_descartada():
    ex = extrair_por_padroes(TABELA_BB_NOV, 2026)
    assert _confere(12e9, 14e9, TABELA_BB_NOV, "Lucro Líquido Ajustado entre 12 e 14", ex.faixas) is None


def test_trecho_confere_ignorando_espacos_e_separadores():
    texto = "Projeções\nLucro  Líquido\nAjustado entre R$ 9 bilhões e R$ 11 bilhões para 2026"
    assert _confere(9e9, 11e9, texto, "Lucro Líquido Ajustado entre R$ 9 bilhões e R$ 11 bilhões", [])


def test_a_api_recebe_as_faixas_do_documento():
    recebido = {}

    def claude(pdf, texto, ano, faixas):
        recebido["faixas"] = faixas
        return None
    _planejar([(NOV, TABELA_BB_NOV)], claude=claude)
    assert (9e9, 11e9) in recebido["faixas"] and (18e9, 22e9) in recebido["faixas"]


def test_inicial_eua_pega_o_primeiro_documento_do_ano():
    docs = [{"form": "8-K", "data": "2026-02-03", "acc": "a1", "cik": "7084"},
            {"form": "8-K", "data": "2026-04-29", "acc": "a2", "cik": "7084"}]
    textos = {"a1": "ADM provides 2026 guidance: the Company expects 2026 adjusted EPS of approximately $3.60 to $4.25.",
              "a2": "ADM now expects 2026 adjusted EPS of $4.00 to $4.50."}
    novo, motivo = fg.buscar_inicial_eua("ADM", "2026", cabecalho=lambda: {"User-Agent": "x"},
                                         buscar_cik=lambda t, c: ("0000007084", "ADM"),
                                         buscar_docs=lambda cik, c, i, f: docs,
                                         ler=lambda d, c: (f"https://sec/{d['acc']}", textos[d["acc"]]))
    assert motivo == "" and (novo["lpa_min"], novo["lpa_max"], novo["data"]) == (3.60, 4.25, "03/02/2026")
    vazio, motivo2 = fg.buscar_inicial_eua("HSIC", "2026", cabecalho=lambda: {"User-Agent": "x"},
                                           buscar_cik=lambda t, c: ("1", "HSIC"), buscar_docs=lambda *a: [],
                                           ler=lambda d, c: None)
    assert vazio is None and motivo2 == "sem projeção inicial encontrada"


# ------------------------------------------------------------ contábil 12 meses pela SEC
def _fato(ini, fim, val, form, filed):
    return {"start": ini, "end": fim, "val": val, "form": form, "filed": filed}


def _fatos_adm(com_4t26=False):
    e = [  # 2025: 9 meses acumulados e ano (10-K) -> 4T25 = 2,23 - 1,29 = 0,94
        _fato("2025-01-01", "2025-09-30", 1.29, "10-Q", "2025-11-04"),
        _fato("2025-01-01", "2025-12-31", 2.23, "10-K", "2026-02-18"),
        # 2026: trimestres de 3 meses
        _fato("2026-01-01", "2026-03-31", 1.07, "10-Q", "2026-05-05"),
        _fato("2026-04-01", "2026-06-30", 1.41, "10-Q", "2026-08-05"),
        _fato("2026-07-01", "2026-09-30", 1.70, "10-Q", "2026-11-04"),
        _fato("2026-01-01", "2026-09-30", 4.18, "10-Q", "2026-11-04"),
    ]
    if com_4t26:
        e.append(_fato("2026-01-01", "2026-12-31", 5.38, "10-K", "2027-02-17"))
    return {"facts": {"us-gaap": {"EarningsPerShareDiluted": {"units": {"USD/shares": e}}}}}


def test_contabil_sec_soma_4_trimestres_e_recalcula_com_balanco_novo():
    c = fg.lpa_ttm_sec(_fatos_adm(), dt.date(2026, 11, 17))
    assert c["status"] == "ok" and c["lpa_12m"] == pytest.approx(5.12)       # 0,94 + 1,07 + 1,41 + 1,70
    assert [t["fim"] for t in c["trimestres"]] == ["31/12/2025", "31/03/2026", "30/06/2026", "30/09/2026"]
    novo = fg.lpa_ttm_sec(_fatos_adm(com_4t26=True), dt.date(2027, 2, 20))  # chega o 10-K de 2026
    assert novo["lpa_12m"] == pytest.approx(5.38) and novo["trimestres"][-1]["fim"] == "31/12/2026"


def test_contabil_sec_incompleto():
    fatos = _fatos_adm()
    fatos["facts"]["us-gaap"]["EarningsPerShareDiluted"]["units"]["USD/shares"] = \
        fatos["facts"]["us-gaap"]["EarningsPerShareDiluted"]["units"]["USD/shares"][2:5]   # só 3 trimestres
    assert fg.lpa_ttm_sec(fatos, dt.date(2026, 11, 17))["status"] == "incompleto"
    assert fg.lpa_ttm_sec(_fatos_adm(), dt.date(2027, 8, 1))["status"] == "incompleto"   # SEC atrasada
    assert fg.lpa_ttm_sec({}, dt.date(2026, 11, 17))["status"] == "incompleto"


# ------------------------------------------------------------ contábil AJUSTADO (8-K Exhibit 99.1)
# Valores reais da SEC (8-K Exhibit 99.1 de cada trimestre): 4T25 0,87, 1T26 0,71, 2T26 1,84 e 3T26 1,77.
# 2026 até o 3T = 0,71 + 1,84 + 1,77 = 4,32; 12 meses = 5,19.
ADM_AJ = {"31/12/2025": 0.87, "31/03/2026": 0.71, "30/06/2026": 1.84, "30/09/2026": 1.77}


def _aj(valores):
    return {fim: {"lpa": v, "fonte": "SEC Form 8-K Exhibit 99.1, LPA Ajustado", "data": "x", "url": ""} for fim, v in valores.items()}


def test_contabil_ajustado_da_adm_soma_5_19_e_nao_5_12():
    gaap = fg.lpa_ttm_sec(_fatos_adm(), dt.date(2026, 11, 17))
    assert gaap["lpa_12m"] == pytest.approx(5.12)                          # GAAP
    c = fg.contabil_ajustado(gaap, _aj(ADM_AJ))
    assert c["lpa_12m"] == pytest.approx(5.19) and c["base"] == "ajustado" and c["trimestres_gaap"] == 0
    assert sum(t["lpa"] for t in c["trimestres"][1:]) == pytest.approx(4.32)   # 2026 até o 3T
    assert c["fonte"] == "SEC 8-K Exhibit 99.1, LPA Ajustado"
    assert [t["tipo"] for t in c["trimestres"]] == ["ajustado"] * 4
    # o LPA ajustado do trimestre sai do press release, sem confundir com o acumulado, o ano ou a projeção
    q3 = ("ADM Reports Third Quarter 2026 Results. Third quarter adjusted EPS of $1.77; year-to-date adjusted EPS "
          "of $4.32. The Company now expects 2026 adjusted EPS of approximately $5.50 to $5.80.")
    q4 = "Fourth quarter adjusted EPS of $0.87, down 24%. Full year adjusted EPS of $3.43. 2026 adjusted EPS guidance $3.60 to $4.25."
    assert fg.extrair_eps_ajustado_trimestre(q3) == 1.77 and fg.extrair_eps_ajustado_trimestre(q4) == 0.87


def test_falta_ajustado_em_um_trimestre_usa_gaap_so_nele_e_marca_no_card():
    import pathlib
    from tela.dados import contabil_12m
    gaap = fg.lpa_ttm_sec(_fatos_adm(), dt.date(2026, 11, 17))
    sem_1t = {k: v for k, v in ADM_AJ.items() if k != "31/03/2026"}
    c = fg.contabil_ajustado(gaap, _aj(sem_1t))
    assert [t["tipo"] for t in c["trimestres"]] == ["ajustado", "GAAP", "ajustado", "ajustado"]
    assert c["lpa_12m"] == pytest.approx(0.87 + 1.07 + 1.84 + 1.77)        # 1T26 pelo GAAP (1,07)
    assert c["fonte"] == "SEC 8-K Exhibit 99.1, LPA Ajustado (1 trimestre GAAP por falta de Ajustado)"
    lpa, fonte, _ = contabil_12m("ADM", 5.12, {"ADM": c})
    assert lpa == pytest.approx(5.55) and "1 trimestre GAAP por falta de Ajustado" in fonte
    js = pathlib.Path(fg.__file__).resolve().parent.parent.joinpath("tela", "detalhe.js").read_text(encoding="utf-8")
    assert "GAAP por falta de Ajustado" in js and "Contábil Ajustado 12 meses" in js



# ------------------------------------------------------------ contábil BBAS3 pelo release do BB (CVM)
BB_LUCRO = {"4T25": 5.70, "1T26": 3.40, "2T26": 3.91, "3T26": 1.27}     # R$ bi, exemplo do pedido
BB_DATAS = {"4T25": "2026-02-11", "1T26": "2026-05-13", "2T26": "2026-08-12", "3T26": "2026-11-11"}


def _release_bb(tri):
    """Release no formato do BB: frase de destaque e a tabela com os trimestres em R$ milhões."""
    v = BB_LUCRO[tri]
    milhoes = f"{v * 1000:,.0f}".replace(",", ".")
    return (f"Divulgação de Resultados {tri}. O lucro líquido ajustado alcançou R$ {str(v).replace('.', ',')} bilhões no {tri}. "
            f"Principais indicadores R$ milhões {tri} Lucro Líquido Ajustado {milhoes} RSPL 12,0%")


def test_bbas3_soma_4_trimestres_do_release_e_lpa_2_50():
    for tri in BB_LUCRO:
        v, como = fg.extrair_lucro_trimestre(_release_bb(tri), tri)
        assert v == pytest.approx(BB_LUCRO[tri] * 1e9) and como == "tabela"
    docs = [{"data": BB_DATAS[t], "categoria": "Dados Econômico-Financeiros", "assunto": "Divulgação de Resultados",
             "link": f"https://cvm/{t}.pdf"} for t in ("3T26", "2T26", "1T26", "4T25")]
    c = fg.contabil_br("BBAS3", dt.date(2026, 11, 17), {"fonte": "BB, Divulgação de Resultados, Lucro Líquido Ajustado"},
                       buscar_cnpj=lambda t, h: ("00000000000191", "BCO BRASIL S.A."), buscar_docs=lambda c, h: docs,
                       ler_pdf=lambda link: (b"", _release_bb(link.split("/")[-1][:4])), buscar_acoes=lambda t: 5.71e9)
    assert c["status"] == "ok" and [t["tri"] for t in c["trimestres"]] == ["4T25", "1T26", "2T26", "3T26"]
    assert round(c["lucro_12m"] / 1e9, 1) == 14.3 and round(c["lpa_12m"], 2) == 2.50
    assert c["fonte"] == "BB, Divulgação de Resultados, Lucro Líquido Ajustado" and c["data"] == "11/11/2026"
    assert c["trimestres"][-1]["data"] == "11/11/2026" and c["trimestres"][0]["data"] == "11/02/2026"


def test_bbas3_sem_ler_todos_os_releases_fica_pendente_sem_inventar():
    docs = [{"data": BB_DATAS["3T26"], "categoria": "Resultado", "assunto": "Divulgação de Resultados", "link": "x"}]
    c = fg.contabil_br("BBAS3", dt.date(2026, 11, 17), {}, buscar_cnpj=lambda t, h: ("1", "BB"),
                       buscar_docs=lambda c, h: docs, ler_pdf=lambda link: (b"", _release_bb("3T26")),
                       buscar_acoes=lambda t: 5.71e9)
    assert c["status"] == "pendente" and "lpa_12m" not in c
    # frase e tabela diferentes: sem confiança
    txt = "O lucro líquido ajustado foi de R$ 1,27 bilhão no 3T26. R$ milhões 3T26 Lucro Líquido Ajustado 2.100 RSPL"
    assert fg.extrair_lucro_trimestre(txt, "3T26")[0] is None
    assert fg.trimestre_do_documento(dt.date(2026, 2, 11)) == "4T25" and fg.trimestre_do_documento(dt.date(2026, 11, 11)) == "3T26"


def test_pendente_nao_apaga_valor_bom_ja_gravado(tmp_path, monkeypatch):
    import json
    arq = tmp_path / "br.json"
    arq.write_text(json.dumps({"BBAS3": {"status": "ok", "lpa_12m": 2.5}}), encoding="utf-8")
    monkeypatch.setattr(fg, "ARQ_CONTABIL_BR", arq)
    fg.aplicar_contabil_br([{"ticker": "BBAS3", "contabil_br": {"status": "pendente", "motivo": "PDF não abriu"}}])
    dado = json.loads(arq.read_text(encoding="utf-8"))["BBAS3"]
    assert dado["lpa_12m"] == 2.5 and dado["ultima_tentativa"] == "PDF não abriu"


def test_release_do_bb_com_colunas_de_variacao_e_frase_arredondada():
    txt = ("Análise do Desempenho 3T26. O lucro líquido ajustado foi de R$ 1,3 bilhão no 3T26, queda de 66,5%. "
           "Tabela 1 - Principais Indicadores R$ milhões 3T25 2T26 3T26 Var. % 3T25 2T26 9M25 9M26 Var. % "
           "Lucro Líquido Ajustado 3.785 3.906 1.270 (66,5) (67,5) 14.969 8.624 (42,4) RSPL Ajustado 8,4 8,3 2,8")
    r = fg.ler_lucro_trimestre(txt, "3T26")
    assert r["tabela"] == pytest.approx(1.270e9) and r["frase"] == pytest.approx(1.3e9)   # arredondada: 2,4%
    assert r["valor"] == pytest.approx(1.270e9) and r["motivo"] == "tabela"
    assert fg.ler_lucro_trimestre(txt, "2T26")["tabela"] == pytest.approx(3.906e9)
    # frase "no trimestre", sem tabela
    so_frase = "No período, o lucro líquido ajustado atingiu R$ 3,4 bilhões no trimestre, com RSPL de 8,4%."
    assert fg.ler_lucro_trimestre(so_frase, "1T26")["valor"] == pytest.approx(3.4e9)


def test_log_uma_linha_por_trimestre_e_documento_press_release():
    docs = [{"data": BB_DATAS["3T26"], "categoria": "Dados Econômico-Financeiros", "tipo": "Press-release",
             "assunto": "Análise do Desempenho 3T26", "link": "https://cvm/3T26.pdf"}]
    linhas = []
    fg.contabil_br("BBAS3", dt.date(2026, 11, 17), {}, buscar_cnpj=lambda t, h: ("1", "BB"), buscar_docs=lambda c, h: docs,
                   ler_pdf=lambda link: (b"", _release_bb("3T26")), buscar_acoes=lambda t: 5.71e9, registrar=linhas.append)
    tri = next(l for l in linhas if l.startswith("BBAS3 3T26:"))
    assert "frase=1.27 bi" in tri and "tabela=1.27 bi" in tri and "divergência=0.0%" in tri and "gravou=sim" in tri
    assert "link=https://cvm/3T26.pdf" in tri and "Análise do Desempenho 3T26" in tri
    assert linhas[-1].startswith("BBAS3: contábil pendente")          # só 1 trimestre: pendente, sem número


# ------------------------------------------------------------ casos do log da execução #9 (BBAS3)
def test_zero_nunca_e_gravado_e_tabela_em_bilhoes_sem_unidade():
    # tabela em R$ bilhões sem unidade escrita: antes virava 3,9 milhões = "0.00 bi"
    t = "No 2T26, o lucro líquido ajustado foi de R$ 3,91 bilhões. 1T26 2T26 Lucro Líquido Ajustado 3,4 3,9 RSPL"
    r = fg.ler_lucro_trimestre(t, "2T26")
    assert r["tabela"] == pytest.approx(3.9e9) and r["valor"] == pytest.approx(3.9e9)
    # sem frase e sem unidade, "3,9" é ambíguo: não usa
    assert fg.ler_lucro_trimestre("1T26 2T26 Lucro Líquido Ajustado 3,4 3,9 RSPL", "2T26")["valor"] is None
    # zero é leitura inválida
    zero = fg.ler_lucro_trimestre("R$ milhões 1T26 2T26 Lucro Líquido Ajustado 0 0 RSPL", "2T26")
    assert zero["tabela"] is None and zero["valor"] is None


def test_frase_do_ano_ou_do_semestre_e_descartada():
    ano = ("No 4T25, o lucro líquido ajustado acumulado no ano foi de R$ 20,7 bilhões. "
           "R$ milhões 4T24 3T25 4T25 Lucro Líquido Ajustado 9.578 3.785 5.737 RSPL")
    r = fg.ler_lucro_trimestre(ano, "4T25")
    assert r["frase"] is None and r["valor"] == pytest.approx(5.737e9) and r["motivo"] == "tabela"
    sem = ("No 2T25, o lucro líquido ajustado no semestre foi de R$ 11,2 bilhões. "
           "R$ milhões 2T24 1T25 2T25 1S24 1S25 Lucro Líquido Ajustado 9.501 7.373 3.784 18.700 11.157")
    r2 = fg.ler_lucro_trimestre(sem, "2T25")
    assert r2["frase"] is None and r2["valor"] == pytest.approx(3.784e9)


def test_bbas3_fluxo_com_os_formatos_do_log_fica_consecutivo():
    textos = {
        "3T26": "R$ milhões 3T25 2T26 3T26 Var. % 9M25 9M26 Lucro Líquido Ajustado 3.785 3.906 1.270 (66,5) 14.969 8.624",
        "2T26": "No 2T26, o lucro líquido ajustado foi de R$ 3,91 bilhões. 1T26 2T26 Lucro Líquido Ajustado 3,4 3,9 RSPL",
        "1T26": "O lucro líquido ajustado alcançou R$ 3,4 bilhões no 1T26. R$ milhões 4T25 1T26 Lucro Líquido Ajustado 5.737 3.400",
        "4T25": ("No 4T25, o lucro líquido ajustado acumulado no ano foi de R$ 20,7 bilhões. "
                 "R$ milhões 4T24 3T25 4T25 Lucro Líquido Ajustado 9.578 3.785 5.737 RSPL"),
    }
    docs = [{"data": BB_DATAS[t], "categoria": "Dados Econômico-Financeiros", "tipo": "Press-release",
             "assunto": f"Análise do Desempenho {t}", "link": f"https://cvm/{t}.pdf"} for t in ("3T26", "2T26", "1T26", "4T25")]
    linhas = []
    c = fg.contabil_br("BBAS3", dt.date(2026, 11, 17), {"fonte": "BB, Divulgação de Resultados, Lucro Líquido Ajustado"},
                       buscar_cnpj=lambda t, h: ("1", "BB"), buscar_docs=lambda c, h: docs,
                       ler_pdf=lambda link: (b"", textos[link.split("/")[-1][:4]]), buscar_acoes=lambda t: 5.709e9,
                       registrar=linhas.append)
    assert c["status"] == "ok" and [t["tri"] for t in c["trimestres"]] == ["4T25", "1T26", "2T26", "3T26"]
    assert c["lidos"] == {"4T25": 5.737, "1T26": 3.4, "2T26": 3.9, "3T26": 1.27}
    assert round(c["lucro_12m"] / 1e9, 2) == 14.31 and round(c["lpa_12m"], 2) == 2.51
    assert all(any(l.startswith(f"BBAS3 {t}:") for l in linhas) for t in ("3T26", "2T26", "1T26", "4T25"))


def test_valor_errado_ja_gravado_e_substituido_quando_acha_o_certo(tmp_path, monkeypatch):
    import json
    arq = tmp_path / "br.json"
    arq.write_text(json.dumps({"BBAS3": {"status": "ok", "lpa_12m": 1.0, "lidos": {"2T26": 0.0}}}), encoding="utf-8")
    monkeypatch.setattr(fg, "ARQ_CONTABIL_BR", arq)
    novo = {"status": "ok", "lpa_12m": 2.51, "lidos": {"2T26": 3.9}}
    fg.aplicar_contabil_br([{"ticker": "BBAS3", "contabil_br": novo}])
    assert json.loads(arq.read_text(encoding="utf-8"))["BBAS3"]["lpa_12m"] == 2.51


# ------------------------------------------------------------ casos do log da execução #10 (BBAS3)
REL = {"categoria": "Dados Econômico-Financeiros", "tipo": "Press-release"}


def test_relatorio_tabela_vence_frase_do_ano_que_escapou_do_filtro():
    # frase sem palavra de acumulado (escapa do filtro) com o valor do ano: no relatório, a tabela vence
    t = ("O lucro líquido ajustado foi de R$ 20,7 bilhões no período, com RSPL de 12,5%. "
         "R$ milhões 4T24 3T25 4T25 Lucro Líquido Ajustado 9.578 3.785 5.737 RSPL")
    r = fg.ler_lucro_trimestre(t, "4T25", tabela_vence=True)
    assert r["valor"] == pytest.approx(5.737e9) and "frase 20.70 bi descartada" in r["motivo"]
    assert fg.ler_lucro_trimestre(t, "4T25")["valor"] is None          # fora de relatório, continua sem confiança


def test_pdf_tenta_de_novo_quando_a_cvm_devolve_pagina(monkeypatch):
    chamadas = {"n": 0}

    def baixar(link):
        chamadas["n"] += 1
        if chamadas["n"] == 1:
            raise ValueError("não é PDF (b'Erro')")
        return b"%PDF-1.4"
    monkeypatch.setattr(fg, "_baixar_pdf", baixar)
    monkeypatch.setattr(fg, "_texto_pdf", lambda pdf: "texto do release")
    assert fg.texto_do_pdf("https://cvm/x", espera=0)[1] == "texto do release" and chamadas["n"] == 2


def test_trimestre_sem_abrir_usa_a_coluna_da_tabela_do_release_seguinte():
    textos = {
        "3T26": "R$ milhões 3T25 2T26 3T26 Var. % 9M25 9M26 Lucro Líquido Ajustado 3.785 3.906 1.270 (66,5) 14.969 8.624",
        "2T26": "R$ milhões 1T26 2T26 Lucro Líquido Ajustado 3.430 3.906 RSPL",
        "4T25": ("O lucro líquido ajustado foi de R$ 20,7 bilhões no período. "
                 "R$ milhões 4T24 3T25 4T25 Lucro Líquido Ajustado 9.578 3.785 5.737 RSPL"),
    }

    def ler(link):
        tri = link.split("/")[-1][:4]
        if tri == "1T26":
            raise ValueError("não é PDF (b'<html>')")                    # o relatório do 1T26 não abre
        return b"", textos[tri]
    docs = [{**REL, "data": BB_DATAS[t], "assunto": f"Análise do Desempenho {t}", "link": f"https://cvm/{t}.pdf"}
            for t in ("3T26", "2T26", "1T26", "4T25")]
    linhas = []
    c = fg.contabil_br("BBAS3", dt.date(2026, 11, 17), {"fonte": "BB, Divulgação de Resultados, Lucro Líquido Ajustado"},
                       buscar_cnpj=lambda t, h: ("1", "BB"), buscar_docs=lambda c, h: docs, ler_pdf=ler,
                       buscar_acoes=lambda t: 5.709e9, registrar=linhas.append)
    assert c["status"] == "ok" and c["lidos"] == {"4T25": 5.737, "1T26": 3.43, "2T26": 3.906, "3T26": 1.27}
    assert round(c["lucro_12m"] / 1e9, 2) == 14.34 and round(c["lpa_12m"], 2) == 2.51
    assert any("1T26: tabela=3.43 bi gravou=sim motivo=coluna 1T26 na tabela do release do 2T26" in l for l in linhas)
    assert next(t for t in c["trimestres"] if t["tri"] == "1T26")["leitura"] == "tabela do release do 2T26"


# ------------------------------------------------------------ 2ª camada: API do Claude
def _json_api(**k):
    import json
    base = {"tem_guidance": True, "ano": 2026, "lucro_min": None, "lucro_max": None, "lpa_min": None, "lpa_max": None,
            "payout": None, "trecho": "", "pagina": 3}
    return json.dumps({**base, **k})


def test_api_br_le_faixa_de_lucro_e_confere_no_documento():
    texto = "Guidance 2026: lucro líquido ajustado entre R$ 9 bilhões e R$ 11 bilhões, payout de 25%."
    ex = fg.extrair_com_claude(b"", texto, 2026, chamar=lambda c: _json_api(
        lucro_min=9e9, lucro_max=11e9, payout=0.25, trecho="lucro líquido ajustado entre R$ 9 bilhões e R$ 11 bilhões"))
    assert ex.metodo == "API do Claude" and (ex.lucro_min, ex.lucro_max, ex.payout) == (9e9, 11e9, 0.25)
    # trecho inventado: descartado
    assert fg.extrair_com_claude(b"", texto, 2026, chamar=lambda c: _json_api(
        lucro_min=20e9, lucro_max=22e9, trecho="lucro de 20 a 22 bilhões projetado pela diretoria")) is None


def test_api_eua_le_lpa_e_sem_guidance_devolve_none():
    texto = "For fiscal 2026, Apple expects revenue growth in the low single digits."
    assert fg.extrair_eps_com_claude(texto, 2026, chamar=lambda c: _json_api(tem_guidance=False)) is None
    txt2 = "The Company expects full-year adjusted EPS in the range of $5.50 to $5.80."
    r = fg.extrair_eps_com_claude(txt2, 2026, chamar=lambda c: _json_api(
        lpa_min=5.5, lpa_max=5.8, trecho="full-year adjusted EPS in the range of $5.50 to $5.80"))
    assert (r["lpa_min"], r["lpa_max"], r["pagina"]) == (5.5, 5.8, 3)


def test_api_falha_mantem_o_anterior_e_marca_sem_guidance():
    anterior = {"lpa_min": 5.5, "lpa_max": 5.8, "data": "03/11/2026"}
    doc = {"form": "8-K", "data": "2026-11-03", "acc": "a", "cik": "1"}
    item = fg.planejar_ticker_eua("AAPL", HOJE, anterior, cabecalho=lambda: {"User-Agent": "x"},
                                  buscar_cik=lambda t, c: ("1", "APPLE"), buscar_docs=lambda cik, c: [doc],
                                  ler_anexo=lambda d, c: ("https://sec/x", "Apple reports results. Revenue grew 8%."),
                                  ler_claude=lambda texto, ano: None)
    assert item["acao"] == "nada" and item["novo"] is None and item["motivo"].startswith("sem guidance")
    # e chamou a API uma vez só para o documento
    vistos = set()
    chamadas = []
    fg.planejar_ticker_eua("AAPL", HOJE, None, cabecalho=lambda: {"User-Agent": "x"},
                           buscar_cik=lambda t, c: ("1", "APPLE"), buscar_docs=lambda cik, c: [doc],
                           ler_anexo=lambda d, c: ("https://sec/x", "sem faixa"),
                           ler_claude=lambda texto, ano: chamadas.append(1), vistos=vistos)
    fg.planejar_ticker_eua("AAPL", HOJE, None, cabecalho=lambda: {"User-Agent": "x"},
                           buscar_cik=lambda t, c: ("1", "APPLE"), buscar_docs=lambda cik, c: [doc],
                           ler_anexo=lambda d, c: ("https://sec/x", "sem faixa"),
                           ler_claude=lambda texto, ano: chamadas.append(1), vistos=vistos)
    assert len(chamadas) == 1


# ------------------------------------------------------------ log de decisões, avisos e resumo de sexta
def test_log_registra_publicado_e_travado_sem_repetir_travado(tmp_path, monkeypatch):
    monkeypatch.setattr(fg, "ARQ_LOG", tmp_path / "log.json")
    pub = _planejar([(NOV, FATO_BB_NOV_TABELA)], anterior=GUIDANCE_APROVADO)
    trav = {**_planejar([(NOV, FATO_BB_NOV_TABELA)], anterior=GUIDANCE_MAI), "ticker": "ITUB4"}
    novos = fg.registrar([pub, trav], dt.date(2026, 11, 13))
    assert [(r["ticker"], r["decisao"]) for r in novos] == [("BBAS3", "publicado"), ("ITUB4", "travado")]
    assert novos[0]["faixa"] == "lucro R$ 9,0 a 11,0 bi (2026)"
    registro = json.loads((tmp_path / "log.json").read_text())
    assert fg.ja_avisado(registro, trav)                 # dia seguinte: mesmo documento, não avisa de novo
    assert fg.registrar([trav], dt.date(2026, 11, 14)) == []


def test_pr_nao_reabre_quando_todos_os_travados_ja_foram_avisados(tmp_path, monkeypatch):
    monkeypatch.setattr(fg, "ARQ_AUTO", tmp_path / "auto.json")
    plano = [{"ticker": "ITUB4", "acao": "pr", "novo": {"lucro_min": 2}, "motivo": "", "ja_avisado": True}]
    assert fg.aplicar(plano, "pr") == [] and not (tmp_path / "auto.json").exists()


def test_resumo_de_sexta_separa_publicado_e_travado():
    registro = [
        {"data": "2026-11-09", "ticker": "BBAS3", "decisao": "publicado", "faixa": "lucro R$ 9,0 a 11,0 bi (2026)",
         "fonte": "BB, Fato Relevante", "url": "https://www.rad.cvm.gov.br/x", "travas": [], "duvidas": []},
        {"data": "2026-11-12", "ticker": "AAPL", "decisao": "travado", "faixa": "LPA 7.10 a 7.30 (2026)",
         "fonte": "Apple 8-K", "url": "https://www.sec.gov/x",
         "travas": [{"nome": "Variação até 20%", "ok": False, "detalhe": "sem guidance anterior no app para comparar"}],
         "duvidas": []},
        {"data": "2026-11-01", "ticker": "VELHO", "decisao": "publicado", "faixa": "x", "fonte": "x", "url": "x"}]
    txt = fg.resumo_semana(registro, dt.date(2026, 11, 13))
    assert "Publicado sozinho (1)" in txt and "**BBAS3** (09/11/2026)" in txt
    assert "Travado para você decidir (1)" in txt and "❌ Variação até 20%" in txt and "VELHO" not in txt
    assert "Nada." in fg.resumo_semana([], dt.date(2026, 11, 13))


def test_aviso_de_publicado_mostra_as_travas():
    item = _planejar([(NOV, FATO_BB_NOV_TABELA)], anterior=GUIDANCE_APROVADO)
    txt = fg.aviso_publicado([item])
    assert "## BBAS3: lucro R$ 9,0 a 11,0 bi (2026)" in txt and txt.count("✅") == 4


def test_contabil_br_grava_indicador_de_atualizacao_no_fim(tmp_path, monkeypatch):
    arq = tmp_path / "br.json"
    monkeypatch.setattr(fg, "ARQ_CONTABIL_BR", arq)
    ok = {"status": "ok", "lpa_12m": 2.51, "trimestres": [{"tri": "2T26"}, {"tri": "3T26"}]}
    agora = dt.datetime(2026, 11, 17, 21, 32, tzinfo=dt.timezone.utc)          # 18:32 em Brasília
    fg.aplicar_contabil_br([{"ticker": "BBAS3", "contabil_br": ok}], agora=agora)
    dado = json.loads(arq.read_text(encoding="utf-8"))["BBAS3"]
    assert list(dado)[-3:] == ["atualizado_em", "trimestre_ref", "trimestre_data"]
    assert (dado["atualizado_em"], dado["trimestre_ref"], dado["trimestre_data"]) == ("17/11 18:32", "3T26", "set/26")
    # leitura falhou no dia seguinte: mantém o valor e a hora da última leitura boa (o indicador envelhece)
    fg.aplicar_contabil_br([{"ticker": "BBAS3", "contabil_br": {"status": "pendente", "motivo": "PDF não abriu"}}],
                           agora=agora + dt.timedelta(days=1))
    dado = json.loads(arq.read_text(encoding="utf-8"))["BBAS3"]
    assert dado["atualizado_em"] == "17/11 18:32" and list(dado)[-1] == "trimestre_data"
    assert dado["ultima_tentativa"] == "PDF não abriu"


def test_contabil_eua_grava_indicador_de_atualizacao_calculando_o_trimestre_pelo_fim():
    # EUA não tem "tri" (ex. "3T26") pronto, só "fim" (DD/MM/AAAA): o carimbo calcula o trimestre
    # a partir do mês, na mesma notação usada na B3, e "manter isso para todos" (ADM, AAPL etc.)
    ok = {"status": "ok", "lpa_12m": 5.19, "trimestres": [{"fim": "30/06/2026"}, {"fim": "30/09/2026"}]}
    agora = dt.datetime(2026, 11, 17, 21, 32, tzinfo=dt.timezone.utc)
    dado = fg.carimbo_atualizacao(ok, agora)
    assert (dado["atualizado_em"], dado["trimestre_ref"], dado["trimestre_data"]) == ("17/11 18:32", "3T26", "set/26")


def test_contabil_eua_grava_indicador_e_pendente_nao_apaga_valor_bom(tmp_path, monkeypatch):
    arq = tmp_path / "sec.json"
    monkeypatch.setattr(fg, "ARQ_CONTABIL", arq)
    ok = {"status": "ok", "lpa_12m": 5.19, "trimestres": [{"fim": "31/03/2026"}, {"fim": "30/06/2026"}]}
    agora = dt.datetime(2026, 11, 17, 21, 32, tzinfo=dt.timezone.utc)
    fg.aplicar_contabil([{"ticker": "ADM", "contabil": ok}], agora=agora)
    dado = json.loads(arq.read_text(encoding="utf-8"))["ADM"]
    assert list(dado)[-3:] == ["atualizado_em", "trimestre_ref", "trimestre_data"]
    assert (dado["atualizado_em"], dado["trimestre_ref"], dado["trimestre_data"]) == ("17/11 18:32", "2T26", "jun/26")
    # leitura ficou incompleta depois: mantém o valor e a hora da última leitura boa
    fg.aplicar_contabil([{"ticker": "ADM", "contabil": {"status": "incompleto", "motivo": "só 3 trimestre(s) na SEC"}}],
                       agora=agora + dt.timedelta(days=1))
    dado = json.loads(arq.read_text(encoding="utf-8"))["ADM"]
    assert dado["atualizado_em"] == "17/11 18:32" and list(dado)[-1] == "trimestre_data"
    assert dado["ultima_tentativa"] == "só 3 trimestre(s) na SEC"


# ------------------------------------------------------------ fila pública de tickers novos
def test_fila_sem_token_nao_processa_nada(monkeypatch):
    monkeypatch.delenv("GITHUB_QUEUE_TOKEN", raising=False)
    assert fg.processar_fila(HOJE, token=None) == []


def test_fila_valida_e_registra_em_guidance_tickers(tmp_path, monkeypatch):
    monkeypatch.setattr(fg, "ARQ_TICKERS", tmp_path / "tickers.json")
    monkeypatch.setattr(fg, "ARQ_NAO_VALIDADO", tmp_path / "nv.json")
    (tmp_path / "tickers.json").write_text('["BBAS3"]', encoding="utf-8")
    validado = {"ticker": "VALE3", "acao": "pr", "novo": {"lucro_min": 1, "lucro_max": 2},
               "motivo": "passou nas 4 travas",
               "travas": [{"nome": "Fonte oficial", "ok": True}, {"nome": "Número em 2 lugares", "ok": True},
                         {"nome": "Variação até 20%", "ok": False}, {"nome": "P/L plausível", "ok": True}]}
    fechadas = []
    fg.processar_fila(HOJE, token="tok",
                      listar=lambda tok: [{"ticker": "VALE3", "numero": 10, "pedidos": 7, "criada_em": "x"}],
                      fechar=lambda n, tok, c: fechadas.append((n, c)),
                      planejar_br=lambda t, h, a, v: validado)
    tickers = json.loads((tmp_path / "tickers.json").read_text())
    assert tickers == ["BBAS3", "VALE3"]
    assert fechadas and fechadas[0][0] == 10 and "Validado" in fechadas[0][1]
    assert not (tmp_path / "nv.json").exists()


def test_fila_nao_valida_nao_cadastra_e_fica_travado(tmp_path, monkeypatch):
    monkeypatch.setattr(fg, "ARQ_TICKERS", tmp_path / "tickers.json")
    monkeypatch.setattr(fg, "ARQ_NAO_VALIDADO", tmp_path / "nv.json")
    nao_validado = {"ticker": "ABCD3", "acao": "pr", "novo": None, "motivo": "sem guidance confirmado",
                    "travas": [{"nome": "Fonte oficial", "ok": True}, {"nome": "Número em 2 lugares", "ok": False}]}
    fechadas = []
    fg.processar_fila(HOJE, token="tok",
                      listar=lambda tok: [{"ticker": "ABCD3", "numero": 11, "pedidos": 2, "criada_em": "x"}],
                      fechar=lambda n, tok, c: fechadas.append((n, c)),
                      planejar_br=lambda t, h, a, v: nao_validado)
    assert not (tmp_path / "tickers.json").exists()
    nv = json.loads((tmp_path / "nv.json").read_text())
    assert nv == {"ABCD3": {"motivo": "sem guidance confirmado", "data": f"{HOJE:%d/%m/%Y}"}}
    assert fechadas and "Não validado" in fechadas[0][1]


def test_fila_pula_ticker_ja_registrado_ou_ja_nao_validado(tmp_path, monkeypatch):
    monkeypatch.setattr(fg, "ARQ_TICKERS", tmp_path / "tickers.json")
    monkeypatch.setattr(fg, "ARQ_NAO_VALIDADO", tmp_path / "nv.json")
    (tmp_path / "tickers.json").write_text('["BBAS3"]', encoding="utf-8")
    (tmp_path / "nv.json").write_text('{"ZZZZ": {"motivo": "x", "data": "x"}}', encoding="utf-8")
    chamadas = []
    resultados = fg.processar_fila(
        HOJE, token="tok",
        listar=lambda tok: [{"ticker": "BBAS3", "numero": 1, "pedidos": 5}, {"ticker": "ZZZZ", "numero": 2, "pedidos": 3}],
        fechar=lambda n, tok, c: None, planejar_br=lambda t, h, a, v: chamadas.append(t))
    assert resultados == [] and not chamadas


def test_fila_limita_quantidade_por_execucao(tmp_path, monkeypatch):
    monkeypatch.setattr(fg, "ARQ_TICKERS", tmp_path / "tickers.json")
    monkeypatch.setattr(fg, "ARQ_NAO_VALIDADO", tmp_path / "nv.json")
    fila = [{"ticker": f"T{i}", "numero": i, "pedidos": 1} for i in range(5)]
    chamados = []
    fg.processar_fila(HOJE, token="tok", max_por_run=2, listar=lambda tok: fila, fechar=lambda n, tok, c: None,
                      planejar_us=lambda t, h, a: chamados.append(t) or {"acao": "nada", "motivo": "x", "travas": []})
    assert len(chamados) == 2


def test_fila_formato_invalido_fecha_sem_processar(tmp_path, monkeypatch):
    monkeypatch.setattr(fg, "ARQ_TICKERS", tmp_path / "tickers.json")
    monkeypatch.setattr(fg, "ARQ_NAO_VALIDADO", tmp_path / "nv.json")
    fechadas = []
    fg.processar_fila(HOJE, token="tok", listar=lambda tok: [{"ticker": "'; DROP TABLE x", "numero": 9, "pedidos": 1}],
                      fechar=lambda n, tok, c: fechadas.append(c))
    assert fechadas and "inválido" in fechadas[0]


def test_fila_pula_erro_de_configuracao_sem_bloquear_o_ticker(tmp_path, monkeypatch):
    monkeypatch.setattr(fg, "ARQ_TICKERS", tmp_path / "tickers.json")
    monkeypatch.setattr(fg, "ARQ_NAO_VALIDADO", tmp_path / "nv.json")
    fechadas = []
    erro = {"acao": "erro", "motivo": "sem SEC_CONTACT_EMAIL (Secret do GitHub): a SEC exige e-mail de contato", "travas": []}
    fg.processar_fila(HOJE, token="tok", listar=lambda tok: [{"ticker": "MSFT", "numero": 1, "pedidos": 1}],
                      fechar=lambda n, tok, c: fechadas.append(c), planejar_us=lambda t, h, a: erro)
    assert not fechadas and not (tmp_path / "nv.json").exists()


# ------------------------------------------------------------ histórico (janela deslizante) da API do Claude
def test_api_br_historico_consistente_e_propagado():
    texto = "Guidance 2026: lucro líquido ajustado entre R$ 9 bilhões e R$ 11 bilhões, payout de 25%."
    historico = [{"lucro_min": 18e9, "lucro_max": 22e9, "lpa_min": None, "lpa_max": None, "ano": 2026, "trecho_curto": "18 a 22"},
                 {"lucro_min": 9e9, "lucro_max": 11e9, "lpa_min": None, "lpa_max": None, "ano": 2026, "trecho_curto": "9 a 11"}]
    ex = fg.extrair_com_claude(b"", texto, 2026, chamar=lambda c: _json_api(
        lucro_min=9e9, lucro_max=11e9, trecho="lucro líquido ajustado entre R$ 9 bilhões e R$ 11 bilhões", historico=historico))
    assert ex.historico == historico
    assert any("histórico" in m for m in ex.motivos)
    n = {"lucro_min": 9e9, "lucro_max": 11e9, "acoes": 5.73e9, "payout": 0.25, "ano": 2026,
        "metodo": "API do Claude", "fonte": "x", "url": "x", "trecho": "x", "historico": historico}
    assert "18,0 a 22,0 bi" in fg.resumo_pr([{"ticker": "BBAS3", "novo": n, "anterior": None, "motivo": "x"}])


def test_api_br_historico_inconsistente_descarta_leitura():
    # a API devolveu 9-11 no topo, mas o último item do histórico é outra faixa: não bate, descarta
    texto = "Guidance 2026: lucro líquido ajustado entre R$ 9 bilhões e R$ 11 bilhões, payout de 25%."
    historico = [{"lucro_min": 18e9, "lucro_max": 22e9, "lpa_min": None, "lpa_max": None, "ano": 2026, "trecho_curto": "x"}]
    assert fg.extrair_com_claude(b"", texto, 2026, chamar=lambda c: _json_api(
        lucro_min=9e9, lucro_max=11e9, trecho="lucro líquido ajustado entre R$ 9 bilhões e R$ 11 bilhões",
        historico=historico)) is None


def test_api_eua_historico_consistente_e_inconsistente():
    txt = "The Company expects full-year adjusted EPS in the range of $5.50 to $5.80."
    bom = [{"lpa_min": 5.15, "lpa_max": 5.60, "lucro_min": None, "lucro_max": None, "ano": 2026, "trecho_curto": "x"},
          {"lpa_min": 5.50, "lpa_max": 5.80, "lucro_min": None, "lucro_max": None, "ano": 2026, "trecho_curto": "y"}]
    r = fg.extrair_eps_com_claude(txt, 2026, chamar=lambda c: _json_api(
        lpa_min=5.5, lpa_max=5.8, trecho="full-year adjusted EPS in the range of $5.50 to $5.80", historico=bom))
    assert r["historico"] == bom
    ruim = [{"lpa_min": 1.0, "lpa_max": 2.0, "lucro_min": None, "lucro_max": None, "ano": 2026, "trecho_curto": "x"}]
    assert fg.extrair_eps_com_claude(txt, 2026, chamar=lambda c: _json_api(
        lpa_min=5.5, lpa_max=5.8, trecho="full-year adjusted EPS in the range of $5.50 to $5.80", historico=ruim)) is None


def test_historico_txt_formata_do_mais_antigo_ao_mais_novo():
    historico = [{"lucro_min": 18e9, "lucro_max": 22e9, "ano": 2026}, {"lpa_min": 9.9, "lpa_max": 10.65, "ano": 2026}]
    assert fg._historico_txt(historico) == "R$ 18,0 a 22,0 bi (2026) -> LPA 9.90 a 10.65 (2026)"
    assert fg._historico_txt([]) == ""


def test_historico_sem_itens_nao_bloqueia_leitura_unica():
    assert fg._historico_bate_com_atual([], 9e9, 11e9, "lucro") is True


# ------------------------------------------------------------ B3SA3: dígito dentro do código (não só no fim)
def test_b3sa3_e_roteada_para_cvm_nao_para_a_sec():
    # antes do fix, [A-Z]{4}\d{1,2} não batia com B3SA3 (o "3" fica no meio) e caía na SEC por engano
    item = fg.planejar_ticker("B3SA3", HOJE, None, set(),
                              buscar_cnpj=lambda t, h: None)   # força "erro" só para provar que entrou no ramo BR
    assert item["acao"] == "erro" and "CNPJ" in item["motivo"]


def test_padrao_br_aceita_digito_no_meio_do_codigo_sem_confundir_eua():
    import re
    padrao = r"(?=.*[A-Z])[A-Z0-9]{4}\d{1,2}"
    assert re.fullmatch(padrao, "B3SA3") and re.fullmatch(padrao, "PETR4") and re.fullmatch(padrao, "BOVA11")
    assert not re.fullmatch(padrao, "AAPL") and not re.fullmatch(padrao, "TGT") and not re.fullmatch(padrao, "PANW")


# ------------------------------------------------------------ fallback de ano (título/cabeçalho e vizinhança da faixa)
def test_ano_no_titulo_e_usado_mas_confianca_fica_baixa():
    texto = "A Companhia estima lucro líquido ajustado entre R$ 9 bilhões e R$ 11 bilhões, payout de 25%."
    ex = fg.extrair_por_padroes(texto, 2026, titulo="Projeções Corporativas 2026")
    assert ex.ano == 2026 and ex.confianca == "baixa"
    assert any("título" in m and "2026" in m for m in ex.motivos)


def test_ano_na_vizinhanca_da_faixa_e_usado_quando_titulo_nao_ajuda():
    texto = ("Release de resultados. " + "x" * 50 + " Em 2026, a Companhia estima lucro líquido ajustado "
             "entre R$ 9 bilhões e R$ 11 bilhões, payout de 25%.")
    ex = fg.extrair_por_padroes(texto, 2026, titulo="Divulgação de Resultados")   # título sem ano nenhum
    assert ex.ano == 2026 and ex.confianca == "baixa"
    assert any("perto da faixa" in m for m in ex.motivos)


def test_titulo_com_dois_anos_diferentes_cai_para_a_vizinhanca():
    texto = "Em 2026, a Companhia estima lucro líquido ajustado entre R$ 9 bilhões e R$ 11 bilhões, payout de 25%."
    ex = fg.extrair_por_padroes(texto, 2026, titulo="Resultados 2025 e projeções 2026")   # 2 anos no título: ambíguo
    assert ex.ano == 2026 and any("perto da faixa" in m for m in ex.motivos)


def test_sem_ano_em_nenhum_lugar_mantem_comportamento_atual():
    texto = "A Companhia estima lucro líquido ajustado entre R$ 9 bilhões e R$ 11 bilhões, payout de 25%."
    ex = fg.extrair_por_padroes(texto, 2026, titulo="Divulgação de Resultados")
    assert ex.ano is None and ex.confianca == "baixa"
    assert "ano da projeção não encontrado" in ex.motivos


def test_dois_anos_no_titulo_e_tambem_na_vizinhanca_nao_inventa():
    texto = "Em 2025 ou 2026, a Companhia estima lucro líquido ajustado entre R$ 9 bilhões e R$ 11 bilhões."
    ex = fg.extrair_por_padroes(texto, 2026, titulo="Resultados 2024 e 2025")
    assert ex.ano is None and "ano da projeção não encontrado" in ex.motivos


def test_ano_ja_encontrado_pelo_padrao_normal_nao_muda_com_fallback():
    # "guidance 2026" perto do número: já tinha ano antes do fix, continua idêntico (requisito do pedido)
    texto = "Guidance 2026: lucro líquido ajustado entre R$ 9 bilhões e R$ 11 bilhões, payout de 25%."
    ex = fg.extrair_por_padroes(texto, 2026, titulo="Resultados 2099")   # título com outro ano: não deve nem olhar
    assert ex.ano == 2026 and ex.confianca == "alta"
    assert not any("título" in m or "vizinhança" in m or "perto da faixa" in m for m in ex.motivos)


def test_fallback_de_ano_nao_publica_sozinho_mesmo_batendo_com_ano_alvo(tmp_path, monkeypatch):
    # ponta a ponta: ano só veio do fallback -> confiança baixa -> precisa da API do Claude confirmar;
    # sem confirmação, trava (erro), nunca publica sozinho só porque o ano bateu por acaso
    texto = "Em 2026, a Companhia estima lucro líquido ajustado entre R$ 9 bilhões e R$ 11 bilhões, payout de 25%."
    docs = [{"data": "2026-11-11", "categoria": "Divulgação de Resultados", "assunto": "",
            "link": "https://www.rad.cvm.gov.br/doc0.pdf"}]
    item = fg.planejar_ticker(
        "BBAS3", dt.date(2026, 11, 16), None, set(),
        buscar_cnpj=lambda t, h: ("00.000.000/0001-91", "BANCO DO BRASIL S.A."),
        buscar_docs=lambda c, h: docs, ler_pdf=lambda link: (b"%PDF", texto),
        buscar_acoes=lambda t: 5.73e9, ler_com_claude=lambda *a: None)
    assert item["acao"] == "erro" and "sem confiança" in item["motivo"]


# ------------------------------------------------------------ LPA anual direto da SEC (histórico, não TTM)
def test_lpa_anual_sec_so_pega_10k_completo_ignora_trimestre():
    fatos = {"facts": {"us-gaap": {"EarningsPerShareDiluted": {"units": {"USD/shares": [
        {"form": "10-K", "start": "2022-09-01", "end": "2023-08-31", "val": -5.34, "filed": "2023-10-01"},
        {"form": "10-K", "start": "2023-09-03", "end": "2024-08-29", "val": 0.70, "filed": "2024-10-01"},
        {"form": "10-K", "start": "2024-08-30", "end": "2025-08-28", "val": 7.59, "filed": "2025-10-01"},
        {"form": "10-Q", "start": "2025-09-01", "end": "2025-11-30", "val": 2.10, "filed": "2026-01-05"},
    ]}}}}}
    r = fg.lpa_anual_sec(fatos)
    assert [x["ano"] for x in r] == [2023, 2024, 2025]
    assert r[-1] == {"ano": 2025, "lpa": 7.59, "fim": "28/08/2025", "anuncio": "01/10/2025", "form": "10-K", "moeda": None}


def test_lpa_anual_sec_reapresentacao_10ka_ganha_do_10k_original():
    fatos = {"facts": {"us-gaap": {"EarningsPerShareDiluted": {"units": {"USD/shares": [
        {"form": "10-K", "start": "2023-09-03", "end": "2024-08-29", "val": 0.70, "filed": "2024-10-01"},
        {"form": "10-K/A", "start": "2023-09-03", "end": "2024-08-29", "val": 0.68, "filed": "2024-11-15"},
    ]}}}}}
    r = fg.lpa_anual_sec(fatos)
    assert len(r) == 1 and r[0]["lpa"] == 0.68 and r[0]["form"] == "10-K/A"


def test_lpa_anual_sec_sem_fato_devolve_lista_vazia():
    assert fg.lpa_anual_sec({}) == []
    assert fg.lpa_anual_sec({"facts": {"us-gaap": {}}}) == []


def test_lpa_anual_sec_aceita_20f_em_euro_emissora_estrangeira():
    """ASML (e outras emissoras estrangeiras) arquiva 20-F, não 10-K, com o LPA em EUR/shares, não
    USD/shares - sem isso, o histórico da SEC nunca aparecia pra elas e caía sempre no Yahoo (só ~4
    anos). Marca moeda="EUR" pra quem usar saber que precisa converter antes de misturar com dólar."""
    fatos = {"facts": {"us-gaap": {"EarningsPerShareDiluted": {"units": {"EUR/shares": [
        {"form": "20-F", "start": "2023-01-01", "end": "2023-12-31", "val": 20.09, "filed": "2024-02-14"},
        {"form": "20-F", "start": "2024-01-01", "end": "2024-12-31", "val": 17.86, "filed": "2025-02-12"},
    ]}}}}}
    r = fg.lpa_anual_sec(fatos)
    assert [x["ano"] for x in r] == [2023, 2024]
    assert r[0] == {"ano": 2023, "lpa": 20.09, "fim": "31/12/2023", "anuncio": "14/02/2024", "form": "20-F", "moeda": "EUR"}


def test_lpa_anual_sec_usa_a_data_do_anuncio_original_nao_do_comparativo_repetido():
    """Emissora estrangeira (ex. ASML) repete o mesmo valor de um ano como comparativo em 2-3 20-F
    seguintes - sem isso, "anuncio" viraria a data do filing mais recente (anos depois), e o câmbio
    EUR->USD usado pra converter esse LPA ficaria errado (câmbio de hoje aplicado a um ano antigo,
    exatamente o que essa regra deveria evitar)."""
    fatos = {"facts": {"us-gaap": {"EarningsPerShareDiluted": {"units": {"EUR/shares": [
        {"form": "20-F", "start": "2023-01-01", "end": "2023-12-31", "val": 19.89, "filed": "2024-02-14"},
        {"form": "20-F", "start": "2023-01-01", "end": "2023-12-31", "val": 19.89, "filed": "2025-03-05"},
        {"form": "20-F", "start": "2023-01-01", "end": "2023-12-31", "val": 19.89, "filed": "2026-02-25"},
    ]}}}}}
    r = fg.lpa_anual_sec(fatos)
    assert len(r) == 1 and r[0]["anuncio"] == "14/02/2024"   # a 1ª vez que o número saiu, não a 3ª


def test_lpa_anual_sec_combina_usd_e_eur_sem_misturar_o_mesmo_ano():
    fatos = {"facts": {"us-gaap": {"EarningsPerShareDiluted": {"units": {
        "USD/shares": [{"form": "10-K", "start": "2024-01-01", "end": "2024-12-31", "val": 5.0, "filed": "2025-02-01"}],
        "EUR/shares": [{"form": "20-F", "start": "2023-01-01", "end": "2023-12-31", "val": 20.0, "filed": "2024-02-01"}],
    }}}}}
    r = fg.lpa_anual_sec(fatos)
    assert r == [{"ano": 2023, "lpa": 20.0, "fim": "31/12/2023", "anuncio": "01/02/2024", "form": "20-F", "moeda": "EUR"},
                {"ano": 2024, "lpa": 5.0, "fim": "31/12/2024", "anuncio": "01/02/2025", "form": "10-K", "moeda": None}]


def test_cik_do_ticker_com_mapa_nao_baixa_lista_de_novo():
    """Com `mapa` já em mãos (ex. cacheado pelo app pra todos os tickers), não chama a SEC de novo
    - achou o bug de travamento: antes, cada ticker dos EUA digitado baixava a lista inteira
    (~10 mil empresas) de novo."""
    mapa = {"0": {"ticker": "MU", "cik_str": 723125, "title": "Micron Technology, Inc."}}
    assert fg.cik_do_ticker("mu", cab={}, mapa=mapa) == ("0000723125", "Micron Technology, Inc.")


def test_cik_do_ticker_sem_mapa_busca_na_sec(monkeypatch):
    chamadas = []

    def fake_tickers_sec(cab):
        chamadas.append(cab)
        return {"0": {"ticker": "AAPL", "cik_str": 320193, "title": "Apple Inc."}}

    monkeypatch.setattr(fg, "tickers_sec", fake_tickers_sec)
    assert fg.cik_do_ticker("AAPL", cab={"x": 1}) == ("0000320193", "Apple Inc.")
    assert len(chamadas) == 1


# ------------------------------------------------------------ outlook trimestral (EUA)
TEXTO_OUTLOOK_MU = (
    "Business Outlook The following table presents Micron's guidance for the first quarter of 2027: "
    "FQ1-27 GAAP (1) Outlook Non-GAAP (2) Outlook Revenue $61.5 billion ± $1.5 billion $61.5 billion "
    "± $1.5 billion Gross margin Approximately 85.95% Approximately 86.25% Operating expenses "
    "Approximately $2.31 billion Approximately $2.06 billion Diluted earnings per share $37.84 ± "
    "$1.00 $38.15 ± $1.00 Further information regarding Micron's business outlook"
)

TEXTO_OUTLOOK_NVDA = (
    "Outlook NVIDIA's outlook for the fourth quarter of fiscal 2027, which includes an additional "
    "week, is as follows: • Revenue is expected to be $130.0 billion, plus or minus 3%. NVIDIA is "
    "not assuming any Data Center compute revenue from China in its outlook. • GAAP and non-GAAP "
    "gross margins are expected to be between 71.0% and 72.0%. • GAAP and non-GAAP operating "
    "expenses are expected to be approximately $11.0 billion"
)

TEXTO_OUTLOOK_PANW = (
    "Financial Outlook Palo Alto Networks provides guidance based on current market conditions and "
    "expectations. For the fiscal second quarter 2027, we expect: • Next-Generation Security ARR "
    "of $10.20 billion to $10.22 billion. • Total revenue in the range of $3.530 billion to $3.550 "
    "billion, representing year-over-year growth of 36% to 37%. • Diluted non-GAAP net income per "
    "share in the range of $1.01 to $1.03, using 837 million to 842 million shares outstanding."
)


def test_outlook_trimestral_mu_faixa_com_mais_menos():
    r = fg.extrair_outlook_trimestral_eua(TEXTO_OUTLOOK_MU)
    assert r["periodo"] == "1T FY2027"
    assert r["receita_min"] == 60_000_000_000.0 and r["receita_max"] == 63_000_000_000.0
    assert r["margem_bruta"] == 85.95
    assert r["lpa_min"] == 36.84 and r["lpa_max"] == 38.84


def test_outlook_trimestral_nvda_percentual_e_faixa_de_margem_sem_lpa():
    """NVIDIA não dá guidance de LPA - tem que devolver receita/margem sem travar por falta de LPA."""
    r = fg.extrair_outlook_trimestral_eua(TEXTO_OUTLOOK_NVDA)
    assert r["periodo"] == "4T FY2027"
    assert r["receita_min"] == pytest.approx(126_100_000_000.0)
    assert r["receita_max"] == pytest.approx(133_900_000_000.0)
    assert r["margem_bruta"] == 71.5   # ponto médio de "between 71.0% and 72.0%"
    assert r["lpa_min"] is None and r["lpa_max"] is None


def test_outlook_trimestral_panw_faixa_com_to_e_rotulo_non_gaap():
    r = fg.extrair_outlook_trimestral_eua(TEXTO_OUTLOOK_PANW)
    assert r["periodo"] == "2T FY2027"
    assert r["receita_min"] == 3_530_000_000.0 and r["receita_max"] == 3_550_000_000.0
    assert r["lpa_min"] == 1.01 and r["lpa_max"] == 1.03


TEXTO_OUTLOOK_AMD = (
    "Current Outlook AMD's outlook statements are based on current expectations. The following "
    "statements are forward-looking and actual results could differ materially depending on market "
    "conditions and the factors set forth under “Cautionary Statement” below. For the fourth "
    "quarter of 2026, AMD expects revenue to be approximately $17 billion, plus or minus 3%. The "
    "mid-point of the revenue range represents year-over-year growth of approximately 66% and a "
    "sequential increase of approximately 27%. Non-GAAP gross margin is expected to be approximately "
    "55%. AMD Teleconference AMD will hold a conference call"
)


def test_outlook_trimestral_amd_rotulo_empresa_expects_sem_fiscal():
    """AMD usa 'For the Nth quarter of YEAR, AMD expects' - sem a palavra 'fiscal' e sem 'we expect',
    diferente de MU/NVDA/PANW; e a margem vem mais longe do rótulo ('is expected to be approximately')."""
    r = fg.extrair_outlook_trimestral_eua(TEXTO_OUTLOOK_AMD)
    assert r["periodo"] == "4T FY2026"
    assert r["receita_min"] == pytest.approx(16_490_000_000.0, rel=1e-6)
    assert r["receita_max"] == pytest.approx(17_510_000_000.0, rel=1e-6)
    assert r["margem_bruta"] == 55.0
    assert r["lpa_min"] is None and r["lpa_max"] is None


def test_outlook_trimestral_sem_guidance_devolve_none():
    assert fg.extrair_outlook_trimestral_eua("Nada de guidance aqui, só resultados do trimestre passado.") is None


TEXTO_OUTLOOK_ASML = (
    "Outlook ASML expects Q4 2026 total net sales between €14.2 billion and €15.2 billion, and a "
    "gross margin around 57% Full-year 2026 total net sales expected to be between €44 billion and "
    "€45 billion, with a gross margin around 56%"
)

TEXTO_OUTLOOK_ASML_CEO = (
    "CEO statement and outlook In the third quarter we reported a record total net sales. "
    "We expect fourth-quarter 2026 total net sales between €14.2 billion and €15.2 billion, with "
    "a gross margin around 57%. We expect R&D costs of around €1.2 billion. We expect total net "
    "sales for 2026 to be between €44 billion and €45 billion, with a gross margin around 56%."
)


def test_outlook_trimestral_asml_rotulo_q_abreviado_net_sales_e_between():
    """ASML usa 'EMPRESA expects QN AAAA' (sem 'quarter' por extenso), 'net sales' em vez de
    'Revenue', faixa em 'between X and Y' e valores em euro (símbolo € antes do número) - formatos
    que PANW/MU/NVDA/AMD não usam. Não dá guidance de LPA (só receita/margem)."""
    r = fg.extrair_outlook_trimestral_eua(TEXTO_OUTLOOK_ASML)
    assert r["periodo"] == "4T FY2026"
    assert r["receita_min"] == 14_200_000_000.0 and r["receita_max"] == 15_200_000_000.0
    assert r["margem_bruta"] == 57.0
    assert r["lpa_min"] is None and r["lpa_max"] is None


def test_outlook_trimestral_asml_no_ceo_statement_quarter_composto():
    """No corpo do release (CEO statement), a ASML também usa 'We expect fourth-quarter 2026'
    (composto com hífen, sem 'Q4' abreviado) - formato real do 6-K, diferente do resumo em bullet
    no topo do documento (coberto pelo teste acima)."""
    r = fg.extrair_outlook_trimestral_eua(TEXTO_OUTLOOK_ASML_CEO)
    assert r["periodo"] == "4T FY2026"
    assert r["receita_min"] == 14_200_000_000.0 and r["receita_max"] == 15_200_000_000.0
    assert r["margem_bruta"] == 57.0
    assert r["lpa_min"] is None and r["lpa_max"] is None


def test_extrair_outlook_marca_moeda_euro_quando_tem_simbolo():
    r = fg.extrair_outlook_trimestral_eua(TEXTO_OUTLOOK_ASML)
    assert r["moeda"] == "EUR"
    r2 = fg.extrair_outlook_trimestral_eua(TEXTO_OUTLOOK_MU)
    assert r2["moeda"] is None   # MU dá em dólar, sem símbolo - não marca nenhuma moeda (já é USD)


def test_converter_lpa_anual_para_usd_converte_pela_data_do_anuncio_nao_do_fim_do_ano():
    anos = [{"ano": 2023, "lpa": 20.09, "fim": "31/12/2023", "anuncio": "14/02/2024", "form": "20-F", "moeda": "EUR"},
            {"ano": 2024, "lpa": 7.0, "fim": "31/12/2024", "anuncio": "01/02/2025", "form": "10-K", "moeda": None}]
    datas_pedidas = []

    def fake_buscar_taxas(datas):
        datas_pedidas.extend(datas)
        return {dt.date(2024, 2, 14): (1.10, "14/02/2024")}   # câmbio na data do anúncio, não do fim do ano (31/12)

    r = fg.converter_lpa_anual_para_usd(anos, buscar_taxas=fake_buscar_taxas)
    assert datas_pedidas == [dt.date(2024, 2, 14)]
    assert r[0]["lpa"] == pytest.approx(20.09 * 1.10) and r[0]["lpa_eur"] == 20.09 and r[0]["moeda"] == "USD"
    assert r[0]["taxa_cambio"] == 1.10 and r[0]["taxa_cambio_data"] == "14/02/2024"
    assert r[1] == anos[1]   # intocado (já em dólar)


def test_converter_lpa_anual_para_usd_sem_cambio_descarta_o_ano():
    anos = [{"ano": 2023, "lpa": 20.09, "fim": "31/12/2023", "anuncio": "14/02/2024", "form": "20-F", "moeda": "EUR"}]
    r = fg.converter_lpa_anual_para_usd(anos, buscar_taxas=lambda datas: {})
    assert r == []


def test_converter_lpa_anual_para_usd_sem_nenhum_ano_em_euro_nao_chama_cambio():
    anos = [{"ano": 2024, "lpa": 7.0, "fim": "31/12/2024", "anuncio": "01/02/2025", "form": "10-K", "moeda": None}]
    chamou = []
    r = fg.converter_lpa_anual_para_usd(anos, buscar_taxas=lambda datas: chamou.append(datas) or {})
    assert r == anos and chamou == []


def test_taxa_cambio_historica_eur_usd_pega_fechamento_do_dia_ou_anterior(monkeypatch):
    """Fim de semana/feriado: usa o último pregão anterior à data pedida, nunca um valor futuro."""
    import sys
    import types

    import pandas as pd

    idx = pd.to_datetime(["2023-12-28", "2023-12-29", "2024-01-02"], utc=True)
    close = pd.Series([1.10, 1.105, 1.10], index=idx)

    class FakeTicker:
        def __init__(self, s):
            assert s == "EURUSD=X"

        def history(self, start=None, end=None, interval=None, auto_adjust=None):
            return pd.DataFrame({"Close": close})

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=FakeTicker))
    r = fg.taxa_cambio_historica_eur_usd([dt.date(2023, 12, 31)])   # domingo, sem pregão
    assert r[dt.date(2023, 12, 31)] == (1.105, "29/12/2023")   # último pregão antes do domingo


def test_converter_outlook_para_usd():
    dados = {"receita_min": 14.2e9, "receita_max": 15.2e9, "lpa_min": None, "lpa_max": None, "moeda": "EUR"}
    c = fg.converter_outlook_para_usd(dados, 1.08, "20/11/2026")
    assert c["moeda"] == "USD" and c["moeda_original"] == "EUR"
    assert c["receita_min"] == pytest.approx(14.2e9 * 1.08) and c["receita_max"] == pytest.approx(15.2e9 * 1.08)
    assert c["receita_min_eur"] == 14.2e9 and c["receita_max_eur"] == 15.2e9   # original preservado pra nota
    assert c["taxa_cambio"] == 1.08 and c["taxa_cambio_data"] == "20/11/2026"
    assert c["taxa_cambio_fonte"] == "Yahoo Finance (EURUSD=X)"


def test_converter_outlook_para_usd_nao_mexe_quando_ja_e_dolar():
    dados = {"receita_min": 1e9, "receita_max": 2e9, "moeda": None}
    assert fg.converter_outlook_para_usd(dados, 1.08, "20/11/2026") == dados


def test_atualizar_outlook_trimestral_eua_converte_euro_para_dolar(tmp_path, monkeypatch):
    """ASML dá o outlook em euro (símbolo €); o robô precisa converter pra dólar antes de gravar,
    senão a tela mostraria "US$ 14,20 bi" quando na verdade é € 14,20 bi (moeda errada). O câmbio
    usado é o da DATA DO ANÚNCIO (data do próprio documento, 14/10/2026), não o de hoje."""
    arq = tmp_path / "guidance_trimestral_eua.json"
    monkeypatch.setattr(fg, "ARQ_OUTLOOK_TRI", arq)
    datas_pedidas = []

    def fake_buscar_taxas(datas):
        datas_pedidas.extend(datas)
        return {dt.date(2026, 10, 14): (1.08, "14/10/2026")}

    tab = fg.atualizar_outlook_trimestral_eua(
        tickers=["ASML"], cabecalho=lambda: {"User-Agent": "x"},
        buscar_cik=lambda t, cab: ("0000937966", "ASML Holding N.V."),
        buscar_docs=lambda cik, cab: [{"form": "6-K", "data": "2026-10-14", "acc": "1", "cik": cik}],
        ler_anexo=lambda doc, cab: ("http://x", TEXTO_OUTLOOK_ASML_CEO),
        buscar_taxas=fake_buscar_taxas)
    assert datas_pedidas == [dt.date(2026, 10, 14)]   # câmbio da data do anúncio, não de hoje
    assert tab["ASML"]["receita_min"] == pytest.approx(14.2e9 * 1.08)
    assert tab["ASML"]["moeda"] == "USD" and tab["ASML"]["moeda_original"] == "EUR"
    assert tab["ASML"]["taxa_cambio"] == 1.08 and tab["ASML"]["taxa_cambio_data"] == "14/10/2026"


def test_atualizar_outlook_trimestral_eua_sem_cambio_nao_grava_em_euro(tmp_path, monkeypatch):
    """Câmbio indisponível na data do anúncio (Yahoo falhou): nunca grava o valor em euro como se já
    fosse dólar - melhor não gravar nada do que mostrar número errado."""
    arq = tmp_path / "guidance_trimestral_eua.json"
    monkeypatch.setattr(fg, "ARQ_OUTLOOK_TRI", arq)
    tab = fg.atualizar_outlook_trimestral_eua(
        tickers=["ASML"], cabecalho=lambda: {"User-Agent": "x"},
        buscar_cik=lambda t, cab: ("0000937966", "ASML Holding N.V."),
        buscar_docs=lambda cik, cab: [{"form": "6-K", "data": "2026-10-14", "acc": "1", "cik": cik}],
        ler_anexo=lambda doc, cab: ("http://x", TEXTO_OUTLOOK_ASML_CEO),
        buscar_taxas=lambda datas: {})
    assert "ASML" not in tab


def test_atualizar_outlook_trimestral_eua_nao_apaga_valor_bom_sem_achar_de_novo(tmp_path, monkeypatch):
    arq = tmp_path / "guidance_trimestral_eua.json"
    arq.write_text('{"MU": {"periodo": "4T FY2026"}}', encoding="utf-8")
    monkeypatch.setattr(fg, "ARQ_OUTLOOK_TRI", arq)
    tab = fg.atualizar_outlook_trimestral_eua(
        tickers=["MU"], cabecalho=lambda: {"User-Agent": "x"},
        buscar_cik=lambda t, cab: ("0000723125", "Micron"),
        buscar_docs=lambda cik, cab: [{"form": "8-K", "data": "2026-01-01", "acc": "1", "cik": cik}],
        ler_anexo=lambda doc, cab: ("http://x", "nada de outlook aqui"))
    assert tab["MU"] == {"periodo": "4T FY2026"}   # mantido: a tentativa não achou nada novo


def test_atualizar_outlook_trimestral_eua_grava_quando_acha(tmp_path, monkeypatch):
    arq = tmp_path / "guidance_trimestral_eua.json"
    monkeypatch.setattr(fg, "ARQ_OUTLOOK_TRI", arq)
    tab = fg.atualizar_outlook_trimestral_eua(
        tickers=["MU"], cabecalho=lambda: {"User-Agent": "x"},
        buscar_cik=lambda t, cab: ("0000723125", "Micron Technology, Inc."),
        buscar_docs=lambda cik, cab: [{"form": "8-K", "data": "2026-09-30", "acc": "1", "cik": cik}],
        ler_anexo=lambda doc, cab: ("http://x", TEXTO_OUTLOOK_MU))
    assert tab["MU"]["periodo"] == "1T FY2027"
    assert json.loads(arq.read_text(encoding="utf-8"))["MU"]["periodo"] == "1T FY2027"


def test_atualizar_outlook_trimestral_eua_inclui_travados_sem_guidance_anual(tmp_path, monkeypatch):
    """MU e AMD não têm guidance anual (ficam em queue_nao_validado.json) mas dão guidance
    trimestral - o robô precisa olhar os dois arquivos (cadastrados + travados), não só
    guidance_tickers.json, senão o card trimestral deles nunca apareceria sozinho."""
    arq_tickers = tmp_path / "guidance_tickers.json"
    arq_tickers.write_text('["AAPL"]', encoding="utf-8")
    arq_nao_validado = tmp_path / "queue_nao_validado.json"
    arq_nao_validado.write_text('{"MU": {"motivo": "sem guidance", "data": "20/11/2026"}}', encoding="utf-8")
    arq_outlook = tmp_path / "guidance_trimestral_eua.json"
    monkeypatch.setattr(fg, "ARQ_TICKERS", arq_tickers)
    monkeypatch.setattr(fg, "ARQ_NAO_VALIDADO", arq_nao_validado)
    monkeypatch.setattr(fg, "ARQ_OUTLOOK_TRI", arq_outlook)
    vistos = []

    def fake_buscar_cik(t, cab):
        vistos.append(t)
        return ("0000723125", "Micron Technology, Inc.") if t == "MU" else None

    tab = fg.atualizar_outlook_trimestral_eua(
        cabecalho=lambda: {"User-Agent": "x"}, buscar_cik=fake_buscar_cik,
        buscar_docs=lambda cik, cab: [{"form": "8-K", "data": "2026-09-30", "acc": "1", "cik": cik}],
        ler_anexo=lambda doc, cab: ("http://x", TEXTO_OUTLOOK_MU))
    assert set(vistos) == {"AAPL", "MU"}   # os dois arquivos foram combinados
    assert tab["MU"]["periodo"] == "1T FY2027"


def test_anexo_sec_identifica_exhibit_pelo_type_da_pagina_indice(monkeypatch):
    """NVIDIA (e outras) nomeiam o press release sem o padrão 'ex99' no nome do arquivo (ex.:
    'q3fy27pr.htm'); a leitura pelo nome falhava silenciosamente. Agora usa a coluna "Type" da
    página de índice da SEC, que identifica o exhibit certo independente do nome do arquivo."""
    index_html = """
    <tr class="evenRow">
        <td scope="row">2</td>
        <td scope="row">EX-99.1</td>
        <td scope="row"><a href="/Archives/edgar/data/1045810/000104581026000088/q3fy27pr.htm">q3fy27pr.htm</a></td>
        <td scope="row">EX-99.1</td>
        <td scope="row">348063</td>
    </tr>
    """

    class FakeResp:
        def __init__(self, text):
            self.text = text

        def json(self):
            return json.loads(self.text)

    def fake_get_sec(url, cab):
        if url.endswith("-index.htm"):
            return FakeResp(index_html)
        assert url.endswith("q3fy27pr.htm")
        return FakeResp("<html><body>guidance for the fourth quarter</body></html>")

    monkeypatch.setattr(fg, "_get_sec", fake_get_sec)
    doc = {"form": "8-K", "data": "2026-11-17", "acc": "0001045810-26-000088", "cik": "0001045810"}
    link, texto = fg.anexo_sec(doc, cab={"User-Agent": "x"})
    assert link.endswith("q3fy27pr.htm")
    assert "guidance for the fourth quarter" in texto


def test_anexo_sec_6k_sem_exhibit_99_usa_o_corpo_do_formulario(monkeypatch):
    """Emissores estrangeiros (ex. Novo Nordisk/NVO) às vezes não têm Exhibit 99 separado no 6-K -
    o comunicado vem direto no corpo do formulário. Sem esse fallback, anexo_sec devolvia None e a
    leitura falhava silenciosamente, igual ao caso da NVIDIA antes da correção por nome de arquivo."""
    index_html = """
    <tr class="evenRow">
        <td scope="row">1</td>
        <td scope="row">FORM 6-K</td>
        <td scope="row"><a href="/Archives/edgar/data/353278/000117184326007156/f6k_110526.htm">f6k_110526.htm</a></td>
        <td scope="row">6-K</td>
        <td scope="row">28026</td>
    </tr>
    """

    class FakeResp:
        def __init__(self, text):
            self.text = text

    def fake_get_sec(url, cab):
        if url.endswith("-index.htm"):
            return FakeResp(index_html)
        assert url.endswith("f6k_110526.htm")
        return FakeResp("<html><body>Q3 2026 financial results</body></html>")

    monkeypatch.setattr(fg, "_get_sec", fake_get_sec)
    doc = {"form": "6-K", "data": "2026-11-05", "acc": "0001171843-26-007156", "cik": "0000353278"}
    link, texto = fg.anexo_sec(doc, cab={"User-Agent": "x"})
    assert link.endswith("f6k_110526.htm")
    assert "Q3 2026 financial results" in texto


def test_anexo_sec_8k_sem_exhibit_99_nao_usa_o_corpo_como_fallback(monkeypatch):
    """O fallback pro corpo do formulário só vale pra 6-K: um 8-K sem Exhibit 99 não deve cair pro
    corpo do próprio 8-K (que normalmente é só o texto-padrão do item, não o press release)."""
    index_html = """
    <tr class="evenRow">
        <td scope="row">1</td>
        <td scope="row">FORM 8-K</td>
        <td scope="row"><a href="/Archives/edgar/data/1/000000000000001/form8k.htm">form8k.htm</a></td>
        <td scope="row">8-K</td>
        <td scope="row">1000</td>
    </tr>
    """

    class FakeResp:
        def __init__(self, text):
            self.text = text

        def json(self):
            return {"directory": {"item": [{"name": "form8k.htm"}]}}

    monkeypatch.setattr(fg, "_get_sec", lambda url, cab: FakeResp(index_html))
    doc = {"form": "8-K", "data": "2026-11-05", "acc": "0000000000-00-000001", "cik": "1"}
    assert fg.anexo_sec(doc, cab={"User-Agent": "x"}) is None
