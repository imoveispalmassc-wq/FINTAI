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


def test_acao_dos_eua_fica_desligada():
    item = planejar_ticker("AAPL", HOJE, None, set())
    assert item["acao"] == "nada" and "desligad" in item["motivo"]


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
