# FINTAI: regras do projeto

App de análise de ações (Streamlit) para qualquer ativo do Yahoo Finance: B3 (PETR4, BBAS3,
VALE3...), EUA (MU, AAPL...) e demais bolsas. Leia antes de mudar qualquer número na tela.

## Dados: sempre de fonte confiável

- Todo número da tela vem de uma fonte identificável: Yahoo Finance (cotações, demonstrativos,
  estimativas de analistas) ou Banco Central / SGS (CDI, Selic, IPCA, Poupança).
- Nunca inventar, estimar por conta própria ou copiar número de outro ativo. Dado que falta
  aparece como "Dados indisponíveis" ou "Sem dado".
- Nunca travar valores de um ativo no código (ex.: 511,31 / 936,28 / 176,50 da MU). Tudo sai de
  regras de cálculo aplicadas aos dados do ativo buscado.
- Estimativas de analistas mostram a base (ano atual, próximo ano fiscal, longo prazo), o número
  de analistas e a faixa quando o Yahoo informa. Com menos de 3 analistas, avisar que é pouco confiável.
- Projeção da empresa (guidance) não vem do Yahoo: só entra com fonte citada.
- A página de exemplo (`docs/index.html`, gerada por `tools/gerar_demo.py`) não busca dados.
  Qualquer valor nela sem fonte real fica vazio ou marcado como EXEMPLO.

## Regras de cálculo (valem para todos os ativos)

- Faixa de 52 semanas: ponto de oportunidade = mínima + 30% da amplitude; fim da Zona Neutra =
  mínima + 70%. Validação: mínima 192,59 e máxima 1.255,00 dão 511,31 e 936,28.
- Decisão: COMPRAR - Oportunidade / AGUARDAR - Neutro / CARO - Evitar, sempre com
  "Ponto de oportunidade em [valor]".
- Regra de prejuízo (Graham e Lynch): LPA dos últimos 3 anos; 1 ano negativo sai da média
  ("Ano de prejuízo excluído"); 2 ou mais, não calcula ("Sem cálculo - Empresa com prejuízo recorrente").
- Backtest: 5 anos por padrão; todo o histórico só na escala "Máx.", com aviso.

## Textos

- Nunca mostrar "percentil" nem a sigla IFR como título (só "Força", "Últimos 14 dias").
- Nunca usar a palavra em inglês para operação de curto prazo: sempre "movimento curto".
- Rodapé: "Fonte: Yahoo Finance. Dados podem mudar após balanço."

## Antes de publicar

- `python -m pytest` precisa passar.
- Se mudar a tela (`tela/detalhe.*`), rodar `python tools/gerar_demo.py` para atualizar a página de exemplo.
