import datetime as dt
import json

import pytest

import utils.fetch_guidance as fg
from utils.fetch_guidance import Extracao, extrair_por_padroes, numero_br, planejar_ticker

HOJE = dt.date(2026, 11, 16)

FATO_BB_FEV = """BANCO DO BRASIL S.A. FATO RELEVANTE Divulgação de Projeções Corporativas 2026.
O Banco do Brasil informa as projeções corporativas para 2026: Lucro Líquido Ajustado entre
R$ 22 bilhões e R$ 26 bilhões. Margem Financeira Bruta: crescimento entre 4% e 8%.
O Conselho de Administração aprovou payout de 30% para o exercício de 2026."""

TABELA_BB_REVISADA = """Projeções Corporativas 2026 (R$ bilhões) Anterior Revisado
Lucro Líquido Ajustado 22 a 26 18 a 22  Custo do Crédito 53 a 58 65 a 70"""

RELEASE_SEM_GUIDANCE = "Divulgação de resultados do 3T26. Lucro líquido de R$ 3,9 bilhões no trimestre."


def test_numero_br():
    assert numero_br("18,5") == 18.5 and numero_br("1.234,5") == 1234.5
    assert numero_br("1.234") == 1234 and numero_br("18.5") == 18.5 and numero_br("22") == 22


def test_fato_relevante_com_faixa_unica_tem_confianca_alta():
    ex = extrair_por_padroes(FATO_BB_FEV, 2026)
    assert (ex.lucro_min, ex.lucro_max) == (22e9, 26e9)
    assert ex.ano == 2026 and ex.payout == pytest.approx(0.30)
    assert ex.confianca == "alta" and ex.candidatos == 1
    assert "22 bilhões" in ex.trecho


def test_tabela_com_anterior_e_revisado_fica_sem_confianca():
    ex = extrair_por_padroes(TABELA_BB_REVISADA, 2026)
    assert ex is not None and ex.confianca == "baixa" and ex.candidatos >= 1
    assert ex.lucro_min == 22e9            # a primeira faixa; por isso não pode ir direto para o app


def test_release_sem_faixa_nao_e_guidance():
    assert extrair_por_padroes(RELEASE_SEM_GUIDANCE, 2026) is None


def test_projecao_de_outro_ano_fica_sem_confianca():
    ex = extrair_por_padroes(FATO_BB_FEV.replace("2026", "2027"), 2026)
    assert ex.confianca == "baixa" and ex.ano == 2027


def test_valor_em_milhoes():
    ex = extrair_por_padroes("Guidance 2026: lucro líquido ajustado de R$ 800 milhões a R$ 950 milhões.", 2026)
    assert (ex.lucro_min, ex.lucro_max) == (800e6, 950e6) and ex.confianca == "alta"


# ------------------------------------------------------------ decisão (sem rede)
def _planejar(textos, anterior=None, claude=None, vistos=None):
    docs = [{"data": f"2026-0{9 - i}-01", "categoria": "Fato Relevante", "assunto": "Projeções",
             "link": f"https://cvm.example/doc{i}.pdf"} for i in range(len(textos))]
    paginas = {d["link"]: t for d, t in zip(docs, textos)}
    return planejar_ticker(
        "BBAS3", HOJE, anterior, set() if vistos is None else vistos,
        buscar_cnpj=lambda t, h: ("00.000.000/0001-91", "BANCO DO BRASIL S.A."),
        buscar_docs=lambda c, h: docs, ler_pdf=lambda link: (b"%PDF", paginas[link]),
        buscar_acoes=lambda t: 5.73e9, ler_com_claude=claude or (lambda p, t, a: None))


def test_confianca_alta_vai_direto_para_o_app():
    item = _planejar([FATO_BB_FEV])
    assert item["acao"] == "commit"
    n = item["novo"]
    assert (n["lucro_min"], n["lucro_max"], n["payout"], n["acoes"]) == (22e9, 26e9, 0.30, 5.73e9)
    assert n["fonte"].startswith("BANCO DO BRASIL S.A., Fato Relevante de ") and n["url"].startswith("https://")


def test_documento_mais_novo_sem_guidance_e_pulado():
    assert _planejar([RELEASE_SEM_GUIDANCE, FATO_BB_FEV])["acao"] == "commit"


def test_nunca_volta_para_documento_antigo_quando_o_novo_e_ambiguo():
    # o mais novo é a revisão (ambígua): não pode usar o fato de fevereiro, que está desatualizado
    item = _planejar([TABELA_BB_REVISADA, FATO_BB_FEV])
    assert item["acao"] == "erro" and item["novo"] is None


def test_ambiguo_lido_pela_api_do_claude_vai_para_revisao():
    lido = Extracao(lucro_min=18e9, lucro_max=22e9, ano=2026, trecho="Lucro Líquido Ajustado 22 a 26 18 a 22",
                    metodo="API do Claude", motivos=["lido pela API do Claude: precisa de revisão"])
    item = _planejar([TABELA_BB_REVISADA], claude=lambda p, t, a: lido)
    assert item["acao"] == "pr" and item["novo"]["lucro_min"] == 18e9
    assert item["novo"]["metodo"] == "API do Claude"


def test_documento_ja_tentado_nao_chama_a_api_de_novo():
    chamadas = []
    vistos = {"https://cvm.example/doc0.pdf"}
    item = _planejar([TABELA_BB_REVISADA], claude=lambda *a: chamadas.append(a), vistos=vistos)
    assert not chamadas and item["acao"] == "nada"


def test_mudanca_maior_que_50_por_cento_vai_para_revisao():
    anterior = {"lucro_min": 50e9, "lucro_max": 60e9, "acoes": 5.73e9, "payout": 0.3, "ano": 2026, "documento": "x"}
    item = _planejar([FATO_BB_FEV], anterior=anterior)
    assert item["acao"] == "pr" and "mudou" in item["motivo"]


def test_mesmo_documento_ja_aplicado_nao_muda_nada():
    anterior = {"lucro_min": 22e9, "lucro_max": 26e9, "acoes": 5.73e9, "documento": "https://cvm.example/doc0.pdf"}
    assert _planejar([FATO_BB_FEV], anterior=anterior)["acao"] == "nada"


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
