import datetime as dt
import json

import utils.biblioteca as bib

HOJE = dt.date(2026, 11, 26)


# ------------------------------------------------------------ staleness
def test_registro_sem_data_hora_esta_desatualizado():
    assert bib.esta_desatualizado({"valor": 1.0}, HOJE) is True


def test_registro_recente_nao_esta_desatualizado():
    registro = {"valor": 1.0, "data_hora": "20/11/2026 10:00"}
    assert bib.esta_desatualizado(registro, HOJE) is False


def test_registro_velho_esta_desatualizado():
    registro = {"valor": 1.0, "data_hora": "01/01/2026 10:00"}         # mais de 120 dias antes de HOJE
    assert bib.esta_desatualizado(registro, HOJE) is True


def test_registro_com_data_invalida_esta_desatualizado():
    assert bib.esta_desatualizado({"valor": 1.0, "data_hora": "não é uma data"}, HOJE) is True


# ------------------------------------------------------------ buscar/salvar na biblioteca
def test_buscar_ticker_novo_devolve_none():
    assert bib.buscar_na_biblioteca("BBAS3", "lpa_12m", HOJE, dados={}) is None


def test_salvar_e_buscar_na_biblioteca(tmp_path):
    caminho = tmp_path / "biblioteca.json"
    bib.salvar_na_biblioteca("BBAS3", "lpa_12m", 2.18, "RI, release 3T26, página 4",
                             "20/11/2026 10:00", caminho=caminho, avisar_divergencia=False)
    registro = bib.buscar_na_biblioteca("BBAS3", "lpa_12m", HOJE, caminho=caminho)
    assert registro == {"valor": 2.18, "fonte": "RI, release 3T26, página 4", "data_hora": "20/11/2026 10:00"}
    # ticker é normalizado em caixa alta
    assert bib.buscar_na_biblioteca("bbas3", "lpa_12m", HOJE, caminho=caminho) == registro


def test_buscar_dado_desatualizado_devolve_none(tmp_path):
    caminho = tmp_path / "biblioteca.json"
    bib.salvar_na_biblioteca("BBAS3", "lpa_12m", 2.18, "RI", "01/01/2026 10:00",
                             caminho=caminho, avisar_divergencia=False)
    assert bib.buscar_na_biblioteca("BBAS3", "lpa_12m", HOJE, caminho=caminho) is None


def test_salvar_grava_contabil_e_ajustado_separados(tmp_path):
    caminho = tmp_path / "biblioteca.json"
    bib.salvar_na_biblioteca("MU", "lpa_12m", 2.84, "SEC 10-K", "20/11/2026 10:00",
                             valor_ajustado=3.10, caminho=caminho, avisar_divergencia=False)
    registro = bib.buscar_na_biblioteca("MU", "lpa_12m", HOJE, caminho=caminho)
    # REGRA TRAVADA: "valor" é sempre o contábil (o principal); "valor_ajustado" nunca é confundido com ele
    assert registro["valor"] == 2.84 and registro["valor_ajustado"] == 3.10


def test_salvar_grava_no_disco_no_formato_dos_outros_caches(tmp_path):
    caminho = tmp_path / "biblioteca.json"
    bib.salvar_na_biblioteca("BBAS3", "roe", 0.21, "RI", "20/11/2026 10:00",
                             caminho=caminho, avisar_divergencia=False)
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    assert dados == {"BBAS3": {"roe": {"valor": 0.21, "fonte": "RI", "data_hora": "20/11/2026 10:00"}}}


# ------------------------------------------------------------ divergência (Issue #48, item 9) acionada ao salvar
def test_salvar_valor_diferente_do_anterior_abre_issue_de_divergencia(tmp_path):
    caminho = tmp_path / "biblioteca.json"
    bib.salvar_na_biblioteca("BBAS3", "lpa_12m", 2.18, "RI 2T26", "10/08/2026 10:00",
                             caminho=caminho, avisar_divergencia=False)
    chamadas = []

    def abrir_issue_fake(**kw):
        chamadas.append(kw)
        return {"number": 123}

    resultado = bib.salvar_na_biblioteca("BBAS3", "lpa_12m", 1.90, "RI 3T26", "20/11/2026 10:00",
                                         caminho=caminho, abrir_issue=abrir_issue_fake)
    assert resultado["divergente"] is True and resultado["issue"] == {"number": 123}
    assert chamadas and chamadas[0]["salvo"] == 2.18 and chamadas[0]["novo"] == 1.90
    assert chamadas[0]["base"] == "contábil"


