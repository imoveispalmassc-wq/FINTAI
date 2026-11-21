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
  `utils/override.py` (lucro_min, lucro_max, fonte, data; acoes e payout opcionais, sem acoes usa o Yahoo). Guidance
  em lucro por ação (EUA): lpa_min/lpa_max no lugar do lucro; dividendo (anual da empresa, ganha do payout) e
  periodo (ex.: FY2027) opcionais; base_AAAA_recalculada / base_AAAA_antes quando a empresa recalcula a base
  (só com a tabela citada na fonte). Com override, o guidance ganha
  do Yahoo: LPA projetado = (lucro_min + lucro_max) / 2 / acoes; dividendo projetado = LPA × payout.
  A tela mostra o selo "GUIDANCE OFICIAL" com a data. Sem override, vale o consenso do Yahoo.
- Guidance automático: `utils/fetch_guidance.py` roda sozinho todo dia às 8h de Brasília, e pelo botão Run workflow (`.github/workflows/update-guidance.yml`)
  para os tickers de `utils/guidance_tickers.json` e grava em `utils/guidance_auto.json`. Busca nos documentos
  entregues à CVM (BR) e na SEC EDGAR (EUA: 8-K/6-K com o press release no Exhibit 99.1, faixa de LPA e dividendo); padrões de texto primeiro, API do Claude só se falharem (chave só em secrets.ANTHROPIC_API_KEY, nunca no
  código nem no log): regex sem confiança, ou regex sem faixa no documento de projeção mais novo (B3) / no comunicado
  mais novo (EUA); uma chamada por documento; resposta só JSON (lucro_min, lucro_max, lpa_min, lpa_max, payout, trecho,
  pagina). API falhou ou sem guidance: mantém o anterior e o log diz "sem guidance".
  A leitura da API só vale se a faixa estiver no documento (achada pelos padrões ou no trecho, sem
  contar espaços e separadores de tabela). Ticker não gravado vira aviso amarelo na execução do Actions.
  Fallback de ano (`extrair_por_padroes`): se os padrões acham a faixa de lucro mas não acham o ano perto de
  "guidance/projeção/estimativa/perspectiva", tenta, nessa ordem, (1) um único ano claro no título/categoria/
  assunto do documento na CVM, (2) um único ano claro nos 500 caracteres antes e depois da própria faixa. Achando
  exatamente um ano nesses lugares, usa esse ano e manda para a API do Claude confirmar normalmente - a confiança
  continua "baixa" mesmo quando o ano bate com o ano-alvo, então nunca publica sozinho só por causa do fallback.
  Achando mais de um ano diferente, ou nenhum, mantém "ano da projeção não encontrado" como antes. Não muda nada
  quando o ano já é achado pelo jeito normal (perto de "guidance/projeção").
  Histórico (janela deslizante): a API sempre devolve os últimos 4 guidances do documento, do mais antigo
  para o mais novo, só para o próprio modelo julgar se o pulo faz sentido (ex.: $7,50→$9,90→$10,65 é gradual,
  $8,00→$20,00 é suspeito e não confirma). O código confere que o último item do histórico bate com a faixa
  atual devolvida; se não bater, descarta a leitura. O histórico aparece no corpo do pull request, para revisão.
  AUTOMÁTICO COM PROTEÇÃO (`avaliar_travas`): publica sozinho (commit + issue "Guidance publicado sozinho")
  só se passar nas 4 travas: (1) fonte oficial (documento da empresa na CVM ou 8-K/6-K na SEC); (2) a mesma
  faixa aparece 2+ vezes no documento (texto + tabela); (3) LPA projetado muda no máximo 20% contra o guidance
  do app (cadastro manual ou automático salvo; sem anterior = trava); (4) P/L novo (cotação ÷ LPA projetado)
  positivo, até 100 e entre 1/3 e 3x o P/L de 12 meses do Yahoo. Dúvida também trava: projeção de outro ano ou
  documento com mais de 120 dias. Travou: não grava no app, abre pull request dizendo qual trava falhou e
  espera a decisão (merge publica, fechar descarta); o mesmo documento travado não é avisado de novo.
  Toda decisão vai para `utils/guidance_log.json`; toda sexta (`.github/workflows/resumo-semanal.yml`)
  sai uma issue com o publicado sozinho e o travado na semana. Nunca chuta número.
  Nunca usa documento mais antigo que o mais novo com faixa de lucro, nem mais antigo que o guidance já
  salvo (descarta). Cadastro manual em override.py ganha do automático. EUA: User-Agent "fintai/1.0 (contato: ...)" com o e-mail só do Secret SEC_CONTACT_EMAIL
  (nunca no código); sem o Secret, os tickers dos EUA ficam de fora com aviso. Leitura pela API passa pelas mesmas 4 travas.
  Duas faixas de LPA no mesmo comunicado: ignora a perto de previously/prior/previous/earlier e fica com a perto de
  updated/revised/now expects/raising/lowering; se ainda sobrarem duas, não grava (aviso amarelo).
