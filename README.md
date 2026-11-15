# FINTAI
Fintai - Sua grana investida pela IA. App que analisa, sugere e investe por você.

Painel de ações do Brasil e dos EUA: estado do ativo (COMPRAR, AGUARDAR, CARO, VENDER) pelo
percentil da faixa de 52 semanas, validado por teste histórico, com fundamentos, preço justo
e comparação com o índice.

## Rodar

    pip install -r requirements.txt
    streamlit run app.py

## Regras

As regras de dados e de cálculo do projeto estão em `CLAUDE.md`: todo número vem de fonte
confiável (Yahoo Finance ou Banco Central), nada é inventado nem travado por ativo.

## Estrutura

- `app.py`: página do Streamlit, busca de dados (Yahoo Finance e Banco Central) e cache.
- `tela/dados.py`: monta o pacote único de dados que a tela lê (fonte única de verdade).
- `tela/detalhe.html`, `detalhe.css`, `detalhe.js`: a tela de detalhes da ação, montada
  como componente do Streamlit.
- `utils/percentile.py`: posição do preço na faixa de 52 semanas e zonas de preço.
- `utils/signals.py`: decisão de estado, selo do teste histórico, backtest de 5 anos.
- `utils/lynch.py`: regra de prejuízo em 3 anos (modos Graham e Lynch), crescimento e PEG do futuro.
- `utils/simons.py`: sequência de quedas e régua fixa do modo Simons.
- `utils/benchmarks.py`: CDI, Selic, IPCA e Poupança pelo SGS do Banco Central.
- `calculos.py`: médias, tendência, P/L médio, dividendos e preço justo.
- `tools/gerar_demo.py`: gera `docs/index.html`, a tela atual com dados de exemplo da Micron
  (publicada pelo GitHub Pages). Rode de novo sempre que a tela mudar.
- `prototipos/fintai-micron.html`: protótipo da tela com dados de exemplo (Micron).
- `tests/`: testes unitários.

## Testes

    pip install -r requirements-dev.txt
    python -m pytest

Ferramenta de estudo, não é recomendação de investimento.
