# FINTAI
Fintai - Sua grana investida pela IA. App que analisa, sugere e investe por você.

Painel de ações do Brasil e dos EUA: estado do ativo (COMPRAR, AGUARDAR, CARO, VENDER) pelo
percentil da faixa de 52 semanas, validado por teste histórico, com fundamentos, preço justo
e comparação com o índice.

## Rodar

    pip install -r requirements.txt
    streamlit run app.py

## Estrutura

- `app.py`: tela (Streamlit) e busca de dados no Yahoo Finance.
- `utils/percentile.py`: percentil na faixa de 52 semanas e zonas de preço.
- `utils/signals.py`: decisão de estado, selo do teste histórico, critérios de fundamentos.
- `calculos.py`: médias, tendência, P/L médio, dividendos e preço justo.
- `tests/`: testes unitários.

## Testes

    pip install -r requirements-dev.txt
    python -m pytest

Ferramenta de estudo, não é recomendação de investimento.