- Fila pública de tickers novos (app com muitos usuários, não só o dono): digitar um ticker fora de
  `utils/guidance_tickers.json` mostra na hora o TTM/P/L do Yahoo normalmente, mais o aviso "Guidance ainda não
  verificado - vamos verificar hoje à noite", e registra o pedido como uma Issue do GitHub ("Fila: TICKER", label
  `fila-ticker`) pelo `utils/fila_github.py`, usando o Secret `GITHUB_QUEUE_TOKEN` (permissão só de Issues, nunca de
  conteúdo do repositório - o app nunca grava arquivo). Pedidos repetidos do mesmo ticker só comentam na issue já
  aberta (dedup; "pedidos" = 1 + comentários), e o aviso só aparece 1x por ticker por sessão do navegador.
  `.github/workflows/fila-tickers.yml` roda a cada 6 horas (ou pelo Run workflow) e processa até
  `FILA_MAX_POR_RUN` (15) tickers por execução, do mais pedido para o menos pedido (`processar_fila` em
  `utils/fetch_guidance.py`): tenta achar o guidance com as mesmas travas de "Fonte oficial" e "Número em 2
  lugares" do AUTOMÁTICO COM PROTEÇÃO. Validado: entra em `guidance_tickers.json` (o robô diário passa a
  acompanhar; o guidance em si só aparece depois que o dono aprovar o primeiro PR, igual qualquer ticker novo -
  a fila nunca pula essa aprovação). Não validado: grava para sempre em `utils/queue_nao_validado.json` com o
  motivo, fecha a issue explicando, e o app para de mostrar o aviso "ainda não verificado" para esse ticker (ele
  passa a mostrar só TTM/P/L do Yahoo, igual qualquer ticker sem guidance - nunca número inventado). Erro de
  configuração (ex.: falta `SEC_CONTACT_EMAIL`) não trava o ticker: ele continua na fila para a próxima execução.
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
- Card de P/L: linhas P/L, Lucro líquido (lucro/ação × ações do Yahoo), Lucro/ação, Cotação; colunas em ordem
  cronológica: Início do ano (primeiro guidance do ano, congelado, com data e fonte) -> Contábil 12 meses (real, muda a
  cada balanço) -> Previsão atual (guidance oficial se houver, senão consenso do Yahoo). Embaixo, só 4 linhas curtas
  (Início do ano: guidance; Contábil: cotação ÷ LPA = P/L; Previsão atual: guidance/consenso e variação desde o início;
  Média 12m: P/L e diferença). Soma dos trimestres, fontes completas, faixas de LPA, lucro ajustado e a definição de P/L
  ficam em "Ver como calculamos".