def test_salvar_mesmo_valor_nao_abre_issue_de_divergencia(tmp_path):
    caminho = tmp_path / "biblioteca.json"
    bib.salvar_na_biblioteca("BBAS3", "lpa_12m", 2.18, "RI 2T26", "10/08/2026 10:00",
                             caminho=caminho, avisar_divergencia=False)
    chamadas = []
    resultado = bib.salvar_na_biblioteca("BBAS3", "lpa_12m", 2.18, "RI 3T26 (confirmado)", "20/11/2026 10:00",
                                         caminho=caminho, abrir_issue=lambda **kw: chamadas.append(kw))
    assert resultado["divergente"] is False and not chamadas


def test_salvar_falha_ao_abrir_issue_nao_derruba_a_gravacao(tmp_path):
    caminho = tmp_path / "biblioteca.json"
    bib.salvar_na_biblioteca("BBAS3", "lpa_12m", 2.18, "RI 2T26", "10/08/2026 10:00",
                             caminho=caminho, avisar_divergencia=False)

    def explode(**kw):
        raise RuntimeError("sem GITHUB_TOKEN")

    resultado = bib.salvar_na_biblioteca("BBAS3", "lpa_12m", 1.90, "RI 3T26", "20/11/2026 10:00",
                                         caminho=caminho, abrir_issue=explode)
    assert resultado["divergente"] is True and resultado["issue"] is None
    # o dado novo foi salvo mesmo com a issue falhando
    assert bib.buscar_na_biblioteca("BBAS3", "lpa_12m", HOJE, caminho=caminho)["valor"] == 1.90


def test_primeiro_valor_salvo_nunca_e_divergencia(tmp_path):
    caminho = tmp_path / "biblioteca.json"
    chamadas = []
    resultado = bib.salvar_na_biblioteca("BBAS3", "lpa_12m", 2.18, "RI 2T26", "10/08/2026 10:00",
                                         caminho=caminho, abrir_issue=lambda **kw: chamadas.append(kw))
    assert resultado["divergente"] is False and not chamadas


# ------------------------------------------------------------ Perplexity (PROMPT PADRÃO) - sempre com mocks
def test_montar_prompt_usa_o_texto_padrao_literal_da_issue():
    prompt = bib.montar_prompt_perplexity("BBAS3", "3T26")
    assert prompt.startswith("Ação: BBAS3 / Período: 3T26 / Comparar com trimestre anterior e mesmo tri ano anterior")
    assert "Trazer Contábil e Ajustado em colunas separadas." in prompt
    assert "SE FOR BANCO" in prompt and "SE NÃO FOR BANCO" in prompt
    assert "Fonte / Página" in prompt


def test_pesquisar_via_perplexity_sem_chave_nao_chama_rede(monkeypatch):
    monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
    assert bib.pesquisar_via_perplexity("BBAS3", "3T26") is None


def test_pesquisar_via_perplexity_payload_e_resposta_da_agent_api(monkeypatch):
    """MOCK CLARAMENTE DOCUMENTADO: testa a função `chamar` REAL (não via chamar= injetado) -
    monkeypatcha requests.post, nunca bate na rede de verdade - pra confirmar que o payload da
    Agent API ({"effort": "fast", "input": ...}, endpoint /v1/agent) e o parsing da resposta nova
    (output -> item type "message" -> content[].text) estão certos (27/11/2026, migração do Sonar
    Chat Completions descontinuado)."""
    import requests

    monkeypatch.setenv("PERPLEXITY_API_KEY", "chave-de-teste")
    capturado = {}

    class RespostaFake:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "id": "resp_teste", "object": "response", "status": "completed",
                "output": [
                    {"type": "search_results", "results": []},
                    {"id": "msg_teste", "type": "message", "role": "assistant", "status": "completed",
                     "content": [{"type": "output_text", "text": "LPA | 0,21 | 0,23 | RI, release 3T26, página 4 (SIMULADO)",
                                 "annotations": []}]},
                ],
            }

    def post_fake(url, timeout=None, headers=None, json=None):
        capturado.update(url=url, headers=headers, json=json)
        return RespostaFake()

    monkeypatch.setattr(requests, "post", post_fake)
    resultado = bib.pesquisar_via_perplexity("BBAS3", "3T26")

    assert capturado["url"] == "https://api.perplexity.ai/v1/agent"
    assert capturado["json"] == {"effort": bib.PERPLEXITY_EFFORT, "input": bib.montar_prompt_perplexity("BBAS3", "3T26")}
    assert capturado["headers"]["Authorization"] == "Bearer chave-de-teste"
    assert resultado["resposta"] == "LPA | 0,21 | 0,23 | RI, release 3T26, página 4 (SIMULADO)"


