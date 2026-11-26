"""Meta tags Open Graph (preview do WhatsApp/Telegram/Twitter) para o app Streamlit.

PROBLEMA: `st.set_page_config(page_title=...)` só muda o <title> depois que o JavaScript do
Streamlit termina de montar a página (é um app de página única, renderizado no navegador).
O HTML que o servidor devolve de cara - o único que o WhatsApp lê, porque ele NUNCA executa
JavaScript para gerar o preview de um link - é sempre o mesmo arquivo estático
`streamlit/static/index.html` que vem dentro do pacote, com <title>Streamlit</title> e nenhuma
meta tag de Open Graph. É por isso que o link do app no WhatsApp não mostra nem o nome certo.

SOLUÇÃO (sem servidor próprio, sem acesso ao HTML inicial pelo `app.py`): o container do
Streamlit Cloud roda o app com o pacote `streamlit` instalado no mesmo sistema de arquivos onde
`app.py` roda, e esse arquivo é gravável. `aplicar_meta_og()` reescreve esse index.html uma única
vez (idempotente - não reescreve de novo se já tiver as tags) sempre que o app sobe, trocando o
<title> e inserindo as tags og:title/og:description/og:image antes de </head>. Isso MUDA o HTML
que o servidor devolve na primeira resposta, antes de qualquer JavaScript rodar - é exatamente o
que o crawler do WhatsApp lê.

LIMITAÇÃO HONESTA (documentada para quem for revisar isto): isto é um ajuste no arquivo estático
do pacote `streamlit` instalado, não uma configuração oficial e documentada do Streamlit - não há
hoje (nesta versão) nenhum parâmetro de `st.set_page_config` nem arquivo de config.toml para
meta tags Open Graph. O ajuste:
  - precisa de permissão de escrita no `site-packages` do container (o Streamlit Cloud tem;
    qualquer outro jeito de hospedar pode não ter - falha em silêncio, nunca derruba o app);
  - é refeito a cada vez que o app sobe (container novo = arquivo original de novo), por isso
    roda sempre, não só uma vez;
  - não foi possível confirmar visualmente o preview real do WhatsApp a partir deste ambiente:
    o WhatsApp precisa buscar uma URL pública de verdade (e, às vezes, cacheia o preview antigo
    por um tempo mesmo depois de corrigido) - só dá para confirmar depois de publicado, abrindo o
    link do app publicado em uma conversa do WhatsApp.
  - a imagem usada é o logo do projeto (`assets/logo.png`), publicado de verdade no repositório
    (raw.githubusercontent.com) - nunca uma URL inventada; sem imagem própria do app em produção
    (print de tela, banner etc.), é a única imagem real disponível.
"""
from __future__ import annotations

import logging
from pathlib import Path

LOG = logging.getLogger(__name__)

MARCADOR = "<!-- FINTAI-OG -->"

# Imagem real do projeto (logo em assets/logo.png), publicada no GitHub - nunca uma URL inventada.
# Sem uma imagem de preview própria do app publicada ainda (ex.: print de tela da tela de detalhes),
# fica só o logo como og:image.
IMAGEM_OG = "https://raw.githubusercontent.com/imoveispalmassc-wq/FINTAI/main/assets/logo.png"


def _index_html_do_streamlit() -> Path | None:
    """Caminho do index.html estático que o Streamlit serve de cara (fora do app.py)."""
    try:
        import streamlit
        caminho = Path(streamlit.__file__).parent / "static" / "index.html"
        return caminho if caminho.is_file() else None
    except Exception:  # pragma: no cover - defensivo, nunca derruba o app
        return None


def tags_og(titulo: str, descricao: str, imagem: str = IMAGEM_OG, url: str | None = None) -> str:
    """Monta o bloco de meta tags (usado também pela página de exemplo em tools/gerar_demo.py)."""
    linhas = [
        MARCADOR,
        f'<meta property="og:type" content="website">',
        f'<meta property="og:title" content="{titulo}">',
        f'<meta property="og:description" content="{descricao}">',
        f'<meta property="og:image" content="{imagem}">',
        f'<meta name="twitter:card" content="summary_large_image">',
        f'<meta name="twitter:title" content="{titulo}">',
        f'<meta name="twitter:description" content="{descricao}">',
        f'<meta name="twitter:image" content="{imagem}">',
    ]
    if url:
        linhas.insert(1, f'<meta property="og:url" content="{url}">')
    return "\n    ".join(linhas)


def aplicar_meta_og(titulo: str = "FINTAI", descricao: str =
                     "Análise de ações do Brasil e dos EUA: decisão COMPRAR/AGUARDAR/CARO com "
                     "fundamentos, faixa de preço e comparação com o índice.",
                     imagem: str = IMAGEM_OG, url: str | None = None) -> bool:
    """Injeta as meta tags de Open Graph no HTML estático do Streamlit (ver módulo acima).

    Idempotente (não reescreve se o marcador já estiver lá) e nunca derruba o app: qualquer
    falha (sem permissão de escrita, arquivo não encontrado etc.) só grava um aviso no log e
    devolve False - a tela continua funcionando normalmente, só sem o preview corrigido.
    """
    caminho = _index_html_do_streamlit()
    if caminho is None:
        LOG.warning("SEO: index.html do Streamlit não encontrado - preview do WhatsApp não ajustado.")
        return False
    try:
        html = caminho.read_text(encoding="utf-8")
        if MARCADOR in html:
            return True   # já aplicado (idempotente)
        if "</head>" not in html:
            LOG.warning("SEO: index.html do Streamlit sem </head> - preview do WhatsApp não ajustado.")
            return False
        bloco = tags_og(titulo, descricao, imagem, url)
        html = html.replace("<title>Streamlit</title>", f"<title>{titulo}</title>", 1)
        html = html.replace("</head>", f"    {bloco}\n  </head>", 1)
        caminho.write_text(html, encoding="utf-8")
        return True
    except Exception as e:  # pragma: no cover - defensivo, nunca derruba o app
        LOG.warning("SEO: não deu para ajustar o preview do WhatsApp (%s).", e)
        return False
