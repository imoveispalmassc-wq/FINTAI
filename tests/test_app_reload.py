"""Issue #33: app.py recarrega os módulos na memória (Streamlit Cloud) numa ordem fixa. Um módulo
que faz `from utils.fetch_guidance import nome` no topo (ex. utils/dados_fixos.py) tem que ser
recarregado DEPOIS de utils.fetch_guidance - senão ele reimporta de uma versão antiga do módulo
ainda em memória, e um nome adicionado depois do último reload vira ImportError."""
import re
from pathlib import Path

APP = Path(__file__).parent.parent / "app.py"


def _ordem_do_reload() -> list[str]:
    texto = APP.read_text(encoding="utf-8")
    m = re.search(r"for _modulo in \(([^)]*)\):\s*\n\s*importlib\.reload\(_modulo\)", texto)
    assert m, "não achei o loop de importlib.reload(_modulo) em app.py"
    return [p.strip() for p in m.group(1).split(",") if p.strip()]


def test_fetch_guidance_recarrega_antes_de_dados_fixos():
    ordem = _ordem_do_reload()
    assert "utils.fetch_guidance" in ordem and "utils.dados_fixos" in ordem
    assert ordem.index("utils.fetch_guidance") < ordem.index("utils.dados_fixos")


def test_utils_dados_fixos_so_importa_nomes_que_existem_em_fetch_guidance():
    """Sanity check direto: todo nome que dados_fixos.py importa de fetch_guidance precisa
    existir lá de verdade (evita o próprio ImportError, independente da ordem do reload)."""
    import utils.fetch_guidance as fg

    texto = Path(__file__).parent.parent.joinpath("utils", "dados_fixos.py").read_text(encoding="utf-8")
    m = re.search(r"from utils\.fetch_guidance import \(([^)]*)\)", texto, re.S)
    assert m
    nomes = [n.strip() for n in m.group(1).split(",") if n.strip()]
    faltando = [n for n in nomes if not hasattr(fg, n)]
    assert not faltando, f"nomes importados de fetch_guidance que não existem mais: {faltando}"