def test_pesquisar_via_perplexity_erro_http_loga_corpo_e_devolve_none(monkeypatch, caplog):
    """O 403 real descoberto em produção (chat_completions_not_available) só apareceu porque o
    corpo da resposta de erro é logado - confere que isso continua acontecendo."""
    import requests

    monkeypatch.setenv("PERPLEXITY_API_KEY", "chave-de-teste")

    class RespostaErro:
        status_code = 403
        text = '{"error":{"message":"Sonar is now the Agent API.","code":403}}'

        def raise_for_status(self):
            raise requests.exceptions.HTTPError("403 Client Error: Forbidden", response=self)

    monkeypatch.setattr(requests, "post", lambda *a, **kw: RespostaErro())
    with caplog.at_level("WARNING"):
        assert bib.pesquisar_via_perplexity("BBAS3", "3T26") is None
    assert "Sonar is now the Agent API" in caplog.text


def test_pesquisar_via_perplexity_output_sem_mensagem_devolve_none(monkeypatch):
    import requests

    monkeypatch.setenv("PERPLEXITY_API_KEY", "chave-de-teste")

    class RespostaSemTexto:
        def raise_for_status(self):
            pass

        def json(self):
            return {"id": "resp_teste", "output": [{"type": "search_results", "results": []}]}

    monkeypatch.setattr(requests, "post", lambda *a, **kw: RespostaSemTexto())
    assert bib.pesquisar_via_perplexity("BBAS3", "3T26") is None


def test_pesquisar_via_perplexity_usa_o_prompt_padrao_mock():
    """MOCK CLARAMENTE DOCUMENTADO: simula a resposta da Perplexity sem chamar a rede de verdade
    (api.perplexity.ai não é alcançável neste ambiente de desenvolvimento - ver utils/biblioteca.py)."""
    capturado = {}

    def chamar_mock(prompt):
        capturado["prompt"] = prompt
        return ("Indicador | Tri Atual Contábil | Tri Atual Ajustado | ... | Fonte / Página\n"
                "LPA | 0,21 | 0,23 | ... | RI, release 3T26, página 4 (SIMULADO)")

    resultado = bib.pesquisar_via_perplexity("BBAS3", "3T26", chamar=chamar_mock)
    assert resultado is not None
    assert capturado["prompt"] == bib.montar_prompt_perplexity("BBAS3", "3T26")
    assert "SIMULADO" in resultado["resposta"]


def test_pesquisar_via_perplexity_chamada_sem_resposta_devolve_none():
    assert bib.pesquisar_via_perplexity("BBAS3", "3T26", chamar=lambda p: None) is None


