"""`app.py` roda código de script no nível do módulo (monta a página Streamlit de verdade) e não
pode ser importado direto num teste (ver tests/test_app_reload.py, mesmo motivo) - por isso a
função testada aqui é extraída do próprio texto do arquivo (`ast`) e executada isolada, só como
código Python puro (ela não chama nada externo: só lê chaves de dict)."""
import ast
from pathlib import Path

APP = Path(__file__).parent.parent / "app.py"


def _carregar_funcao(nome: str):
    arvore = ast.parse(APP.read_text(encoding="utf-8"))
    for no in arvore.body:
        if isinstance(no, ast.FunctionDef) and no.name == nome:
            modulo = ast.Module(body=[no], type_ignores=[])
            ns = {}
            exec(compile(modulo, str(APP), "exec"), ns)
            return ns[nome]
    raise AssertionError(f"não achei {nome} em app.py")


_pontos_lpa_grafico = _carregar_funcao("_pontos_lpa_grafico")
_pontos_trimestres_ttm = _carregar_funcao("_pontos_trimestres_ttm")


def _dados(**over):
    base = {
        "lpaAnos": [{"ano": 2023, "lpa": 5.23}, {"ano": 2024, "lpa": 4.62}, {"ano": 2025, "lpa": 2.40}],
        "lpa": 2.18,
        "guidance": {"periodo": "2026", "lpa": 1.75},
        "guidanceInicial": {"lpa": 4.20},
        "lynch": {"futuro": {"lpaEsteAno": 1.75}},
    }
    base.update(over)
    return base


def test_pontos_lpa_grafico_com_os_3_dados_mostra_as_6_barras():
    pontos = _pontos_lpa_grafico(_dados())
    anos = [p["ano"] for p in pontos]
    assert anos == ["2023", "2024", "2025", "2026\nInicial", "2026\nAtual", "2026E\nGuidance"]
    assert all(p["valor"] is not None for p in pontos)


def test_pontos_lpa_grafico_sem_previsao_anual_nao_mostra_barra_inicial():
    """Ativo sem Previsão Anual (guidanceInicial.lpa ausente) - nunca uma barra vazia/zero no lugar,
    a barra "2026 / Inicial" simplesmente não entra na lista."""
    pontos = _pontos_lpa_grafico(_dados(guidanceInicial=None))
    anos = [p["ano"] for p in pontos]
    assert "2026\nInicial" not in anos
    assert anos == ["2023", "2024", "2025", "2026\nAtual", "2026E\nGuidance"]


def test_pontos_lpa_grafico_sem_guidance_nem_consenso_nao_mostra_barra_e():
    """Ativo sem Guidance oficial E sem consenso do Yahoo (lpaEsteAno ausente) - a barra "2026E"
    não entra na lista; nenhum valor 0/traço no lugar."""
    pontos = _pontos_lpa_grafico(_dados(guidance=None, lynch={"futuro": {"lpaEsteAno": None}}))
    anos = [p["ano"] for p in pontos]
    assert not any(a.startswith("2026E") for a in anos)
    assert anos == ["2023", "2024", "2025", "2026\nInicial", "2026\nAtual"]


def test_pontos_lpa_grafico_sem_previsao_e_sem_guidance_mostra_so_historico_e_ttm():
    pontos = _pontos_lpa_grafico(
        _dados(guidanceInicial=None, guidance=None, lynch={"futuro": {"lpaEsteAno": None}}))
    anos = [p["ano"] for p in pontos]
    assert anos == ["2023", "2024", "2025", "2026\nAtual"]


def test_pontos_lpa_grafico_sem_ttm_nao_mostra_barra_atual():
    pontos = _pontos_lpa_grafico(_dados(lpa=None))
    anos = [p["ano"] for p in pontos]
    assert "2026\nAtual" not in anos


def test_pontos_lpa_grafico_sem_nenhum_dado_do_ano_mostra_so_historico():
    pontos = _pontos_lpa_grafico(
        _dados(lpa=None, guidanceInicial=None, guidance=None, lynch={"futuro": {"lpaEsteAno": None}}))
    anos = [p["ano"] for p in pontos]
    assert anos == ["2023", "2024", "2025"]


def test_pontos_lpa_grafico_sem_guidance_oficial_mas_com_consenso_mostra_barra_projecao():
    """Sem OVERRIDE/guidance automático (guia None), mas com estimativa do Yahoo (lpaEsteAno) -
    a barra aparece, rotulada "Projeção" (não "Guidance", que exigiria fonte oficial citada)."""
    pontos = _pontos_lpa_grafico(_dados(guidance=None))
    anos = [p["ano"] for p in pontos]
    assert "2026E\nProjeção" in anos
    assert "2026E\nGuidance" not in anos