- Contábil 12 meses (EUA): utils/contabil_sec.json, gravado pelo robô = soma dos 4 últimos trimestres de LPA AJUSTADO
  do press release (8-K Exhibit 99.1 de cada trimestre); fonte "SEC 8-K Exhibit 99.1, LPA Ajustado". Os trimestres saem
  do GAAP dos 10-Q/10-K (4º tri = ano − 9 meses). Trimestre sem ajustado usa o GAAP dele e o card marca "Contábil
  Ajustado (N trimestre GAAP por falta de Ajustado)". Sem nem GAAP completo (menos de 4 trimestres, fora de sequência
  ou último com mais de 200 dias): Yahoo, "fonte: Yahoo - SEC incompleto". No fim de cada ticker o robô grava
  atualizado_em, trimestre_ref e trimestre_data, igual à B3 (ver abaixo) - calculando o trimestre a partir do
  mês de fim de cada trimestre, já que a SEC não dá "3T26" pronto.
- LPA anual histórico (EUA, cartão "Lucro por ação", Graham, médias de 5/10 anos e Faixa do Conservador): o app
  (não o robô) busca `app.lpa_anual_eua(ticker)` na hora, direto da SEC (10-K, EarningsPerShareDiluted), para
  qualquer ticker dos EUA, sem precisar estar em guidance_tickers.json. Motivo: o `income_stmt` do Yahoo
  normalmente só traz uns 4 anos e, em alguns casos, usa base diferente da que a empresa reporta à SEC - a SEC é
  a fonte primária e tem o histórico completo de 10-K. Quando a SEC tem o dado, substitui 100% a série do Yahoo
  (nunca mistura as duas bases) e troca a
  fonte da tela para "SEC 10-K, lucro por ação diluído (GAAP)"; sem a SEC (sem o Secret `SEC_CONTACT_EMAIL` no
  Streamlit Cloud, ticker não encontrado, ou sem o dado), cai de volta no Yahoo, como antes. Não tem limite de
  anos como o Yahoo (só ~4): usa todo o histórico de 10-K que a SEC tiver, o que ajuda a Média de 5/10 anos e a
  Faixa a aparecerem com mais frequência. Precisa do mesmo e-mail de contato que o robô usa (SEC_CONTACT_EMAIL),
  só que como Secret do Streamlit Cloud - são dois lugares diferentes, cada um com o seu Secret.