# ------------------------------------------------------------ confirmação pela API do Claude
def test_confirmar_com_claude_sem_chave_nao_chama_rede(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    resposta = {"resposta": "LPA contábil 0,21 (RI, página 4)"}
    assert bib.confirmar_com_claude(resposta, "BBAS3", "lpa_12m") is None


def test_confirmar_com_claude_confirma_valor_com_trecho_na_resposta():
    """MOCK CLARAMENTE DOCUMENTADO: simula a resposta em JSON da API do Claude (mesmo esquema de
    ESQUEMA_CONFIRMACAO_CLAUDE), sem chamar a API de verdade."""
    texto = "LPA | 0,21 | 0,23 | RI, release 3T26, página 4"
    resposta_perplexity = {"resposta": texto}
    bruto = ('{"achou": true, "valor_contabil": 0.21, "valor_ajustado": 0.23, '
            '"fonte": "RI, release 3T26, página 4", "link": "https://ri.bb.com.br/release-3t26", '
            '"pagina": "página 4", "trecho": "LPA | 0,21 | 0,23 | RI, release 3T26, página 4"}')
    confirmado = bib.confirmar_com_claude(resposta_perplexity, "BBAS3", "lpa_12m", chamar=lambda i: bruto)
    assert confirmado == {"valor": 0.21, "valor_ajustado": 0.23, "fonte": "RI, release 3T26, página 4",
                          "link": "https://ri.bb.com.br/release-3t26", "pagina": "página 4", "trecho": texto}


def test_confirmar_com_claude_sem_link_nao_confirma():
    # REGRA TRAVADA (27/11/2026): sem link da fonte oficial, nunca confirma - mesmo com achou=true
    # e um valor_contabil presente (número sem link não é confiável o bastante pra salvar).
    bruto = ('{"achou": true, "valor_contabil": 0.21, "valor_ajustado": null, "fonte": "RI", '
            '"link": "", "pagina": "página 4", "trecho": "LPA 0,21 (RI, página 4)"}')
    assert bib.confirmar_com_claude({"resposta": "LPA 0,21 (RI, página 4)"}, "BBAS3", "lpa_12m",
                                    chamar=lambda i: bruto) is None


def test_confirmar_com_claude_sem_pagina_nao_confirma():
    bruto = ('{"achou": true, "valor_contabil": 0.21, "valor_ajustado": null, "fonte": "RI", '
            '"link": "https://ri.bb.com.br/release", "pagina": "", "trecho": "LPA 0,21 (RI)"}')
    assert bib.confirmar_com_claude({"resposta": "LPA 0,21 (RI)"}, "BBAS3", "lpa_12m",
                                    chamar=lambda i: bruto) is None


def test_confirmar_com_claude_nao_confirmado_devolve_none():
    bruto = '{"achou": false, "valor_contabil": null, "valor_ajustado": null, "fonte": "", "trecho": ""}'
    assert bib.confirmar_com_claude({"resposta": "nada aqui"}, "BBAS3", "lpa_12m", chamar=lambda i: bruto) is None


def test_confirmar_com_claude_trecho_inventado_fora_da_resposta_e_descartado():
    """O trecho devolvido pela API tem de existir na resposta da Perplexity - senão pode ter sido
    inventado (mesma regra de _confere já usada no guidance automático)."""
    bruto = ('{"achou": true, "valor_contabil": 9.99, "valor_ajustado": null, "fonte": "RI", '
            '"trecho": "um trecho que nao existe na resposta original de verdade nenhuma"}')
    confirmado = bib.confirmar_com_claude({"resposta": "LPA 0,21 (RI, página 4)"}, "BBAS3", "lpa_12m",
                                          chamar=lambda i: bruto)
    assert confirmado is None


def test_confirmar_com_claude_resposta_fora_do_formato_json_devolve_none():
    assert bib.confirmar_com_claude({"resposta": "x"}, "BBAS3", "lpa_12m", chamar=lambda i: "isso não é JSON") is None


# ------------------------------------------------------------ obter() - ponto de entrada único
def test_obter_usa_biblioteca_quando_ja_tem_dado_fresco(tmp_path):
    caminho = tmp_path / "biblioteca.json"
    bib.salvar_na_biblioteca("BBAS3", "lpa_12m", 2.18, "RI", "20/11/2026 10:00",
                             caminho=caminho, avisar_divergencia=False)
    chamadas_externas = []
    resultado = bib.obter("BBAS3", "lpa_12m", "3T26", HOJE, caminho=caminho,
                          buscar_externo=lambda t, c: chamadas_externas.append((t, c)))
    assert resultado["valor"] == 2.18 and not chamadas_externas


def test_obter_sem_dado_usa_busca_externa_e_salva(tmp_path):
    caminho = tmp_path / "biblioteca.json"

    def buscar_externo(ticker, campo):
        return {"valor": 2.18, "fonte": "SEC 10-Q", "link": "https://sec.gov/x"}

    resultado = bib.obter("MU", "lpa_12m", "1T27", HOJE, caminho=caminho, buscar_externo=buscar_externo)
    assert resultado["valor"] == 2.18
    salvo = json.loads(caminho.read_text(encoding="utf-8"))
    assert salvo["MU"]["lpa_12m"]["valor"] == 2.18


def test_obter_fallback_para_perplexity_quando_busca_externa_falha_igual_yahoo_quebrado(tmp_path):
    """"Se o Yahoo quebrar, cair pra Perplexity antes de mostrar Sem dado" - aqui simulado com
    buscar_externo levantando exceção (mesmo efeito de uma falha de rede/parsing do Yahoo)."""
    caminho = tmp_path / "biblioteca.json"

    def buscar_externo_quebrado(ticker, campo):
        raise RuntimeError("Yahoo: falha de rede simulada")

    chamar_perplexity = lambda p: "LPA | 0,21 | 0,23 | RI, release 3T26, página 4 (SIMULADO)"
    chamar_claude = lambda i: ('{"achou": true, "valor_contabil": 0.21, "valor_ajustado": 0.23, '
                              '"fonte": "RI, release 3T26, página 4", "link": "https://ri.bb.com.br/release-3t26", '
                              '"pagina": "página 4", '
                              '"trecho": "LPA | 0,21 | 0,23 | RI, release 3T26, página 4 (SIMULADO)"}')
    resultado = bib.obter("BBAS3", "lpa_12m", "3T26", HOJE, caminho=caminho,
                         buscar_externo=buscar_externo_quebrado,
                         chamar_perplexity=chamar_perplexity, chamar_claude=chamar_claude)
    assert resultado["valor"] == 0.21 and resultado["valor_ajustado"] == 0.23
    assert resultado["link"] == "https://ri.bb.com.br/release-3t26" and resultado["pagina"] == "página 4"


def test_obter_sem_nada_disponivel_devolve_none_nunca_inventa(tmp_path):
    caminho = tmp_path / "biblioteca.json"
    resultado = bib.obter("ZZZZ", "lpa_12m", "3T26", HOJE, caminho=caminho,
                         buscar_externo=lambda t, c: None, chamar_perplexity=lambda p: None)
    assert resultado is None


# ------------------------------------------------------------ workflow: atualizar_tickers / CLI
def test_periodo_atual_pede_o_trimestre_anterior_ao_calendario_de_hoje():
    # BUG CORRIGIDO (27/11/2026): pede o ÚLTIMO trimestre com chance real de já ter sido
    # divulgado, não o trimestre calendário de hoje (esse quase nunca foi divulgado ainda -
    # achado pedindo BBAS3 de verdade: 27/11/2026 cai no 4T26, mas o 4T26 do Banco do Brasil só
    # sai em 10/02/2027 - a Perplexity respondia "Não divulgado" pro 4T26).
    assert bib._periodo_atual(dt.date(2026, 11, 26)) == "3T26"
    assert bib._periodo_atual(dt.date(2026, 10, 1)) == "3T26"      # início do 4T26 -> ainda pede 3T26
    assert bib._periodo_atual(dt.date(2026, 2, 1)) == "4T25"       # início do 1T26 -> vira o ano
    assert bib._periodo_atual(dt.date(2026, 4, 15)) == "1T26"      # início do 2T26 -> pede 1T26


def test_atualizar_tickers_processa_cada_ticker_e_registra_resultado(tmp_path):
    caminho = tmp_path / "biblioteca.json"
    chamar_perplexity = lambda p: "LPA | 0,21 | 0,23 | RI, release 3T26, página 4 (SIMULADO)"
    chamar_claude = lambda i: ('{"achou": true, "valor_contabil": 0.21, "valor_ajustado": 0.23, '
                              '"fonte": "RI, release 3T26, página 4", "link": "https://ri.bb.com.br/release-3t26", '
                              '"pagina": "página 4", '
                              '"trecho": "LPA | 0,21 | 0,23 | RI, release 3T26, página 4 (SIMULADO)"}')
    resultados = bib.atualizar_tickers(["BBAS3", "VALE3"], "lpa_atual", HOJE, caminho=caminho,
                                       chamar_perplexity=chamar_perplexity, chamar_claude=chamar_claude)
    assert [r["ticker"] for r in resultados] == ["BBAS3", "VALE3"]
    assert all(r["achado"] and r["valor"] == 0.21 for r in resultados)


def test_atualizar_tickers_um_erro_nao_derruba_os_outros(tmp_path):
    caminho = tmp_path / "biblioteca.json"

    def buscar_externo(ticker, campo):
        if ticker == "QUEBRA":
            raise RuntimeError("falha simulada")
        return None

    resultados = bib.atualizar_tickers(["QUEBRA", "BBAS3"], "lpa_atual", HOJE, caminho=caminho,
                                       buscar_externo=buscar_externo, chamar_perplexity=lambda p: None)
    assert [r["ticker"] for r in resultados] == ["QUEBRA", "BBAS3"]
    assert all(not r["achado"] for r in resultados)


def test_cli_atualizar_le_tickers_de_um_arquivo_json(tmp_path, monkeypatch):
    tickers_json = tmp_path / "tickers.json"
    tickers_json.write_text('["BBAS3"]', encoding="utf-8")
    monkeypatch.setattr(bib, "ARQ_BIBLIOTECA", tmp_path / "biblioteca.json")
    monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
    assert bib.main(["atualizar", "--tickers", str(tickers_json), "--campo", "lpa_atual"]) == 0
