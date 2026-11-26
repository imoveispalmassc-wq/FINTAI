"""Issue #46 (item 1): meta tags de Open Graph para o preview do link no WhatsApp.

O app Streamlit só tem controle sobre o HTML inicial (o que o WhatsApp lê, sem rodar JavaScript)
reescrevendo o index.html estático que vem dentro do próprio pacote `streamlit` - ver utils/seo.py
para a explicação completa e a limitação (não é uma configuração oficial do Streamlit)."""
from pathlib import Path

import pytest

from utils.seo import IMAGEM_OG, MARCADOR, aplicar_meta_og, tags_og


def test_tags_og_tem_og_title_descricao_e_imagem():
    bloco = tags_og("FINTAI", "Descrição de teste", "https://exemplo.com/img.png")
    assert 'og:title" content="FINTAI"' in bloco
    assert 'og:description" content="Descrição de teste"' in bloco
    assert 'og:image" content="https://exemplo.com/img.png"' in bloco
    assert 'twitter:card" content="summary_large_image"' in bloco


def test_tags_og_url_opcional():
    sem_url = tags_og("T", "D", "https://x/img.png")
    com_url = tags_og("T", "D", "https://x/img.png", url="https://x/pagina")
    assert "og:url" not in sem_url
    assert 'og:url" content="https://x/pagina"' in com_url


def test_imagem_og_padrao_e_url_real_do_repositorio_nunca_inventada():
    # aponta para o logo de verdade do projeto (assets/logo.png, publicado no GitHub) - nunca uma
    # URL de imagem inventada, como a regra do projeto exige
    assert IMAGEM_OG == "https://raw.githubusercontent.com/imoveispalmassc-wq/FINTAI/main/assets/logo.png"


def test_aplicar_meta_og_injeta_no_index_html_e_e_idempotente(tmp_path, monkeypatch):
    index = tmp_path / "index.html"
    index.write_text(
        "<!doctype html><html><head><title>Streamlit</title></head><body></body></html>",
        encoding="utf-8",
    )
    monkeypatch.setattr("utils.seo._index_html_do_streamlit", lambda: index)

    assert aplicar_meta_og(titulo="FINTAI", descricao="desc", imagem="https://x/img.png") is True
    conteudo = index.read_text(encoding="utf-8")
    assert "<title>FINTAI</title>" in conteudo
    assert MARCADOR in conteudo
    assert 'og:image" content="https://x/img.png"' in conteudo

    # segunda chamada: não duplica o bloco (idempotente)
    assert aplicar_meta_og(titulo="FINTAI", descricao="desc", imagem="https://x/img.png") is True
    assert index.read_text(encoding="utf-8").count(MARCADOR) == 1


def test_aplicar_meta_og_sem_arquivo_nunca_derruba_o_app(monkeypatch):
    monkeypatch.setattr("utils.seo._index_html_do_streamlit", lambda: None)
    assert aplicar_meta_og() is False


def test_aplicar_meta_og_sem_head_fechado_nunca_derruba_o_app(tmp_path, monkeypatch):
    index = tmp_path / "index.html"
    index.write_text("<html><body>sem head fechado</body></html>", encoding="utf-8")
    monkeypatch.setattr("utils.seo._index_html_do_streamlit", lambda: index)
    assert aplicar_meta_og() is False


def test_aplicar_meta_og_erro_de_escrita_nunca_derruba_o_app(tmp_path, monkeypatch):
    index = tmp_path / "index.html"
    index.write_text("<head><title>Streamlit</title></head>", encoding="utf-8")
    monkeypatch.setattr("utils.seo._index_html_do_streamlit", lambda: index)

    def _escrita_falha(*a, **k):
        raise PermissionError("sem permissão de escrita (ex.: hospedagem sem acesso ao site-packages)")

    monkeypatch.setattr(Path, "write_text", _escrita_falha)
    assert aplicar_meta_og() is False