- Guidance TRIMESTRAL (EUA, card "Guidance da empresa para o próximo trimestre"): empresas como a Micron dão
  guidance a cada earnings release para o PRÓXIMO TRIMESTRE (receita, margem bruta, LPA), não para o ano fiscal
  inteiro - diferente do guidance ANUAL (lpa_min/lpa_max, "Previsão atual"/P/L, selo GUIDANCE OFICIAL) descrito
  acima. Os dois nunca se misturam: usar o LPA de 1 trimestre como se fosse do ano inteiro distorceria o P/L.
  Por isso é só informativo, num card separado, sem entrar no P/L nem nas 4 travas do AUTOMÁTICO COM PROTEÇÃO
  (não precisa: não é o número que a tela usa para decidir nada). O robô (`atualizar_outlook_trimestral_eua`,
  rodado pelo workflow todo dia junto com o guidance anual) olha os earnings releases mais recentes de cada
  ticker dos EUA já em guidance_tickers.json OU já travado em queue_nao_validado.json (os dois arquivos juntos -
  é exatamente o caso de empresas como MU e AMD, que não têm guidance anual mas dão trimestral; sem incluir os
  travados, o card delas nunca apareceria sozinho) e tenta achar a tabela/lista de "Business Outlook"/"Financial
  Outlook" só por padrões de texto (sem API do Claude, sem travas - a faixa extraída é usada tal como está no
  documento, nunca inventada). Reconhece hoje: "guidance for the Nth quarter of year", "'s outlook for the Nth
  quarter of fiscal year", "for the fiscal Nth quarter year, we expect" e "for the Nth quarter of year, EMPRESA
  expects" (ex.: AMD); faixas em "X ± Y", "X to Y" e "X, plus or minus Z%"; margem em "Approximately X%" ou
  "between X% and Y%" (nesse caso o ponto médio). Nem toda empresa dá guidance de LPA (ex. NVIDIA e AMD só dão
  receita/margem) nem usa um desses formatos (ex. Apple não dá guidance numérico formal) - sem achar um formato
  reconhecido, o campo correspondente fica "Sem dado" e, sem nada achado, o card simplesmente não aparece (nunca
  trava o ticker como "não validado": isso é só do guidance ANUAL). Não calcula margem líquida por fora (ex.:
  LPA × ações do Yahoo ÷ receita) mesmo quando dá para estimar: o LPA de guidance costuma ser non-GAAP e as
  ações do Yahoo podem não bater com a base da empresa - mostra só o que a empresa realmente divulgou. Grava
  em utils/guidance_trimestral_eua.json; uma tentativa sem sucesso nunca apaga um valor bom já gravado.
  O app (não só o robô) também busca ao vivo (`app.outlook_trimestral_eua(ticker)`, cache de 1 dia) quando o
  robô ainda não gravou nada pro ticker - mesmos padrões de texto, sem API do Claude, pra não depender do
  próximo ciclo do robô (6 em 6 horas) nem de intervenção manual toda vez que um ticker novo cai nessa mesma
  situação (sem guidance anual, com trimestral).
  `anexo_sec` (abre o Exhibit 99.1 de um 8-K/6-K) identifica o arquivo certo pela coluna "Type" da página de
  índice da SEC, não só pelo nome do arquivo - correção necessária porque empresas como a NVIDIA nomeiam o
  press release sem o padrão "ex99" (ex.: "q3fy27pr.htm"), e a leitura por nome falhava silenciosamente para
  elas (isso também melhora a leitura do guidance ANUAL e do contábil, que usam a mesma função). Emissores
  estrangeiros em 6-K (ex. Novo Nordisk/NVO) às vezes não têm Exhibit 99 nenhum - o comunicado vem direto no
  corpo do próprio formulário; nesse caso (só pra 6-K, nunca pra 8-K) aceita o documento do tipo "6-K" como
  alternativa. Mesmo assim, nem toda empresa dá guidance trimestral (a NVO, por exemplo, só dá guidance
  ANUAL) - sem achar, o card simplesmente não aparece, como qualquer outro caso sem dado.
  O aviso da fila pública ("ainda não verificado") deixa claro que é do guidance ANUAL ("Guidance ANUAL de
  TICKER ainda não verificado"), para não confundir com o trimestral. Ticker já travado no guidance anual (em
  queue_nao_validado.json) mas com guidance trimestral verificado: em vez do aviso de pendente, mostra uma nota
  diferente ("Guidance ANUAL de TICKER não encontrado ... a empresa só dá guidance trimestral. Guidance
  trimestral verificado abaixo") - não é um dado faltando, é a empresa que não dá guidance anual.
- Contábil 12 meses (B3): tickers de utils/contabil_br_config.json (linha do lucro e nome da fonte; hoje só BBAS3, linha
  "Lucro Líquido Ajustado", fonte "BB, Divulgação de Resultados, Lucro Líquido Ajustado"). O robô lê o release de
  resultados de cada trimestre na CVM (trimestre = o último encerrado antes da entrega), extrai o lucro do trimestre
  (frase e tabela; divergência > 3% = sem confiança; frase com acumulado/ano/semestre/9M/12M é descartada; tabela só
  pela coluna trimestral; sem unidade escrita, decide pela frase, e "3,9" sem frase é ambíguo; lucro < R$ 1 mi, ex. 0,00,
  é leitura inválida e tenta o próximo documento; em release/Relatório de Análise Gerencial a tabela vence sempre e a
  frase só ajuda na unidade; PDF com 3 tentativas e leitores pypdf → pdfplumber → PyMuPDF; trimestre que não abre usa a
  coluna dele na tabela de um release posterior; log "BBAS3 3T26: frase=... tabela=... divergência=... gravou=..."), soma 4 trimestres consecutivos e grava em utils/contabil_br.json:
  LPA = soma ÷ ações (Yahoo). Sem conseguir ler: "Yahoo - pendente", nunca número inventado; pendente não apaga valor
  bom já gravado. Demais tickers da B3: Yahoo.
  No fim de cada ticker (B3 e EUA) o robô grava atualizado_em ("17/11 18:32", Brasília; só muda com leitura boa,
  igual ao "pendente"/"incompleto" não apagar valor bom), trimestre_ref ("3T26") e trimestre_data ("set/26").
  O card de P/L mostra no topo "🟢 Atualizado em 17/11 às 18:32" e "Contábil 12m até 3T26 (set/26)" para
  qualquer ativo com contábil do robô (B3 ou EUA): verde com menos de 2h, amarelo com menos de 24h, vermelho
  com 24h ou mais.
- Projeção do início do ano: utils/guidance_inicial.json (ticker -> ano -> faixa, fonte, data, travado). O robô busca o
  primeiro documento do ano com projeção (release do 4T anterior, jan-abr; depois o 10-K) e grava uma única vez:
  nunca sobrescreve. Sem achar: {"status": "sem projeção inicial encontrada"}.
- Retorno acumulado: período (1/3/5 anos) no topo; barras com o ativo primeiro e os indicadores em ordem crescente.
- SIMONS, nesta ordem: (1) MM200 no gráfico com preço e distância %; (2) classificação pela faixa de 52 semanas
  (30/70) + MM200: OPORTUNIDADE = zona de oportunidade e preço até +5% da MM200; CARO = zona cara ou +15% ou
  mais acima da MM200; senão NEUTRO; (3) dias de queda desde o topo dos últimos 10 pregões (alta no meio não quebra) viram entrada
  escalonada só dentro da oportunidade: 2-3 dias 1/3, 4-6 dias 2/3, 7+ 3/3 (5º dia nunca manda tudo). Abaixo da
  MM200 com a média caindo: 4-6 dias 1/3, 7+ 2/3, última parte só com preço acima da MM200 ou média parando de cair.
  Neutro/Caro: dias são só alerta. Mostra também a régua fixa (A VALIDAR) e o histórico de 5 anos do ativo
  (cada queda conta uma vez por linha; "10 ou mais" só no dia em que chega a 10). Gráfico 10D do SIMONS: escala
  inclui MM200, oportunidade e caro (nome e valor escritos na linha, à esquerda), % de cada dia de queda no ponto.
  Cartões em barras visuais: classificação na faixa de 52 semanas com a MM200 marcada; dias de 0 a 10+ com as
  partes da entrada; histórico em vezes que subiu/caiu (sem % solto; contorno azul = hoje; ★ MELHOR só com 30+ casos, 8+ pontos
  acima da média geral e 5+ acima da segunda melhor; senão "Nenhum padrão forte - todos entre X% e Y%"); régua fixa de 1 a 5+.
- CONSERVADOR: a "Faixa de preço" (zona de oportunidade/neutra/cara e o badge COMPRAR/AGUARDAR/CARO do topo) usa
  valuation, não a faixa histórica de 52 semanas. Preço Teto = ÂNCORA = preço médio dos últimos 1 ano (fechamento
  semanal, igual à `media_fechamentos` de 52 semanas). Oportunidade até 0,70 × Teto (margem de segurança de 30%);
  Neutra alargada até 1,30 × Teto (30% ACIMA do teto - não vira "Cara" só por passar um pouco da âncora); Cara
  acima disso (`decidir_estado_conservador` aceita `caro_acima` opcional, padrão 1,30 × teto). Substituiu o
  Número de Graham (LPA médio × VPA): o preço histórico quase nunca falta (diferente de LPA/VPA, que ficavam
  "Sem dado" com frequência, e cuja mediana de anos longos pode ficar presa a um regime de mercado antigo da
  empresa, ex. MU antes do supercycle de IA). Sem 1 ano de histórico de preço (ticker recém-listado): sem teto -
  a tela cai para a faixa de 52 semanas como alternativa visual; nunca tem teste histórico ("SEM TESTE"), mesmo
  quando o valuation está disponível. Médias de 3 anos (margem de 40%: limite = 0,60 × média) e 5 anos (margem
  de 50%: limite = 0,50 × média) NÃO travam a decisão - são só referências visuais, sempre marcadas na régua
  (a escala da barra estica além da mínima/máxima do período quando precisa, pra caber até o limite de 5 anos,
  que costuma ficar abaixo da mínima de 52 semanas) - a mínima/máxima mostrada nas bordas da régua é sempre um
  dado real (a mínima/máxima do período, ou o próprio ponto - ex. limite de 5 anos - quando ele é mais extremo
  que o período; nunca uma margem inventada). Quando a borda coincide exatamente com um ponto já marcado por um
  traço, só não repete o número (fica em branco na borda) - o traço e o valor continuam lá, só não duplica o
  texto. Se o preço cair abaixo da mínima (ou subir acima da máxima) da régua, a bolinha encosta na borda e
  para de se mover (não desaparece, só perde a precisão de mostrar o quanto passou). A média de 200 dias
  (mm200) é marcada direto na barra
  (traço laranja). Os limites de 3 e 5 anos dividem a própria zona de oportunidade em
  até 3 tons de verde, mais forte quanto mais fundo o preço (mais claro perto do ponto de entrada de 1 ano, mais
  escuro perto do limite de 5 anos) - `--verde-claro` entre o limite de 3a e a oportunidade, `--verde` entre o
  limite de 5a e o de 3a, `--verde-forte` abaixo do limite de 5a; com só um dos dois limites disponível, usa só
  2 tons, e sem nenhum, a zona toda fica na cor padrão (`--verde`). As posições na régua (cortes de cor, traços
  e os próprios números) usam a mesma posição já afastada pelo `afastar()` (distância mínima de 17 pontos) -
  nunca a posição linear crua: senão, quando os pontos ficam muito próximos no preço real (ex. zona de
  oportunidade estreita), a cor mudaria num lugar e o número escrito em cima diria outro, parecendo que a faixa
  verde "não chega" onde o próprio número diz que chega. O "Você está aqui" (bolinha do preço) passa pela MESMA
  transformação (interpolação entre a posição crua e a já afastada de cada ponto, com 0%/100% como âncoras) -
  senão a bolinha ficaria "presa" perto do traço errado sempre que o preço real estiver perto de um ponto que
  foi empurrado pro afastar() (ex. preço de R$14,30 bem perto do limite de 3 anos de R$14,65 apareceria colado
  no traço do limite de 5 anos, bem mais longe). Sem texto explicativo embaixo
  da régua (só os cartões Zona de oportunidade/neutra/cara acima já explicam os cortes). O
  PONTO DE ENTRADA (o texto "Ponto de oportunidade em") é sempre o alvo fixo de 30% sobre a âncora de 1 ano -
  não escala para os limites de 3/5 anos, que são só
  referência, nunca o ponto de entrada em si. O gráfico pontilhado do modo Conservador repete as mesmas 3 faixas
  de verde da barra, rotuladas Oportunidade 1 (o próprio ponto de entrada), Oportunidade 2 (limite de 3 anos) e
  Oportunidade 3 (limite de 5 anos), sem "anos" no texto, além da mm200 - a escala do eixo Y também estica pra
  caber o limite de 5 anos quando ele fica abaixo da mínima do período mostrado, senão as linhas ficariam
  espremidas perto do fundo do gráfico (mesmo problema e mesma solução da régua). TODAS as linhas do gráfico
  (Oportunidade 1/2/3, Neutro, Caro, Média 200d, Bem abaixo no Lynch) seguem o mesmo desenho: título e valor com
  espaço bem maior entre si (ex. "Oportunidade 2    14,65"), e a linha tracejada só começa depois do próprio
  texto (nunca passa atrás dele, só do fim do texto até a borda direita) - cada uma na sua própria altura, com
  folga mínima de 12px das outras (de baixo pra cima), pra nunca uma cair bem em cima da outra quando os valores
  são próximos (ex. Oportunidade 1 e 2) ou iguais (Neutro e Caro, que descrevem o mesmo valor dos dois lados).
  Sem a antiga linha
  "Média dos métodos ... não validado" (média do Conservador/P/L
  histórico/Bazin): tirada do gráfico por não ser validada e confundir com os cortes reais do valuation; os 3
  métodos continuam no card "Preço justo", sem relação com a Faixa de preço. A legenda das zonas (Caro/Neutro/
  Oportunidade, mais Média 200d quando ela aparece) é HTML normal em linha, fora do gráfico (embaixo dele) - não
  é mais desenhada em cima do canvas, pra nunca colidir com nenhuma linha/rótulo do próprio gráfico; ordem
  Oportunidade/Média/Neutro/Caro, com espaço curto entre os itens (agrupados à esquerda, não esticados pela
  largura toda - isso empurraria o último pra quase fora da tela em celular). Sem o link "Ver como calculamos" da variação do
  gráfico (perto do "Variação em X: -Y% só preço"): só a variação em si continua.
  Mais reativo a mudança de cenário do que usar um LPA médio de vários anos (que reage devagar) e
  menos sujeito a 1 ano isolado distorcer tudo (diferente de olhar só o LPA do último ano). O card de Lucro por
  ação continua exigindo exatamente 10 anos ("Sem dado" sem isso) para "Média 5/10 anos" e o Graham ali, com
  média simples, e não muda com nada disso: "P/L Conservador" e "Preço teto conservador" (LPA médio 10a × 15)
  continuam só como diagnóstico, não viram teto nem usam preço de fechamento por ano. A barra (mínima/máxima do
  período do gráfico e "Você está aqui") continua só mostrando onde o preço está; não define mais os cortes. A
  faixa de 52 semanas clássica (mínima + 30%) não aparece mais como referência extra na barra (tirada por ser um
  número antigo e confundir com os cortes do valuation). Rótulos que ficariam colados (ativo perto da mínima/
  máxima do período, ex. BBAS3 perto da mínima de 52 semanas: zona de oportunidade muito estreita) se afastam
  automaticamente na régua de números (função `afastar`, distância mínima de 17 pontos); o nome da zona
  (Oportunidade/Neutra/Cara) some quando a coluna fica estreita demais pra caber o texto sem quebrar palavra -
  regra geral, vale pra qualquer ativo, não só pra casos específicos. LYNCH
  ignora a faixa e usa só a
  MM200: Oportunidade = MM200 −10% a +5%;
  abaixo de −10% = "Bem abaixo da MM200" (azul, separado, ainda COMPRAR); Neutro = +5% a +15%; Caro = +15% ou mais;
  ponto de oportunidade = MM200 × 1,05.
- Para conferir o que o Yahoo devolve para um ticker: Actions -> "Diagnóstico Yahoo (só leitura)".
- Backtest: 5 anos por padrão; todo o histórico só na escala "Máx.", com aviso.

## Textos

- Nunca mostrar "percentil" nem a sigla IFR como título (só "Força", "Últimos 14 dias").
- Nunca usar a palavra em inglês para operação de curto prazo: sempre "movimento curto".
- Rodapé: "Fonte: Yahoo Finance. Dados podem mudar após balanço."

## Antes de publicar

- `python -m pytest` precisa passar.
- Se mudar a tela (`tela/detalhe.*`), rodar `python tools/gerar_demo.py` para atualizar a página de exemplo.
