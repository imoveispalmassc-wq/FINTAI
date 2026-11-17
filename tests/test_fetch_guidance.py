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


# ------------------------------------------------------------ decisão (sem rede)
def _planejar(docs_datados, anterior=None, claude=None, vistos=None):
    """docs_datados: [(data ISO, texto)], do mais novo para o mais antigo."""
    docs = [{"data": data, "categoria": "Fato Relevante", "assunto": "Projeções",
             "link": f"https://cvm.example/doc{i}.pdf"} for i, (data, _) in enumerate(docs_datados)]
    paginas = {d["link"]: texto for d, (_, texto) in zip(docs, docs_datados)}
    return planejar_ticker(
        "BBAS3", HOJE, anterior, set() if vistos is None else vistos,
        buscar_cnpj=lambda t, h: ("00.000.000/0001-91", "BANCO DO BRASIL S.A."),
        buscar_docs=lambda c, h: docs, ler_pdf=lambda link: (b"%PDF", paginas[link]),
        buscar_acoes=lambda t: 5.73e9, ler_com_claude=claude or (lambda *args: None))


NOV, MAI, FEV = "2026-11-11", "2026-05-13", "2026-02-12"
GUIDANCE_NOV = {"lucro_min": 9e9, "lucro_max": 11e9, "acoes": 5.73e9, "payout": 0.25, "ano": 2026,
                "data": "11/11/2026", "documento": "https://cvm.example/release-3t26.pdf"}


def test_primeira_gravacao_do_ticker_sempre_abre_pr_mesmo_com_confianca_alta():
    item = _planejar([(NOV, FATO_BB_NOV)])          # documento recente, faixa única, sem guidance salvo
    assert item["acao"] == "pr" and "primeira gravação" in item["motivo"]
    n = item["novo"]
    assert (n["lucro_min"], n["lucro_max"], n["payout"], n["acoes"]) == (9e9, 11e9, 0.25, 5.73e9)
    assert n["data"] == "11/11/2026"
    assert n["fonte"] == "BANCO DO BRASIL S.A., Fato Relevante de 11/11/2026 (CVM)" and n["url"].startswith("https://")


GUIDANCE_APROVADO = {"lucro_min": 9.5e9, "lucro_max": 11.5e9, "acoes": 5.73e9, "payout": 0.25, "ano": 2026,
                     "data": "15/08/2026", "documento": "https://cvm.example/antigo.pdf"}


def test_depois_de_aprovado_confianca_alta_e_variacao_pequena_vai_direto():
    item = _planejar([(NOV, FATO_BB_NOV)], anterior=GUIDANCE_APROVADO)     # LPA de 10,5 para 10: -5%
    assert item["acao"] == "commit" and "primeira" not in item["motivo"]


def test_documento_mais_novo_sem_guidance_e_pulado():
    item = _planejar([("2026-11-14", RELEASE_SEM_GUIDANCE), (NOV, FATO_BB_NOV)], anterior=GUIDANCE_APROVADO)
    assert item["acao"] == "commit" and item["novo"]["lucro_min"] == 9e9


def test_faixa_de_maio_e_descartada_quando_o_app_ja_tem_a_de_novembro():
    # o robô só achou o documento de maio (18 a 22): é mais antigo que o guidance atual, descarta
    item = _planejar([(MAI, FATO_BB_MAI), (FEV, FATO_BB_FEV)], anterior=GUIDANCE_NOV)
    assert item["acao"] == "nada" and item["novo"] is None and "mais antigo" in item["motivo"]


def test_faixa_de_maio_sem_guidance_no_app_nunca_e_publicada_sozinha():
    # primeira execução, sem guidance salvo: documento com mais de 120 dias vai para revisão
    item = _planejar([(MAI, FATO_BB_MAI)])
    assert item["acao"] == "pr" and "120 dias" in item["motivo"]
    assert item["novo"]["lucro_min"] == 18e9      # aparece no PR, para você recusar


def test_nunca_volta_para_documento_antigo_quando_o_novo_e_ambiguo():
    # o mais novo (novembro) traz anterior e revisada; não pode cair para o fato de maio ou fevereiro
    item = _planejar([(NOV, TABELA_BB_NOV), (MAI, FATO_BB_MAI), (FEV, FATO_BB_FEV)])
    assert item["acao"] == "erro" and item["novo"] is None


def test_ambiguo_lido_pela_api_do_claude_vai_para_revisao():
    lido = Extracao(lucro_min=9e9, lucro_max=11e9, payout=0.25, ano=2026,
                    trecho="Lucro Líquido Ajustado 18 a 22 9 a 11", metodo="API do Claude",
                    motivos=["lido pela API do Claude: precisa de revisão"])
    item = _planejar([(NOV, TABELA_BB_NOV)], claude=lambda *args: lido)
    assert item["acao"] == "pr" and (item["novo"]["lucro_min"], item["novo"]["lucro_max"]) == (9e9, 11e9)
    assert item["novo"]["metodo"] == "API do Claude"


def test_documento_ja_tentado_nao_chama_a_api_de_novo():
    chamadas = []
    item = _planejar([(NOV, TABELA_BB_NOV)], claude=lambda *a: chamadas.append(a),
                     vistos={"https://cvm.example/doc0.pdf"})
    assert not chamadas and item["acao"] == "nada"


GUIDANCE_MAI = {"lucro_min": 18e9, "lucro_max": 22e9, "acoes": 5.73e9, "payout": 0.30, "ano": 2026,
                "data": "13/05/2026", "documento": "x"}