def test_pontos_lpa_grafico_valor_negativo_real_nao_e_escondido():
    """Guidance de prejuízo (LPA inicial negativo) é um dado real, não um dado ausente - a barra
    continua aparecendo com o valor negativo (regra travada 28/11/2026: só `is not None` esconde
    a barra, nunca um filtro de sinal/positividade)."""
    pontos = _pontos_lpa_grafico(_dados(guidanceInicial={"lpa": -1.5}))
    por_ano = {p["ano"]: p["valor"] for p in pontos}
    assert por_ano["2026\nInicial"] == -1.5


# ---------------- card "Últimos 4 trimestres (TTM)" (28/11/2026, pedido do usuário após o caso GOOGL) ----------------

def _googl_trimestres():
    """Os 4 trimestres reais do GOOGL já conferidos pelo usuário (CLAUDE.md, REGRA 7) - fonte EUA
    (contabil_sec.json): cada trimestre já tem "lpa" direto, nunca "lucro"."""
    return {"status": "ok", "acoes": None, "trimestres": [
        {"fim": "31/12/2025", "lpa": 2.82},
        {"fim": "31/03/2026", "lpa": 5.11},
        {"fim": "30/06/2026", "lpa": 9.11},
        {"fim": "30/09/2026", "lpa": 2.12},
    ]}


def test_pontos_trimestres_ttm_googl_soma_19_16():
    """Trava o caso real que gerou a confusão 19,16 x 19,03 (CLAUDE.md, REGRA 7): a soma exata dos
    4 trimestres GAAP diluídos do GOOGL é 19,16, não 19,03."""
    ut = _pontos_trimestres_ttm({"lpaSec": _googl_trimestres()})
    assert ut["total"] == 19.16
    assert ut["linhas"] == [
        {"label": "Q4 2025", "valor": 2.82},
        {"label": "Q1 2026", "valor": 5.11},
        {"label": "Q2 2026", "valor": 9.11},
        {"label": "Q3 2026", "valor": 2.12},
    ]


def test_pontos_trimestres_ttm_b3_calcula_lpa_por_lucro_sobre_acoes():
    """B3 (contabil_br.json): o trimestre só tem "lucro" (total da empresa) - o LPA é lucro ÷ acoes,
    o MESMO `acoes` do registro que já produz o lpa_12m total (REGRA 1 do TTM) - nunca um número novo."""
    sec = {"status": "ok", "acoes": 1_000_000_000.0, "trimestres": [
        {"fim": "31/12/2025", "lucro": 500_000_000.0},
        {"fim": "31/03/2026", "lucro": 300_000_000.0},
    ]}
    ut = _pontos_trimestres_ttm({"lpaSec": sec})
    assert ut["linhas"] == [
        {"label": "Q4 2025", "valor": 0.5},
        {"label": "Q1 2026", "valor": 0.3},
    ]
    assert ut["total"] == 0.8


def test_pontos_trimestres_ttm_trimestre_ausente_mostra_so_os_que_existem():
    """Um trimestre sem "fim" nem dado suficiente (nem "lpa", nem "lucro"+"acoes") nunca é
    completado/estimado - simplesmente não entra na lista; os outros continuam aparecendo."""
    sec = {"status": "ok", "acoes": None, "trimestres": [
        {"fim": "31/12/2025", "lpa": 2.82},
        {"fim": "31/03/2026"},          # sem "lpa" e sem "acoes" pra calcular via "lucro" - ausente
        {"fim": "30/06/2026", "lpa": 9.11},
    ]}
    ut = _pontos_trimestres_ttm({"lpaSec": sec})
    assert [l["label"] for l in ut["linhas"]] == ["Q4 2025", "Q2 2026"]
    assert ut["total"] == 2.82 + 9.11


def test_pontos_trimestres_ttm_sem_nenhum_trimestre_nao_mostra_o_bloco():
    assert _pontos_trimestres_ttm({"lpaSec": {"status": "ok", "trimestres": []}}) is None
    assert _pontos_trimestres_ttm({"lpaSec": None}) is None
    assert _pontos_trimestres_ttm({"lpaSec": {"status": "incompleto"}}) is None
    assert _pontos_trimestres_ttm({}) is None
