import datetime as dt
import json

import utils.divergencia as dv

HOJE = dt.date(2026, 11, 26)


# ------------------------------------------------------------ detectar
def test_detectar_sem_valor_anterior_nao_e_divergencia():
    assert dv.detectar(None, 2.10) is False
    assert dv.detectar(2.10, None) is False


def test_detectar_mesmo_valor_nao_e_divergencia():
    assert dv.detectar(2.10, 2.10) is False
    assert dv.detectar(2.1000001, 2.1000002) is False        # arredondamento, dentro da tolerância


def test_detectar_valor_diferente_e_divergencia():
    assert dv.detectar(2.10, 1.80) is True
    assert dv.detectar(0, 1) is True


def test_detectar_zero_para_zero_nao_e_divergencia():
    assert dv.detectar(0, 0) is False


def test_detectar_texto_nao_numerico_compara_igualdade():
    assert dv.detectar("sem dado", "sem dado") is False
    assert dv.detectar("sem dado", "pendente") is True


# ------------------------------------------------------------ abrir_issue_divergencia
def test_abrir_issue_sem_token_nao_chama_rede(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    chamadas = []
    resultado = dv.abrir_issue_divergencia(
        "BBAS3", "lpa_ttm", 2.18, 1.90, "RI, release 3T26", "https://ri.bb.com.br/x",
        "26/11/2026 10:00", "contábil", token=None, criar=lambda *a: chamadas.append(a))
    assert resultado is None and not chamadas


def test_abrir_issue_titulo_e_corpo_no_formato_pedido():
    capturado = {}

    def criar(titulo, corpo):
        capturado["titulo"], capturado["corpo"] = titulo, corpo
        return {"number": 99}

    r = dv.abrir_issue_divergencia("BBAS3", "lpa_ttm", 2.18, 1.90, "RI, release 3T26, página 4",
                                   "https://ri.bb.com.br/x", "26/11/2026 10:00", "contábil",
                                   token="tok", criar=criar)
    assert r == {"number": 99}
    assert capturado["titulo"] == "Divergência: BBAS3 - Salvo: 2.18 / Novo: 1.9"
    assert "RI, release 3T26, página 4" in capturado["corpo"]
    assert "https://ri.bb.com.br/x" in capturado["corpo"]
    assert "26/11/2026 10:00" in capturado["corpo"]
    assert "contábil" in capturado["corpo"]
    assert "4 travas" in capturado["corpo"]


def test_abrir_issue_falha_na_api_nao_levanta_excecao():
    def explode(titulo, corpo):
        raise RuntimeError("timeout")
    assert dv.abrir_issue_divergencia("BBAS3", "lpa_ttm", 2.18, 1.90, "RI", None,
                                      "26/11/2026 10:00", token="tok", criar=explode) is None


# ------------------------------------------------------------ revisar_divergencia (reaproveita avaliar_travas)
def test_revisar_divergencia_reaproveita_avaliar_travas(monkeypatch):
    """Não duplica a lógica das 4 travas: chama utils.fetch_guidance.avaliar_travas com os
    mesmos argumentos que o AUTOMÁTICO COM PROTEÇÃO já usa."""
    import utils.fetch_guidance as fg

    chamadas = []

    def avaliar_travas_fake(ticker, novo, referencia, texto, hoje, duvidas, buscar_mercado):
        chamadas.append((ticker, novo, referencia, hoje))
        return {"publica": True, "travas": [], "duvidas": [], "motivo": "passou nas 4 travas"}

    monkeypatch.setattr(fg, "avaliar_travas", avaliar_travas_fake)
    novo = {"lpa_min": 1.8, "lpa_max": 1.9}
    salvo = {"lpa_min": 2.1, "lpa_max": 2.2}
    resultado = dv.revisar_divergencia("BBAS3", novo, salvo, "texto do documento", HOJE)
    assert resultado["publica"] is True
    assert chamadas == [("BBAS3", novo, salvo, HOJE)]


# ------------------------------------------------------------ parsear_issue / revisar_issue_divergencia
CORPO_EXEMPLO = """**Ticker:** BBAS3
**Campo:** lpa_12m
**Base:** contábil
**Salvo:** 2.18
**Novo:** 1.9
**Fonte:** RI, release 3T26, página 4
**Link:** https://ri.bb.com.br/x
**Data/hora:** 26/11/2026 10:00

Um segundo workflow vai revisar..."""


def test_parsear_issue_le_todos_os_campos():
    campos = dv.parsear_issue(CORPO_EXEMPLO)
    assert campos == {"ticker": "BBAS3", "campo": "lpa_12m", "base": "contábil", "salvo": "2.18",
                      "novo": "1.9", "fonte": "RI, release 3T26, página 4",
                      "link": "https://ri.bb.com.br/x", "data_hora": "26/11/2026 10:00"}


def test_parsear_issue_sem_link_devolve_none():
    corpo = CORPO_EXEMPLO.replace("https://ri.bb.com.br/x", "sem link")
    assert dv.parsear_issue(corpo)["link"] is None


def test_parsear_issue_corpo_fora_do_formato_devolve_vazio():
    assert dv.parsear_issue("um texto qualquer, sem os campos esperados") == {}


def test_revisar_issue_divergencia_trava_sem_texto_do_documento(monkeypatch):
    """LIMITAÇÃO CONHECIDA: a trava "Número em 2 lugares" sempre falha neste fluxo (a Issue não
    carrega o texto do documento) - a divergência fica travada, nunca publica PR sozinha."""
    import utils.fetch_guidance as fg
    monkeypatch.setattr(fg, "mercado_yahoo", lambda t: {"preco": 20.0, "pl": 10.0})
    resultado = dv.revisar_issue_divergencia(CORPO_EXEMPLO, HOJE)
    assert resultado["campos"]["ticker"] == "BBAS3"
    assert resultado["decisao"]["publica"] is False
    nomes_travados = [t["nome"] for t in resultado["decisao"]["travas"] if not t["ok"]]
    assert "Número em 2 lugares" in nomes_travados


def test_revisar_issue_divergencia_corpo_invalido_trava_sem_travas_listadas():
    resultado = dv.revisar_issue_divergencia("corpo vazio", HOJE)
    assert resultado["decisao"]["publica"] is False
    assert "formato esperado" in resultado["decisao"]["motivo"]


# ------------------------------------------------------------ aplicar_correcao / CLI
def test_aplicar_correcao_grava_o_valor_confirmado(tmp_path):
    caminho = tmp_path / "biblioteca.json"
    dv.aplicar_correcao("bbas3", "lpa_12m", 1.9, caminho)
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    assert dados["BBAS3"]["lpa_12m"]["valor"] == 1.9


def test_cli_revisar_grava_json_de_saida(tmp_path):
    corpo = tmp_path / "corpo.md"
    corpo.write_text(CORPO_EXEMPLO, encoding="utf-8")
    saida = tmp_path / "revisao.json"
    assert dv.main(["revisar", "--corpo", str(corpo), "--saida", str(saida)]) == 0
    resultado = json.loads(saida.read_text(encoding="utf-8"))
    assert resultado["campos"]["ticker"] == "BBAS3"
    assert resultado["decisao"]["publica"] is False


def test_cli_aplicar_grava_no_caminho_pedido(tmp_path):
    caminho = tmp_path / "biblioteca.json"
    assert dv.main(["aplicar", "--ticker", "BBAS3", "--campo", "lpa_12m", "--valor", "1.9",
                   "--caminho", str(caminho)]) == 0
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    assert dados["BBAS3"]["lpa_12m"]["valor"] == 1.9