def test_corte_de_exatamente_50_por_cento_vai_para_revisao_mesmo_com_confianca_alta():
    # o corte real do BB: de 18 a 22 (maio) para 9 a 11 (novembro), LPA de 20 para 10 bi / ações
    item = _planejar([(NOV, FATO_BB_NOV)], anterior=GUIDANCE_MAI)
    assert item["acao"] == "pr" and "mudou 50%" in item["motivo"]
    assert (item["novo"]["lucro_min"], item["novo"]["lucro_max"]) == (9e9, 11e9)


def test_corte_maior_que_50_por_cento_vai_para_revisao():
    item = _planejar([(NOV, FATO_BB_NOV.replace("9 bilhões", "8 bilhões"))], anterior=GUIDANCE_MAI)
    assert item["acao"] == "pr" and "mudou" in item["motivo"]


def test_mudanca_menor_que_50_por_cento_com_confianca_alta_vai_direto():
    anterior = {**GUIDANCE_MAI, "lucro_min": 12e9, "lucro_max": 14e9}     # LPA de 13 para 10: -23%
    assert _planejar([(NOV, FATO_BB_NOV)], anterior=anterior)["acao"] == "commit"


def test_mesmo_documento_ja_aplicado_nao_muda_nada():
    anterior = {**GUIDANCE_NOV, "documento": "https://cvm.example/doc0.pdf"}
    assert _planejar([(NOV, FATO_BB_NOV)], anterior=anterior)["acao"] == "nada"


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


def test_planejar_eua_primeira_gravacao_vai_para_pr():
    doc = {"form": "8-K", "data": "2026-11-03", "acc": "0000007084-26-000054", "cik": "0000007084"}
    item = fg.planejar_ticker_eua("ADM", HOJE, None, cabecalho=lambda: {"User-Agent": "x"},
                                  buscar_cik=lambda t, c: ("0000007084", "ARCHER-DANIELS-MIDLAND CO"),
                                  buscar_docs=lambda cik, c: [doc], ler_anexo=lambda d, c: ("https://sec/ex991.htm", ADM_TXT))
    assert item["acao"] == "pr" and item["novo"]["lpa_min"] == 5.50 and item["novo"]["data"] == "03/11/2026"
    assert "SEC" in item["novo"]["fonte"]


def test_aplicar_grava_so_o_tipo_pedido(tmp_path, monkeypatch):
    monkeypatch.setattr(fg, "ARQ_AUTO", tmp_path / "auto.json")
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
# 4T25 ajustado 0,87 e 3T26 ajustado 1,77 são os divulgados pela ADM; 1T26 e 2T26 (1,11 e 1,45) são de teste,
# escolhidos para que 2026 até o 3T some 4,33, como no release do 3T26.
ADM_AJ = {"31/12/2025": 0.87, "31/03/2026": 1.11, "30/06/2026": 1.45, "30/09/2026": 1.77}


def _aj(valores):
    return {fim: {"lpa": v, "fonte": "SEC Form 8-K Exhibit 99.1, LPA Ajustado", "data": "x", "url": ""} for fim, v in valores.items()}


def test_contabil_ajustado_da_adm_soma_5_20_e_nao_5_12():
    gaap = fg.lpa_ttm_sec(_fatos_adm(), dt.date(2026, 11, 17))
    assert gaap["lpa_12m"] == pytest.approx(5.12)                          # GAAP
    c = fg.contabil_ajustado(gaap, _aj(ADM_AJ))
    assert c["lpa_12m"] == pytest.approx(5.20) and c["base"] == "ajustado" and c["trimestres_gaap"] == 0
    assert c["fonte"] == "SEC 8-K Exhibit 99.1, LPA Ajustado"
    assert [t["tipo"] for t in c["trimestres"]] == ["ajustado"] * 4
    # o LPA ajustado do trimestre sai do press release, sem confundir com o acumulado, o ano ou a projeção
    q3 = ("ADM Reports Third Quarter 2026 Results. Third quarter adjusted EPS of $1.77; year-to-date adjusted EPS "
          "of $4.33. The Company now expects 2026 adjusted EPS of approximately $5.50 to $5.80.")
    q4 = "Fourth quarter adjusted EPS of $0.87, down 24%. Full year adjusted EPS of $3.43. 2026 adjusted EPS guidance $3.60 to $4.25."
    assert fg.extrair_eps_ajustado_trimestre(q3) == 1.77 and fg.extrair_eps_ajustado_trimestre(q4) == 0.87


def test_falta_ajustado_em_um_trimestre_usa_gaap_so_nele_e_marca_no_card():
    import pathlib
    from tela.dados import contabil_12m
    gaap = fg.lpa_ttm_sec(_fatos_adm(), dt.date(2026, 11, 17))
    sem_1t = {k: v for k, v in ADM_AJ.items() if k != "31/03/2026"}
    c = fg.contabil_ajustado(gaap, _aj(sem_1t))
    assert [t["tipo"] for t in c["trimestres"]] == ["ajustado", "GAAP", "ajustado", "ajustado"]
    assert c["lpa_12m"] == pytest.approx(0.87 + 1.07 + 1.45 + 1.77)        # 1T26 pelo GAAP (1,07)
    assert c["fonte"] == "SEC 8-K Exhibit 99.1, LPA Ajustado (1 trimestre GAAP por falta de Ajustado)"
    lpa, fonte, _ = contabil_12m("ADM", 5.12, {"ADM": c})
    assert lpa == pytest.approx(5.16) and "1 trimestre GAAP por falta de Ajustado" in fonte
    js = pathlib.Path(fg.__file__).resolve().parent.parent.joinpath("tela", "detalhe.js").read_text(encoding="utf-8")
    assert "GAAP por falta de Ajustado" in js and "Contábil Ajustado 12 meses" in js
