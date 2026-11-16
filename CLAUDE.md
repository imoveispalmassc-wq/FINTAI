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
- Projeção da empresa (guidance) não vem do Yahoo: só entra com fonte citada, pelo `OVERRIDE` em
  `utils/override.py` (lucro_min, lucro_max, fonte, data; acoes e payout opcionais, sem acoes usa o Yahoo). Com override, o guidance ganha
  do Yahoo: LPA projetado = (lucro_min + lucro_max) / 2 / acoes; dividendo projetado = LPA × payout.
  A tela mostra o selo "GUIDANCE OFICIAL" com a data. Sem override, vale o consenso do Yahoo.
- Guidance automático: `utils/fetch_guidance.py` roda todo dia às 9h (`.github/workflows/update-guidance.yml`)
  para os tickers de `utils/guidance_tickers.json` e grava em `utils/guidance_auto.json`. Busca nos documentos
  entregues à CVM; padrões de texto primeiro, API do Claude só se falharem (chave em GitHub Secrets).
  A leitura da API só vale se a faixa estiver no documento (achada pelos padrões ou no trecho, sem
  contar espaços e separadores de tabela). Ticker não gravado vira aviso amarelo na execução do Actions.
  Primeira gravação de cada ticker: sempre pull request. Depois de aprovada, confiança alta e variação
  menor que 50%: commit direto. API do Claude, confiança baixa ou LPA mudando 50% ou mais: pull request.
  Nunca usa documento mais antigo que o mais novo com faixa de lucro, nem mais antigo que o guidance já
  salvo (descarta). Documento com mais de 120 dias vai para PR. Cadastro manual em override.py ganha
  do automático. Ações dos EUA desligadas até haver e-mail de contato para a SEC.
- A página de exemplo (`docs/index.html`, gerada por `tools/gerar_demo.py`) não busca dados.
  Qualquer valor nela sem fonte real fica vazio ou marcado como EXEMPLO.

## Regras de cálculo (valem para todos os ativos)

- Faixa de 52 semanas: ponto de oportunidade = mínima + 30% da amplitude; fim da Zona Neutra =
  mínima + 70%. Validação: mínima 192,59 e máxima 1.255,00 dão 511,31 e 936,28.
- A faixa acompanha o período do gráfico: Hoje/1S/1M/1A usam 52 semanas; 5A usa 260 semanas;
  Máx. usa todo o histórico. Mesma regra de 30%/70%. Só a faixa de 52 semanas tem teste histórico;
  nas outras o selo diz "SEM TESTE".
- Decisão: COMPRAR - Oportunidade / AGUARDAR - Neutro / CARO - Evitar, sempre com
  "Ponto de oportunidade em [valor]".
- Regra de prejuízo (Graham e Lynch): LPA dos últimos 3 anos; 1 ano negativo sai da média
  ("Ano de prejuízo excluído"); 2 ou mais, não calcula ("Sem cálculo - Empresa com prejuízo recorrente").
- Graham em duas versões: atual = √(22,5 × LPA 12 meses × VPA); média = √(22,5 × LPA médio 3 anos × VPA),
  com a regra de prejuízo. Usado = o MENOR dos dois (só um existindo, esse; LPA 12 meses <= 0, só a média).
  Se LPA 12 meses < 60% da média de 3 anos: "Lucro atual 40%+ abaixo da média de 3 anos. Estamos usando
  o Graham mais conservador (lucro atual). Se usasse a média, o valor seria otimista." Com LPA 12 meses
  negativo (só resta a média), o aviso diz que a média pode estar otimista.
- P/L médio de 12 meses só usa o LPA trimestral do Yahoo se a série bater com o LPA de 12 meses em até 10%
  (senão as bases são diferentes, ex.: ajustado x contábil). Aí tenta o lucro contábil de cada balanço
  (lucro trimestral ÷ ações; trimestre faltante pelo anual ou pelo LPA de 12 meses; precisa bater com o LPA atual
  e cobrir 6+ meses, só os dias cobertos). Sem isso: preço médio do ano ÷ LPA atual.
- Card de P/L: linhas P/L, Lucro/ação, Cotação; colunas Contábil (LPA 12 meses, data do último balanço), Previsão do ano (consenso do Yahoo,
  com analistas e faixa) e Média 12m. Guidance oficial e lucro ajustado aparecem em linhas à parte, com fonte.
- Retorno acumulado: período (1/3/5 anos) no topo; barras com o ativo primeiro e os indicadores em ordem crescente.
- Para conferir o que o Yahoo devolve para um ticker: Actions -> "Diagnóstico Yahoo (só leitura)".
- Backtest: 5 anos por padrão; todo o histórico só na escala "Máx.", com aviso.

## Textos

- Nunca mostrar "percentil" nem a sigla IFR como título (só "Força", "Últimos 14 dias").
- Nunca usar a palavra em inglês para operação de curto prazo: sempre "movimento curto".
- Rodapé: "Fonte: Yahoo Finance. Dados podem mudar após balanço."

## Antes de publicar

- `python -m pytest` precisa passar.
- Se mudar a tela (`tela/detalhe.*`), rodar `python tools/gerar_demo.py` para atualizar a página de exemplo.
