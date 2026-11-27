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
  salvo (descarta). Cadastro manual em override.py ganha do automático. Todo ticker cadastrado manualmente em
  OVERRIDE também precisa entrar em `utils/guidance_tickers.json` na mesma mudança (vale igual pra B3 e EUA) -
  senão o robô diário nunca passa a acompanhar esse ticker sozinho (fica parado no guidance manual pra sempre) e
  a tela mostra "Guidance ANUAL ainda não verificado" pra um ticker que já tem guidance oficial cadastrado.
  `tests/test_override.py` tem um teste que falha se algum ticker de OVERRIDE estiver faltando em
  guidance_tickers.json, pra nunca esquecer disso de novo. EUA: User-Agent "fintai/1.0 (contato: ...)" com o e-mail só do Secret SEC_CONTACT_EMAIL
  (nunca no código); sem o Secret, os tickers dos EUA ficam de fora com aviso. Leitura pela API passa pelas mesmas 4 travas.
  Duas faixas de LPA no mesmo comunicado: ignora a perto de previously/prior/previous/earlier e fica com a perto de
  updated/revised/now expects/raising/lowering; se ainda sobrarem duas, não grava (aviso amarelo).
- Fila pública de tickers novos (app com muitos usuários, não só o dono): digitar um ticker fora de
  `utils/guidance_tickers.json` mostra na hora o TTM/P/L do Yahoo normalmente, mais o aviso "Guidance ainda não
  verificado - vamos verificar hoje à noite", e registra o pedido como uma Issue do GitHub ("Fila: TICKER", label
  `fila-ticker`) pelo `utils/fila_github.py`, usando o Secret `GITHUB_QUEUE_TOKEN` (permissão só de Issues, nunca de
  conteúdo do repositório - o app nunca grava arquivo). Pedidos repetidos do mesmo ticker só comentam na issue já
  aberta (dedup; "pedidos" = 1 + comentários), e o aviso só aparece 1x por ticker por sessão do navegador.
  `.github/workflows/fila-tickers.yml` dispara de 2 jeitos (Issue #48, item 7): (1) `issues: opened`
  filtrado pela label `fila-ticker` - processa só o ticker daquela Issue (`--issue NÚMERO`) em até ~2 minutos,
  1 única vez, sem reprocessar o lote; (2) `schedule` a cada 6 horas (ou "Run workflow") como FALLBACK/BACKUP,
  caso o evento de Issue falhe ou não dispare - processa até `FILA_MAX_POR_RUN` (15) tickers por execução, do
  mais pedido para o menos pedido. Os dois caminhos chamam a mesma `processar_fila` (`utils/fetch_guidance.py`,
  parâmetro `numero` filtra pra 1 Issue só) e a mesma lógica: tenta achar o guidance com as mesmas travas de
  "Fonte oficial" e "Número em 2 lugares" do AUTOMÁTICO COM PROTEÇÃO. Validado: entra em `guidance_tickers.json`
  (o robô diário passa a acompanhar; o guidance em si só aparece depois que o dono aprovar o primeiro PR, igual
  qualquer ticker novo - a fila nunca pula essa aprovação). Não validado: grava para sempre em
  `utils/queue_nao_validado.json` com o motivo, fecha a issue explicando, e o app para de mostrar o aviso "ainda
  não verificado" para esse ticker (ele passa a mostrar só TTM/P/L do Yahoo, igual qualquer ticker sem guidance -
  nunca número inventado). Erro de configuração (ex.: falta `SEC_CONTACT_EMAIL`) não trava o ticker: ele continua
  na fila para a próxima execução. A atualização de cotação (a cada 2 minutos, pelo app) é outro mecanismo
  completamente separado - não é tocada por nada disso.
- A página de exemplo (`docs/index.html`, gerada por `tools/gerar_demo.py`) não busca dados.
  Qualquer valor nela sem fonte real fica vazio ou marcado como EXEMPLO.

## Biblioteca própria (Perplexity) e divergência automática - Issue #48, itens 8 e 9

- **REGRA TRAVADA (27/11/2026, revisada no mesmo dia): Perplexity só alimenta número com fonte
  OFICIAL comprovada - nunca sem.** Decisão inicial do dia foi travar TOTALMENTE o uso da
  Perplexity em cálculo; revisada horas depois porque a trava total jogava fora um caso que já
  tinha sido testado manualmente e funcionou (BBAS3: LPA contábil 3T25 = 0,53 e 3T26 = 0,21, direto
  do RI, com fonte). A regra final não é "nunca" nem "sempre" - é CONDICIONAL, e vale pra
  `utils/biblioteca.py` (descrito abaixo) e pra qualquer uso futuro da Perplexity no projeto:
  1. Só confirma um número vindo de fonte OFICIAL: RI da própria empresa, SEC EDGAR, CVM ou B3 -
     nunca notícia, agregador de dados ou opinião de analista sem documento oficial por trás.
  2. Sempre com LINK da fonte + PÁGINA/seção onde o número aparece - sem os dois, não confirma
     (`confirmar_com_claude`/`ESQUEMA_CONFIRMACAO_CLAUDE` exigem `link` e `pagina` como campos
     obrigatórios; achou=true sem eles é descartado, nunca salvo).
  3. Contábil e Ajustado SEMPRE em colunas/campos separados (`valor`/`valor_ajustado`), nunca
     misturados - REGRA 1 do TTM já documentada abaixo (contábil é sempre o principal).
  4. Grava sempre com dado + fonte + link + data/hora (`salvar_na_biblioteca`). Sem fonte oficial
     comprovada (link + página), NÃO salva e NÃO mostra número - quem lê a biblioteca mostra "Não
     divulgado" (texto de exibição de quem chama; a função em si só devolve `None`, nunca inventa
     um texto de erro como se fosse um dado).
  Testes travados: `tests/test_biblioteca.py::test_confirmar_com_claude_sem_link_nao_confirma` e
  `::test_confirmar_com_claude_sem_pagina_nao_confirma`.
  A chave (`PERPLEXITY_API_KEY`) continua configurada nos Secrets do GitHub. Hoje (27/11/2026) a
  biblioteca ainda não é lida por nenhuma parte da tela que o usuário vê (confirmado ao investigar
  um bug de "Sem dado" repetido no card "Lucro por ação" da B3 - ver mais abaixo) - essa regra vale
  pra quando ela passar a ser lida, e pro próprio workflow que já a alimenta.
- `utils/biblioteca.py` é um cache novo e genérico para qualquer dado fundamentalista pesquisado
  (LPA, lucro, dividendo, ROE etc.) - `utils/biblioteca.json`, no MESMO padrão dos outros caches
  do projeto (`contabil_br.json`/`contabil_sec.json`: ticker -> campo -> registro com valor, fonte
  e data/hora). Ponto de entrada único: `obter(ticker, campo, periodo, hoje)`.
  1. Biblioteca primeiro (`buscar_na_biblioteca`): se já tem o dado e não está desatualizado (mais
     de `DIAS_DESATUALIZADO` = 120 dias desde a pesquisa - a MESMA régua de ~1 trimestre já usada
     em `IDADE_MAXIMA_DIAS`, utils/fetch_guidance.py, em vez de inventar um limite novo), usa.
  2. Sem dado, desatualizado, OU se a busca externa (`buscar_externo`, ex.: as mesmas funções de
     SEC/CVM/RI que o resto do projeto já usa, na mesma ordem já definida) falhar - inclusive "o
     Yahoo quebrou" (erro de rede/parsing) - cai para a Perplexity (`pesquisar_via_perplexity`),
     com o PROMPT PADRÃO EXATO da Issue #48 (`montar_prompt_perplexity`/`PROMPT_PADRAO` - não
     mudar o texto do prompt: pede Contábil e Ajustado em colunas separadas, núcleo sempre +
     bloco de banco ou de não-banco).
  3. A Perplexity só traz o dado com a fonte citada; a API do Claude (`confirmar_com_claude`,
     mesma regra de confiança baixa do guidance automático em `ler_com_claude`) só CONFIRMA ou
     CORRIGE o número que a Perplexity já trouxe - nunca inventa um número por conta própria. O
     trecho que a API devolve tem de existir na resposta da Perplexity (mesma ideia de `_confere`
     do guidance automático), senão a leitura é descartada.
  4. Achado um dado novo (de onde vier), `salvar_na_biblioteca` grava na hora, com fonte e
     data/hora, antes de devolver pra quem chamou.
  REGRA TRAVADA - CONTÁBIL É SEMPRE O PRINCIPAL (REGRA 1 do TTM): o registro guarda `valor`
  (contábil, sempre o principal) e `valor_ajustado` (opcional) em campos separados - nunca
  misturados no mesmo cálculo; quem lê a biblioteca só mostra o ajustado com a etiqueta
  "[Ajustado]". `.github/workflows/biblioteca-perplexity.yml` roda todo dia (depois do guidance
  automático) ou pelo "Run workflow", chama `python -m utils.biblioteca atualizar --tickers
  utils/guidance_tickers.json` e manda `utils/biblioteca.json` para um PR (sempre o mesmo ramo,
  `biblioteca/revisar` - NUNCA direto na main, mesma cautela da REGRA 6 do TTM automático, já que
  a biblioteca pode guardar qualquer dado fundamentalista, não só o contábil TTM). Hoje o campo
  processado pelo workflow é só um exemplo (`lpa_atual`) - a função `obter`/`atualizar_tickers` é
  genérica para qualquer campo; cada indicador novo que passar a usar este módulo (app ou outro
  robô) só precisa chamar `obter(ticker, campo, periodo, hoje)` com o seu próprio `buscar_externo`.
  `--ticker TICKER` (CLI) / input `ticker` (workflow_dispatch), acrescentado 27/11/2026: roda só
  esse 1 ticker da lista, em vez de todos - usado pra testar um ticker isolado (ex.: "Run workflow"
  manual com `ticker: BBAS3`) sem gastar chamada de API nos outros 18, e é a mesma peça que um
  gatilho por Issue/fila (ainda NÃO implementado - fica pra outra mudança) vai precisar pra rodar
  só o ticker daquela Issue, no mesmo padrão já usado em `fila-tickers.yml`/`processar_fila`.

  MIGRAÇÃO PARA A AGENT API (27/11/2026, REGRA TRAVADA): o endpoint antigo (`POST
  /chat/completions`, corpo `{"model": "sonar-pro", "messages": [...]}`) foi DESCONTINUADO pela
  Perplexity em 27/09/2026 ("Sonar Chat Completions support ended") - só descoberto rodando de
  verdade em produção/Actions pra BBAS3 (403 `chat_completions_not_available`, pedindo a migração;
  o corpo da resposta de erro só aparecia no log depois de um ajuste pra logar esse corpo, que não
  existia antes). Lido o guia oficial de migração (nunca adivinhado -
  https://docs.perplexity.ai/docs/agent-api/migrate-from-sonar/overview e .../how-to, liberados no
  allowlist de rede desta sessão pra isso) e migrado pra: endpoint `POST
  https://api.perplexity.ai/v1/agent` (o nome do método no SDK oficial é `responses.create()`, mas
  o caminho REST de verdade, confirmado nos exemplos `curl` da própria doc, é `/v1/agent` - não
  `/v1/responses`, que só aparecia na mensagem de erro porque é o nome do recurso lógico, não o
  caminho); corpo `{"effort": "fast", "input": "<prompt>"}` em vez de `model`+`messages` - a doc
  mapeia explicitamente `sonar-pro` → effort `"fast"`; resposta: array `output`, texto no(s)
  item(ns) `"type": "message"` → `content[].text` (`type: "output_text"`), concatenados. A chave
  (`PERPLEXITY_API_KEY`, nos Secrets do GitHub) nunca aparece no código, só em
  `os.environ.get("PERPLEXITY_API_KEY")`. Nenhuma outra parte do módulo mudou com a migração
  (prompt, confirmação pela API do Claude, regra de link+página): a citação de fonte/página
  continua vindo de DENTRO do texto gerado (pedida no próprio PROMPT_PADRAO), não de um campo
  estruturado da API. LIMITAÇÃO CONHECIDA (ambiente de desenvolvimento desta issue): a validação de
  ponta a ponta da Agent API nova (chave real, resposta real pra um ticker) só é possível em
  produção/Actions, com o Secret configurado - esta sandbox não bate em `api.perplexity.ai`. Por
  isso os testes (`tests/test_biblioteca.py`) usam um `chamar`/`chamar_perplexity`/`chamar_claude`
  injetável com respostas SIMULADAS, claramente marcadas como mock no próprio teste (ex.: comentário
  "MOCK CLARAMENTE DOCUMENTADO", texto com "(SIMULADO)") - nenhuma chamada de rede de verdade é
  feita nos testes, e nenhum dado simulado é tratado como se fosse real. 3 testes à parte
  (`test_pesquisar_via_perplexity_payload_e_resposta_da_agent_api`,
  `..._erro_http_loga_corpo_e_devolve_none`, `..._output_sem_mensagem_devolve_none`) testam a
  função `chamar` REAL (não injetada) via `monkeypatch` de `requests.post` - confirmam o payload e
  o parsing da resposta da Agent API sem bater na rede, já que os testes que usam `chamar=`
  injetado não exercitam esse trecho do código.
  LOG DETALHADO (27/11/2026): `pesquisar_via_perplexity` loga a resposta de verdade (truncada a 800
  caracteres) e `confirmar_com_claude` loga o JSON completo da decisão quando não confirma (achou,
  valor_contabil, fonte, link, pagina, trecho) - sem isso, um "não confirmado" só dizia o nome do
  ticker/campo, sem dar pra saber SE o motivo foi a Perplexity não achar nada, achar sem fonte
  oficial, ou a trava de link+página barrando à toa.
  BUG CORRIGIDO - `_periodo_atual` pedia o trimestre ERRADO (27/11/2026, achado testando BBAS3 de
  verdade pela primeira vez, já com crédito pago liberado na Perplexity): pedia o trimestre
  CALENDÁRIO em que `hoje` cai (27/11/2026 -> "4T26") - mas o 4T26 do Banco do Brasil só sai em
  10/02/2027, então a Perplexity corretamente respondia "Não divulgado" pra tudo e a API do Claude
  corretamente recusava confirmar (`achou: false`) - nem chegava na trava de link+página, travava
  antes. Corrigido pra sempre pedir o trimestre ANTERIOR ao calendário de hoje (27/11/2026 ->
  "3T26") - sem inventar uma data de divulgação por empresa (não existe calendário de divulgação
  genérico no projeto): um trimestre corrente nunca está divulgado assim que o calendário vira a
  página (a divulgação leva semanas depois do fim do trimestre), então o trimestre ANTERIOR é o
  único com chance real de já ter sido divulgado. Ainda pode vir "Não divulgado" pra empresas
  atrasadas - a Perplexity/API do Claude continuam livres pra dizer isso, nunca inventam. Testes
  travados em `test_periodo_atual_pede_o_trimestre_anterior_ao_calendario_de_hoje` (inclui a virada
  de ano, jan-mar -> 4º trimestre do ano anterior).

  EFFORT "fast" NÃO VASCULHA DOCUMENTO O BASTANTE (27/11/2026, achado testando BBAS3 de verdade,
  período já corrigido pra "3T26"): com `effort: "fast"` a Perplexity achou que o relatório de
  desempenho do 3T26 existe, mas recusou completar o LPA porque a busca não trouxe a linha/página
  específica dentro do documento - correto (não inventou nada), mas insuficiente. O guia oficial
  recomenda `"fast"` pra "busca de fato único" e `"low"` pra "multi-hop browsing e agregação ampla
  em várias fontes" - vasculhar um documento oficial atrás de uma linha específica é esse 2º caso.
  `PERPLEXITY_EFFORT` mudado pra `"low"` (único uso deste módulo é o PROMPT_PADRAO, sempre esse
  tipo de busca) - testado e achou o número certo (R$ 0,21 3T26 / R$ 0,53 3T25, batendo com o teste
  manual anterior do usuário), com a fonte "Sumário do Resultado, p. 3".

  FONTES: A AGENT API CITA MARCADOR, NÃO LINK (BUG CORRIGIDO, 27/11/2026, achado na mesma rodada):
  mesmo achando o número certo com `effort: "low"`, a confirmação pela API do Claude continuava
  recusando (`achou: false` vazio) - a Agent API cita fonte no TEXTO só como marcador ("[web:8]"),
  não como link embutido (diferente do Sonar antigo) - a URL de verdade fica num item SEPARADO da
  resposta (`output`, `type: "search_results"`, `results: [{"id", "url", "title", ...}]"), que
  `pesquisar_via_perplexity` descartava por completo. Corrigido: `pesquisar_via_perplexity` agora
  captura essa lista (`fontes_capturadas`) e devolve junto no dict (`resultado["fontes"]`);
  `confirmar_com_claude` monta um bloco "FONTES (id -> título/URL de verdade)" e manda junto na
  instrução, com a regra explícita de resolver o marcador "[web:N]"/"[N]" citado perto do número
  numa URL REAL dessa lista - nunca inventar uma URL fora dela, nunca escrever o marcador cru no
  campo `link`. A trava de link+página continua EXATAMENTE igual (não foi enfraquecida) - só passou
  a receber o dado certo pra decidir. Testes travados em
  `test_pesquisar_via_perplexity_payload_e_resposta_da_agent_api` (fontes capturadas do JSON cru),
  `test_confirmar_com_claude_instrucao_inclui_as_fontes_pra_resolver_marcadores` e
  `test_confirmar_com_claude_sem_fontes_capturadas_avisa_na_instrucao`.

- `utils/divergencia.py` (Issue #48, item 9): quando um robô acha um número diferente do que já
  está salvo, ele mesmo abre uma Issue sozinho (`abrir_issue_divergencia`, API REST do GitHub com
  o `GITHUB_TOKEN` padrão do Actions - só precisa de "Issues: write" no mesmo repositório, nunca
  de um token especial). Título `Divergência: TICKER - Salvo: X / Novo: Y`, label `divergencia`,
  corpo com Ticker/Campo/Base (contábil ou `[Ajustado]`)/Salvo/Novo/Fonte/Link/Data-hora. Hoje é
  acionado automaticamente em 2 pontos: `utils.ttm_auto._avisar_divergencia_ttm` (TTM diário
  recalculado por um documento novo, diferente do LPA TTM que já estava em `ttm_diario.json`) e
  `utils.biblioteca.salvar_na_biblioteca` (qualquer campo da biblioteca própria gravado com um
  valor contábil diferente do anterior). Os dois são best-effort: se a Issue não puder ser aberta
  (sem `GITHUB_TOKEN`, API fora do ar), o dado novo é gravado do mesmo jeito - só o aviso
  automático é que fica faltando, e isso nunca derruba o catch-up do TTM nem a gravação na
  biblioteca.
  O guidance automático (`utils/fetch_guidance.py`) já tem o seu PRÓPRIO mecanismo equivalente
  (AUTOMÁTICO COM PROTEÇÃO: `avaliar_travas` + PR "Guidance travado"/issue "Guidance publicado") -
  de propósito, ele NÃO também abre uma Issue `divergencia` genérica por cima disso: seria o
  mesmo aviso duplicado. O mesmo vale para o contábil B3/SEC dentro de `fetch_guidance.py`
  (`aplicar_contabil`/`aplicar_contabil_br`): já vai para o PR `ttm/contabil-revisar` existente
  (REGRA 6), sem precisar de uma segunda Issue.
  `.github/workflows/divergencia-revisar.yml` dispara em `issues: opened` filtrado pela label
  `divergencia` e chama `python -m utils.divergencia revisar` - que reaproveita a MESMA
  `utils.fetch_guidance.avaliar_travas` do AUTOMÁTICO COM PROTEÇÃO (`revisar_divergencia`; a
  lógica das 4 travas nunca é duplicada) para decidir: passou nas 4 -> `gh pr create` com a
  correção sugerida, sempre num ramo próprio (`divergencia/revisar-NÚMERO`), NUNCA direto na main
  (merge publica, fechar descarta); travou em alguma -> comenta na própria Issue qual trava falhou
  e deixa ela aberta esperando a decisão humana (não fecha, não publica nada).
  LIMITAÇÃO CONHECIDA: a Issue de divergência guarda só um resumo (ticker, campo, salvo, novo,
  fonte, link, data/hora) - não o texto completo do documento oficial. Por isso, quando
  `revisar_issue_divergencia` reavalia a trava "Número em 2 lugares" (que conta quantas vezes a
  faixa aparece no TEXTO do documento), ela sempre falha nesse fluxo específico (não há texto
  pra contar) - a divergência fica travada esperando decisão humana, em vez de virar PR
  automático. Isso é intencional e do lado seguro (nunca publica sem confirmação completa), mas
  significa que, no estado atual, a maioria das divergências revisadas por este caminho só vira
  PR automático depois de uma melhoria futura que inclua o texto do documento no corpo da Issue.

- **Lista mestra + gatilho por Issue (27/11/2026, "virar sistema")**: `utils/biblioteca_tickers.json`
  é a lista mestra de tickers acompanhados pela biblioteca própria - dict `ticker -> país` ("BR"/
  "US"), país SEMPRE inferido automaticamente por `utils.dados_fixos.eh_br` (`adicionar_ticker_a_lista`,
  `utils/biblioteca.py`), nunca precisa vir escrito na Issue nem em lugar nenhum à mão. É um arquivo
  DIFERENTE de `utils/guidance_tickers.json` (lista do guidance automático) - os dois podem ter
  tickers em comum ou não; a biblioteca própria tem a sua própria lista porque pode (e deve, no
  futuro) acompanhar tickers que não têm guidance anual nenhum, só dado fundamentalista pesquisado.
  RESTRIÇÃO TÉCNICA REAL (documentada aqui com honestidade, porque o pedido original era "atualiza
  a cada 2 min" e isso não é literalmente possível): o GitHub Actions não garante `cron` menor que
  ~5 minutos - um `schedule` de 2 em 2 minutos não é confiável (pode atrasar, enfileirar ou nem
  disparar). Por isso o mecanismo PRINCIPAL para "ticker novo entra na lista e já é processado"
  NÃO é o schedule - é o gatilho `issues: opened`, que dispara em segundos/poucos minutos, no MESMO
  padrão já usado em `fila-tickers.yml` (Issue #48, item 7). O `schedule` existe só como rede de
  segurança (`.github/workflows/biblioteca-tickers.yml`, `*/5 * * * *` = a cada 5 minutos - o
  menor intervalo prático de cron no GitHub Actions),
  reprocessando a lista mestra inteira para o caso de o evento de Issue ter falhado - e mesmo
  nesse caso NÃO é "varrer tudo gastando API à toa": cada ticker passa primeiro por
  `buscar_na_biblioteca` (já existente, `DIAS_DESATUALIZADO` = 120 dias), que só busca de novo o
  que está faltando ou desatualizado; ticker já em dia não gasta nenhuma chamada de Perplexity/
  Claude nesse passo.
  FLUXO: uma Issue título `"Biblioteca: TICKER"` com a label `biblioteca-ticker` dispara
  `.github/workflows/biblioteca-tickers.yml` (`issues: opened`, filtro pela label, igual à fila de
  guidance) - o ticker é extraído do próprio título (nunca precisa de um corpo de Issue formatado),
  e `python -m utils.biblioteca ticker-novo --ticker TICKER` (novo subcomando, `processar_ticker_novo`
  em `utils/biblioteca.py`) faz as 2 coisas: (1) `adicionar_ticker_a_lista` grava o ticker na lista
  mestra se ainda não estiver lá (idempotente - a mesma Issue/ticker reprocessado não duplica); (2)
  já chama o MESMO `atualizar_tickers`/`obter` que o workflow agendado usa, pra esse 1 ticker, na
  hora - NENHUMA trava, fonte ou lógica de confirmação (Perplexity + confirmação da API do Claude,
  link+página obrigatórios) é duplicada ou reescrita; é a mesma função já testada e validada com
  BBAS3. O workflow comenta e fecha a própria Issue com o resultado.
  GRAVAÇÃO: `utils/biblioteca_tickers.json` (a lista - só ticker/país, NENHUM dado fundamentalista)
  vai DIRETO pra main, no mesmo padrão de `utils/guidance_tickers.json` em `fila-tickers.yml` - não
  precisa da mesma cautela de PR porque não é um número pesquisado, é só "este ticker está sendo
  acompanhado". Já `utils/biblioteca.json` (os NÚMEROS de verdade, com fonte/link/página) continua
  TODO indo pelo PR em `biblioteca/revisar` - REGRA 6/mesma cautela do TTM automático, documentada
  acima em "Biblioteca própria (Perplexity)", não muda com este sistema; o workflow novo reusa
  exatamente o mesmo passo de PR que `biblioteca-perplexity.yml` já tinha (mesmo ramo, mesmo
  título), só adicionando o passo de commit direto da lista mestra antes dele. O pipeline que já
  funciona (`pesquisar_via_perplexity`, `confirmar_com_claude`, `salvar_na_biblioteca`, `obter`,
  a trava de link+página, a migração pra Agent API, o `effort: "low"`, a captura de `search_results`)
  não foi tocado - só ganhou 2 funções novas (`adicionar_ticker_a_lista`, `processar_ticker_novo`)
  e 1 subcomando de CLI (`ticker-novo`) por cima dele.
  BUG CORRIGIDO (27/11/2026, achado testando PETR4 e AAPL de verdade pela 1ª vez): 2 Issues abertas
  quase juntas (concurrency serializa os jobs, mas o 2º ainda roda pouco depois do 1º já ter
  empurrado pro main) fazem o passo "Gravar lista mestra" do 2º job falhar com "You have unstaged
  changes" no `git rebase` - a causa é `utils/biblioteca.json` ficar modificado e DE PROPÓSITO
  ainda não commitado nesse ponto (quem commita ele é o passo seguinte, pro PR de
  `biblioteca/revisar`), e isso bloqueia o rebase sempre que o `main` andou nesse meio-tempo.
  Resultado real do teste: PETR4 entrou na lista (sem dado - Perplexity deu timeout de 60s,
  corretamente não inventou nada); AAPL achou LPA real (2,02, fonte SEC 8-K) mas o job falhou
  ANTES de salvar, perdendo o resultado daquela execução (nada ficou inconsistente - só precisou
  rodar de novo). Corrigido com `git stash push --include-untracked -- utils/biblioteca.json`
  antes do `fetch`/`rebase`/`push` da lista mestra, e `git stash pop` depois, pro próximo passo
  (PR da biblioteca) continuar vendo a mudança.

## TTM automático: PROMPT TRAVADO (22/11/2026, vale para todos os robôs e para o ttm_auto.py)

- Fonte, nesta ordem: release no RI > 8-K/6-K na SEC > CVM/ITR. Nunca só site de cotação para lucro/LPA. Domínio do
  RI aceito como link oficial pela config "ri" de cada ativo em `utils/ttm_auto.py` (além de sec.gov/cvm.gov.br).
- Todo registro atualizado leva last_updated ("DD/MM/AAAA às HH:MM"), updated_by e source_date (data do documento
  oficial). O ttm_auto.py NUNCA apaga essas 3 marcações. Ativo que já tem TTM bom NÃO volta para pendente: mantém o
  último TTM (status MANTIDO_TTM_ANTERIOR) e põe o motivo em pendencias.
- REGRA 1: a tela usa SEMPRE LPA GAAP TTM. Ajustado/recorrente NUNCA no campo principal - só lpa_ajustado (ou
  lpa_recorrente), com nota. Ex.: TGT = 10,77 GAAP; 10,91 ajustado só na nota.
- REGRA 2: com operações descontinuadas, usa operações CONTÍNUAS (tag IncomeLossFromContinuingOperationsPerDilutedShare),
  marca tem_descontinuadas: true e guarda o total (lpa_total / lpa_12m_total) só como nota. Sem descontinuadas, GAAP
  total. Ex.: ACM = 2,84 contínuas; 2,25 total na nota.
- REGRA 3: 4º tri = ano − 9 meses, EXCETO quando o release divulga o 4º tri explicitamente: aí vale o do release,
  cadastrado com fonte em `utils/q4_release.json`; registra q4_calculado, q4_release, q4_usado. Ex.: PANW = 0,61
  (release −0,35; cálculo daria −0,39). Quando os 4 trimestres formam exatamente um ano fiscal com LPA anual oficial no
  10-K, o TTM é o próprio anual (LPA não é aditivo; soma_trimestres fica registrada).
- REGRA 4: sem cotação verificada, sem P/L. Cotação "COPIADO - NÃO VERIFICADO", estimada ou sem fonte não gera P/L:
  pl = null e pl_status = "cotação pendente".
- REGRA 5: TTM = 4 trimestres reais somados; guidance é projeção e nunca entra no TTM (guidance em guidance_auto.json;
  TTM em contabil_sec.json / contabil_br.json / ttm_diario.json). Nenhum ativo é configurado "por guidance" no TTM.
- REGRA 6: atualização automática de TTM NUNCA vai direto para a main. ttm_diario.yml abre/atualiza o PR do ramo
  `ttm/revisar`; update-guidance.yml publica só o guidance (com as 4 travas) e manda contabil_sec/contabil_br para o PR
  do ramo `ttm/contabil-revisar`. `python -m pytest` roda antes. Corpo do PR (`tools/resumo_ttm_pr.py`): no topo as
  divergências (GAAP x ajustado, contínuas x total, 4º tri, cotação não verificada), depois ativos alterados, fonte e
  LPA antes -> depois. Merge publica; fechar descarta.

## Regras de cálculo (valem para todos os ativos)

- Faixa de 52 semanas: ponto de oportunidade = mínima + 30% da amplitude; fim da Zona Neutra =
  mínima + 70%. Validação: mínima 192,59 e máxima 1.255,00 dão 511,31 e 936,28.
- A faixa acompanha o período do gráfico: Hoje/1S/1M/1A usam 52 semanas; 5A usa 260 semanas;
  Máx. usa todo o histórico. Mesma regra de 30%/70%. Só a faixa de 52 semanas tem teste histórico;
  nas outras não tem. O card de decisão não mostra mais selo nem alerta embaixo da zona (ex. "SEM
  TESTE", "VALIDADO", avisos de MM200/Lynch) - só rótulo, preço, badge e o texto com o limite da
  faixa inferior. Esses resultados de teste (quando existem, ex. SIMONS) continuam na seção própria
  de cada modo, mais abaixo na tela.
- Decisão (REGRA TRAVADA, 27/11/2026 - antes dizia "COMPRAR - Oportunidade" / "AGUARDAR - Neutro" /
  "CARO - Evitar"; mudado depois que o usuário apontou que o app não pode dizer "AGUARDAR" nem usar
  a palavra "oportunidade" pro usuário - app de análise não pode soar como recomendação de compra/
  venda/espera): o badge (`rotulo`, em `utils/signals.py` e `utils/lynch.py`) mostra só o nome
  neutro da zona - "Faixa inferior" / "Neutro" / "Faixa superior" (ou "Bem abaixo da MM200" no Lynch,
  quando for o caso) - nunca palavra de julgamento ("Oportunidade"/"Evitar") nem verbo de
  recomendação ("AGUARDAR"/"COMPRAR"/"CARO" como texto). `codigo` (COMPRAR/AGUARDAR/CARO) continua
  existindo só internamente, pra decidir a COR do badge (verde/âmbar/cinza) e a classe CSS - nunca
  é mostrado como texto na tela. A frase que antes era "Ponto de oportunidade em [valor]" virou
  "Faixa neutra a partir de [valor]" (mesmo valor de sempre: o limite de 30% sobre a faixa/âncora -
  CORRIGIDO 27/11/2026: a 1ª versão dizia "Faixa inferior até [valor]", mas [valor] é onde a zona
  neutra COMEÇA, não onde a faixa inferior termina - "até" dava a entender que o valor pertencia à
  faixa inferior, quando na verdade é o início da neutra, logo acima; "a partir de" descreve o mesmo
  ponto do lado certo).
  REGRA TRAVADA (2º bug, 27/11/2026, reportado pelo usuário com BBAS3): a frase descreve sempre o
  limite de 30% ("alvo") - mas isso só faz sentido pra quem está na Faixa inferior ou na Zona neutra
  (que começa exatamente ali); pra quem está na Faixa superior, mostrar o limite de 30% é o limite
  da zona ERRADA (BBAS3 a R$ 14,69, na Faixa inferior, chegou a mostrar "Faixa neutra a partir de
  R$ 15,11" - o texto nem sequer descrevia a própria zona do preço). Corrigido: `texto` passa a
  descrever o limite da PRÓPRIA zona em que o preço está, não sempre o mesmo valor de 30%:
  - Preço na Faixa inferior: "Faixa inferior até [limite de 30%]".
  - Preço na Zona neutra: "Faixa neutra a partir de [limite de 30%]" (igual a antes).
  - Preço na Faixa superior: "Faixa superior acima de [limite de 70%]" (valor NOVO - antes também
    usava o de 30%, errado).
  Mesma regra nos 3 modos: `utils.signals.decidir_estado` (faixa de 52 semanas, limites 30%/70% da
  amplitude) e `decidir_estado_conservador` (valuation, 70%/130% da âncora); `utils.lynch.preco_lynch`
  (MM200, "Faixa inferior"/"Bem abaixo da MM200" usam o limite de +5% sobre a MM200, "Faixa superior"
  usa o de +15%); e o texto do SIMONS em `tela/detalhe.js`/`renderDecisao()` (usa `sm.oportunidadeAte`
  pras 2 zonas de baixo, `sm.caraAcima` pra Faixa superior). Testes travados em
  `tests/test_signals.py::test_texto_descreve_o_limite_da_propria_zona_do_preco`,
  `tests/test_dados.py::test_decidir_estado_conservador_texto_descreve_o_limite_da_propria_zona_do_preco`
  (com os valores reais do BBAS3 do bug) e `tests/test_modos.py::test_lynch_texto_descreve_o_limite_da_propria_zona_do_preco`.
  A pequena pílula que repetia a mesma zona embaixo do badge (ex. "Zona neutra") foi removida por
  ficar redundante com o próprio badge, que agora já diz a zona. NÃO aplicado (fica pra outra issue,
  se pedido): o vocabulário interno do próprio modo SIMONS mais abaixo na tela (`utils/simons.py`, a
  classificação OPORTUNIDADE/NEUTRO/CARO e a entrada escalonada "AGUARDAR"/"NÃO COMPRA"/"OBSERVA" de
  `timing()`) - é uma metodologia própria, já documentada como escopo à parte na Issue #47 item 10, e
  só o badge compartilhado do topo (que usa o mesmo componente dos outros 2 modos) foi corrigido aqui.
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
- Contábil 12 meses (EUA): utils/contabil_sec.json, gravado pelo robô = soma dos 4 últimos trimestres de LPA diluído
  GAAP dos 10-Q/10-K (REGRA 1, travada em 22/11/2026: antes era o LPA AJUSTADO do 8-K Exhibit 99.1 - o ajustado agora
  só aparece como lpa_ajustado/nota_ajustado, nunca em lpa_12m). Sem nem GAAP completo (menos de 4 trimestres, fora de
  sequência ou último com mais de 200 dias): Yahoo, "fonte: Yahoo - SEC incompleto". No fim de cada ticker o robô grava
  atualizado_em, trimestre_ref e trimestre_data, igual à B3 (ver abaixo) - calculando o trimestre a partir do
  mês de fim de cada trimestre, já que a SEC não dá "3T26" pronto.
- JANELA DE 4 TRIMESTRES NUNCA RETROCEDE (REGRA TRAVADA, issue #54, corrigida em 26/11/2026): bug real
  encontrado na revisão do PR #53 - o robô trocou o LPA TTM da NVDA de 9,31 para 7,91, descartando o
  trimestre mais recente (fim 25/10/2026, LPA 2,70) e voltando 1 ANO para o trimestre de 26/10/2025. Causa
  raiz: `contabil_eua`/`_ttm_tag_sec` (utils/fetch_guidance.py) só olhava o XBRL (10-Q/10-K) da SEC; quando o
  10-Q formal do trimestre mais recente ainda não tinha sido protocolado, a janela dos "últimos 4 trimestres"
  simplesmente pegava os 4 últimos QUE EXISTEM no XBRL - que podem ser mais antigos que o trimestre já salvo
  em contabil_sec.json - sem erro nem aviso (o status voltava "ok", só com a janela errada). O estado anterior
  (9,31, com a fonte "NVIDIA press release 3T FY2027 (GAAP)") nunca foi produzido por esse código: foi editado
  à mão num ciclo anterior (commits "Atualização automática TTM" / "Trava regras do TTM automático"), sem a
  lógica real ter esse fallback - por isso o robô "esqueceu como" reproduzir esse valor na execução seguinte.
  Corrigido: `contabil_eua` agora recebe o registro já salvo do ticker (`anterior`) e, se o fim do trimestre
  mais recente que o XBRL devolveria for mais antigo que o já salvo, tenta achar esse trimestre no press
  release/8-K/6-K mais novo (`_trimestre_pendente_gaap`, `extrair_eps_gaap_trimestre`, `extrair_fim_trimestre`
  - mesma hierarquia de fonte já usada no projeto: release no RI > 8-K/6-K na SEC > CVM/ITR), extrai o LPA GAAP
  (não ajustado) do trimestre e o fim do trimestre ("the third quarter ended October 25, 2026"), e só aceita
  se continuar consecutivo (80-100 dias) ao resto da janela - `lpa_ttm_sec`/`_ttm_tag_sec` ganham um parâmetro
  `extra_total` para essa única fonte. Achando, grava com a fonte do press release citada no próprio
  trimestre (nunca "SEC 10-Q/10-K", que esse trimestre não tem). SEM achar nada, MANTÉM o valor anterior
  (status "mantido_ttm_anterior", mesmo padrão MANTIDO_TTM_ANTERIOR já documentado acima para o TTM diário)
  em vez de aceitar uma janela mais antiga - nunca retrocede. `tests/test_fetch_guidance.py` tem o cenário
  exato da NVDA (fixture com os dados reais do press release e do XBRL) provando que, sem a trava, o XBRL
  sozinho reproduz os 7,91 do bug, e que a lógica corrigida chega em 9,31 com a fonte certa.
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
  só que como Secret do Streamlit Cloud - são dois lugares diferentes, cada um com o seu Secret. `app.lpa_anual_eua`
  devolve a lista e o motivo (diagnóstico: "ticker da B3", "SEC sem e-mail configurado...", "SEC não encontrou
  esse ticker", "SEC sem o dado...", "SEC falhou (...)" ou "SEC OK"); quando a SEC não é usada (ticker dos EUA),
  o motivo aparece na nota do card "Lucro por ação" (ex.: "Yahoo Finance (SEC não usada: SEC sem e-mail
  configurado...)"), pra diagnosticar na própria tela sem precisar olhar o código ou os logs.
  Emissora estrangeira (ex. ASML): arquiva 20-F na SEC, não 10-K, e o LPA fica em EUR/shares, não USD/shares -
  `lpa_anual_sec` aceita 20-F/20-F/A além de 10-K/10-K/A e marca `moeda: "EUR"` nesse caso, junto com o campo
  "anuncio" (data em que a empresa arquivou/anunciou aquele resultado na SEC - a 20-F sempre repete 2-3 anos de
  comparativo nos filings seguintes, com o MESMO valor; "anuncio" guarda a data do anúncio ORIGINAL, não a da
  reapresentação mais recente, senão o câmbio ficaria preso ao filing mais novo mesmo pra um ano antigo). Só
  um valor realmente diferente do mesmo ano/moeda (reapresentação de verdade, ex. 10-K/A corrigindo o número)
  troca o "anuncio" pela data dessa correção. `app.lpa_anual_eua` então converte cada ano pra dólar com
  `utils.fetch_guidance.converter_lpa_anual_para_usd`, usando o câmbio EUR→USD da DATA DO ANÚNCIO de cada ano
  (`taxa_cambio_historica_eur_usd`, Yahoo Finance, ticker EURUSD=X, fechamento do dia ou do último pregão
  anterior) - é a cotação que valia quando aquele número saiu, nunca o câmbio de hoje aplicado retroativamente
  nem o do fim do ano fiscal (a empresa não converte pelo câmbio de 31/12), o que distorceria Graham/médias/
  Faixa do Conservador de anos passados. Ano sem câmbio encontrado fica de fora da série (nunca mistura euro
  com dólar). Com conversão, a fonte da tela vira "SEC 20-F, lucro por ação diluído (GAAP) - convertido de
  euro pelo câmbio da data do anúncio de cada ano, Yahoo Finance". O mesmo vale pro guidance TRIMESTRAL em euro (ex. ASML,
  ver acima): o câmbio usado é o da data do anúncio/release (não o de hoje nem o do fim do trimestre).
  `tela/dados.py._pontos_anuais` não corta mais em 4 anos (cortava sempre, pensando só no limite do Yahoo - com
  a SEC disponível, isso travava "Média 5/10 anos" em "Sem dado" mesmo com histórico de sobra); o corte de ~4
  anos continua só onde é pra valer (crescimento de lucro/receita do Lynch, que quer a tendência recente, não
  um CAGR de décadas).
  B3 NÃO tem SEC (é só EUA): pra um ticker da B3, `d["lpa_anual"]` vem só do Yahoo (`tk.income_stmt`, que
  normalmente só traz ~3-4 anos) - sem fallback nenhum pra mais anos (não existe "SEC do Brasil" equivalente no
  projeto). **IMPORTANTE, esclarecido em 27/11/2026 porque um usuário achou que era bug do Perplexity**: a
  biblioteca própria (`utils/biblioteca.py`, Perplexity) NUNCA é chamada por este cálculo nem por nenhuma parte
  do app/robôs que leem a tela - `grep -rln "biblioteca" --include="*.py"` fora de `utils/biblioteca.py`/
  `utils/divergencia.py` só acha o próprio workflow `.github/workflows/biblioteca-perplexity.yml` (que grava só
  o campo de exemplo `lpa_atual` em `utils/biblioteca.json`, nunca lido de volta pela tela). Então "Média 5
  anos"/"Média 10 anos"/"P/L Conservador"/"Preço teto conservador" ficarem em "Sem dado" pra um ticker da B3
  com só 3 anos de histórico (ex. BBAS3) NÃO é falha da Perplexity - é simplesmente a fonte real (Yahoo) não
  ter mais anos pra esse ticker, e não ter outra fonte pra completar (diferente dos EUA, que têm a SEC).
  REGRA DE "SEM DADO" (corrigida 27/11/2026, a pedido do usuário): essas 4 linhas (Média 5 anos, Média 10
  anos, P/L Conservador, Preço teto conservador) NUNCA mostram "Sem dado" repetido - só mostra a linha se
  tiver valor; linha sem valor simplesmente some. P/L Conservador e Preço teto dependem matematicamente da
  Média de 10 anos (`pl_conservador = preco / lpa_media_10a`, `teto_conservador = lpa_media_10a * 15`), então
  sempre faltam juntos quando ela falta. Quando um grupo inteiro falta, 1 nota cinza substitui as linhas vazias
  desse grupo (nunca "Sem dado" × 4): "Dados de 5 e 10 anos indisponíveis para este ticker (P/L Conservador e
  Preço teto conservador também dependem da média de 10 anos)." quando faltam os 2 grupos juntos (caso comum,
  ex. BBAS3); "Dados de 5 e 10 anos indisponíveis para este ticker." quando só falta o 1º grupo; "P/L
  Conservador e Preço teto conservador indisponíveis para este ticker (dependem da média de 10 anos)." quando
  só falta o 2º (Média 5 anos presente, mas sem 10 anos completos). `tela/detalhe.js`, dentro do bloco "Lucro
  por ação" (`renderBloco`).
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
  quarter of fiscal year", "for the fiscal Nth quarter year, we expect", "for the Nth quarter of year, EMPRESA
  expects" (ex.: AMD), "EMPRESA expects QN AAAA" (abreviado, sem "quarter" por extenso - ex.: ASML, no resumo em
  bullet no topo do release) e "We expect Nth-quarter AAAA" (composto com hífen, sem abreviar - ex.: ASML, no
  corpo do CEO statement do mesmo release); faixas em "X ± Y", "X to Y", "X, plus or minus Z%" e "between X and Y"
  (ex.: ASML), em dólar ou em outra moeda com o símbolo antes do número (ex.: €14.2 billion, ASML); rótulo de
  receita "Revenue" ou "net sales"/"total net sales" (ex.: ASML); margem em "Approximately X%" ou "between X% and
  Y%" (nesse caso o ponto médio). Nem toda empresa dá guidance de LPA (ex. NVIDIA, AMD e ASML só dão receita/
  margem) nem usa um desses formatos (ex. Apple não dá guidance numérico formal) - sem achar um formato
  reconhecido, o campo correspondente fica "Sem dado" e, sem nada achado, o card simplesmente não aparece (nunca
  trava o ticker como "não validado": isso é só do guidance ANUAL). Não calcula margem líquida por fora (ex.:
  LPA × ações do Yahoo ÷ receita) mesmo quando dá para estimar: o LPA de guidance costuma ser non-GAAP e as
  ações do Yahoo podem não bater com a base da empresa - mostra só o que a empresa realmente divulgou. Grava
  em utils/guidance_trimestral_eua.json; uma tentativa sem sucesso nunca apaga um valor bom já gravado.
  O card fica no fim do bloco de cada modo (`tela/detalhe.js`, `renderBloco`/seção `modo-bloco`) - depois de
  "Lucro por ação" no Conservador, de "Crescimento" no Lynch, de "Movimento curto" no Simons - e aparece nos
  3 modos (é informativo, não depende do método de valuation). A seção `modo-bloco` foi reposicionada no HTML
  pra ficar logo abaixo de "Mínimo, máximo e ponto médio" e acima de "Fundamentos" (antes era a primeira seção
  da tela); como ela não é escondida por modo (diferente de `minmax`, visível só no Conservador/Simons, ou
  `fundamentos`, só no Conservador/Lynch), o guidance trimestral sempre aparece nessa posição relativa, mesmo
  quando "Mínimo, máximo" ou "Fundamentos" ficam escondidos no modo ativo.
  Mostra a mesma bolinha de atualização do card de P/L (🟢 menos de 2h, 🟡 menos de 24h, 🔴 24h ou mais), a
  partir do `atualizado_em` gravado pelo robô (ou, na busca ao vivo, do momento da própria busca).
  Mostra também "Próximo anúncio previsto" quando o Yahoo tiver essa data. Fonte principal:
  `tela/dados.proximo_anuncio_info`, que lê o campo earningsTimestamp/earningsTimestampStart do próprio "info"
  que o app já busca pra qualquer ticker (sem nenhuma chamada de rede extra - mais confiável do que buscar à
  parte: o calendário do yfinance, por exemplo, pode falhar sozinho por instabilidade da Yahoo, mesmo quando o
  "info" tem o dado). `utils.fetch_guidance.proximo_anuncio_eua` (calendário do yfinance) é só o que o robô usa
  (ele não busca "info"/cotação, só documentos da SEC) e serve de alternativa quando o "info" não tiver a data.
  Não vem do documento da SEC (releases de resultado não costumam anunciar a data do PRÓXIMO earnings call) e
  é só informativo; sem a data em nenhuma das duas fontes, o card não mostra essa linha (nunca inventa).
  Moeda: empresa estrangeira em 6-K que divulga em outra moeda (ex. ASML em euro, símbolo "€" antes do número)
  tem receita/LPA convertidos pra dólar antes de gravar/mostrar (`converter_outlook_para_usd`), pelo câmbio do
  Yahoo Finance (ticker EURUSD=X, `taxa_cambio_historica_eur_usd`) NA DATA DO ANÚNCIO/RELEASE (não o de hoje,
  nunca um câmbio fixo no código - ver acima). Câmbio indisponível nessa data: não grava nem mostra o valor em
  euro como se já fosse dólar (moeda errada é pior que "Sem dado" por enquanto) - só tenta de novo no próximo
  ciclo. Convertido, a nota da fonte no card mostra "Convertido de euro pelo câmbio EUR→USD de [data] (Yahoo
  Finance): [taxa]", pra nunca esconder que o número passou por conversão; os valores originais em euro ficam
  guardados (receita_min_eur/receita_max_eur) para quem for conferir.
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
- Contábil 12 meses (B3): tickers de utils/contabil_br_config.json (linha do lucro e nome da fonte; hoje BBAS3, linha
  "Lucro Líquido Contábil", e PETR4, linha "Lucro líquido (Prejuízo) - Acionistas Petrobras"). REGRA 1 vale para a B3
  também: a linha principal ("linha") é sempre a do lucro CONTÁBIL; "linha_ajustado" (ex.: "Lucro Líquido Ajustado",
  "Lucro Líquido sem Eventos Exclusivos") é lida só como nota (lucro_ajustado_12m / lpa_ajustado). "acoes" + "fonte_acoes"
  no config (número oficial ON+PN do ITR/6-K) ganham do Yahoo, que para a PETR4 devolve só a PN (5,45 bi em vez de
  12,89 bi). O robô lê o release de
  resultados de cada trimestre na CVM (trimestre = o último encerrado antes da entrega), extrai o lucro do trimestre
  (frase e tabela; divergência > 3% = sem confiança; frase com acumulado/ano/semestre/9M/12M é descartada; tabela só
  pela coluna trimestral; sem unidade escrita, decide pela frase, e "3,9" sem frase é ambíguo; lucro < R$ 1 mi, ex. 0,00,
  é leitura inválida e tenta o próximo documento; em release/Relatório de Análise Gerencial a tabela vence sempre e a
  frase só ajuda na unidade; PDF com 3 tentativas e leitores pypdf → pdfplumber → PyMuPDF; trimestre que não abre usa a
  coluna dele na tabela de um release posterior; log "BBAS3 3T26: frase=... tabela=... divergência=... gravou=..."), soma 4 trimestres consecutivos e grava em utils/contabil_br.json:
  Coluna do trimestre (issue #26): o cabeçalho de trimestres é a maior janela SEM repetição que contém o trimestre
  (`colunas_do_cabecalho`) - o texto do PDF da Petrobras grudava um rótulo solto antes do cabeçalho ("2T26 3T26 2T26
  3T25") e o robô lia a coluna do trimestre anterior; entre os grupos candidatos vale o mais completo (um pedaço solto
  como "4T25 (%)" das colunas de variação não é cabeçalho). TRAVA: o release de T repete T-1 como comparativo; se esse
  comparativo diverge mais de 2% do T-1 lido no próprio release de T-1, não grava ("coluna suspeita").
  FONTE OFICIAL DA B3 (issue #26): release de resultados > CVM. O ttm_diario (ttm_auto.py) usa o contábil do release
  (contabil_br.json, base contábil) e guarda a DRE consolidada dos dados abertos da CVM só como conferência (lucro_cvm,
  divergencia_cvm). Ex.: BBAS3 12m = R$ 12,45 bi (Análise do Desempenho), CVM R$ 11,02 bi só nota.
  LPA = soma ÷ ações (oficial do config; senão Yahoo). Sem conseguir ler: "Yahoo - pendente", nunca número inventado; pendente não apaga valor
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
- CONSERVADOR: a "Faixa de preço" (faixa inferior/neutra/superior e o badge de decisão do topo) usa
  valuation, não a faixa histórica de 52 semanas. Preço Teto = ÂNCORA = preço médio dos últimos 1 ano (fechamento
  semanal, igual à `media_fechamentos` de 52 semanas). Oportunidade até 0,70 × Teto (margem de segurança de 30%);
  Neutra alargada até 1,30 × Teto (30% ACIMA do teto - não vira "Cara" só por passar um pouco da âncora); Cara
  acima disso (`decidir_estado_conservador` aceita `caro_acima` opcional, padrão 1,30 × teto). Substituiu o
  Número de Graham (LPA médio × VPA): o preço histórico quase nunca falta (diferente de LPA/VPA, que ficavam
  "Sem dado" com frequência, e cuja mediana de anos longos pode ficar presa a um regime de mercado antigo da
  empresa, ex. MU antes do supercycle de IA). Sem 1 ano de histórico de preço (ticker recém-listado): sem teto -
  a tela cai para a faixa de 52 semanas como alternativa visual. Nunca tem teste histórico - mas isso não aparece
  mais na tela como selo (o card de decisão não mostra mais selo nem alerta, ver regra da Faixa de 52 semanas
  acima). Médias de 3 anos (margem de 40%: limite = 0,60 × média) e 5 anos (margem
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
  e os próprios números) usam a mesma posição já afastada pelo `afastar()` - nunca a posição linear crua: senão,
  quando os pontos ficam muito próximos no preço real (ex. zona de oportunidade estreita), a cor mudaria num
  lugar e o número escrito em cima diria outro, parecendo que a faixa verde "não chega" onde o próprio número
  diz que chega. O gap mínimo entre dois rótulos não é um valor fixo: escala com a largura real de cada um
  (estimada pelo nº de caracteres, convertida em % da largura do card) - um ativo com preço na casa dos milhares
  (ex. "1.999,96") tem rótulo bem mais largo que um de preço baixo (ex. "14,65"), e um gap fixo (17 pontos, bom
  só pros casos curtos) deixava os números colados/sobrepostos nesses ativos (ex.: fim da Zona Cara colado na
  borda direita da régua). `afastar(posicoes, folgas, folgaEsq, folgaDir)` recebe a folga de cada ponto (metade
  da largura do próprio rótulo, já que é centralizado) e a folga extra nas pontas (rótulos de mínima/máxima da
  régua, que são ancorados na borda, não centralizados). O "Você está aqui" (bolinha do preço) passa pela MESMA
  transformação (interpolação entre a posição crua e a já afastada de cada ponto, com 0%/100% como âncoras) -
  senão a bolinha ficaria "presa" perto do traço errado sempre que o preço real estiver perto de um ponto que
  foi empurrado pro afastar() (ex. preço de R$14,30 bem perto do limite de 3 anos de R$14,65 apareceria colado
  no traço do limite de 5 anos, bem mais longe). Sem texto explicativo embaixo
  da régua (só os cartões Faixa inferior/neutra/superior acima já explicam os cortes). O
  PONTO DE ENTRADA (o texto "Faixa neutra a partir de") é sempre o alvo fixo de 30% sobre a âncora de 1 ano -
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
  BUG CORRIGIDO (auditoria 26-27/11/2026, 3 rodadas até fechar de verdade): Neutro e Caro SEMPRE descrevem o
  mesmo valor (a mesma variável zCara) - nunca 2 valores diferentes, mas eram 2 linhas tracejadas DIFERENTES
  desenhadas na MESMA altura ("Faixa neutra até X" e "Faixa superior acima de X"), e a regra de afastar linhas
  próximas empurrava a segunda pra baixo, fazendo "Faixa superior" parecer visualmente ABAIXO de "Faixa
  neutra" - o contrário do que elas significam, pra qualquer ticker. CORREÇÃO FINAL (as 2 primeiras tentativas
  foram rejeitadas - ver histórico abaixo): são 2 CONCEITOS, cada um na SUA PRÓPRIA linha, em ALTURAS
  diferentes - nunca na mesma posição. "Faixa superior acima de X" fica na linha de zCara (vermelho, é
  literalmente onde a zona superior começa). "Faixa neutra X a Y" (o INTERVALO completo, não só o teto) fica
  no MEIO da própria zona neutra (ponto médio entre zOport e zCara, cinza `#aab4c6`) - ela não tem uma única
  linha de fronteira própria (é delimitada por "Faixa inferior 1" embaixo e "Faixa superior" em cima, que já
  existem), então o texto fica solto no meio da faixa, sem "/" juntando 2 conceitos na mesma linha.
  HISTÓRICO DAS 2 TENTATIVAS REJEITADAS (documentado para não repetir o erro): 1ª tentativa mesclou as 2
  linhas em 1 só com a faixa completa ("Faixa neutra Y a X · Faixa superior acima de X") na altura de zCara -
  rejeitada porque, estando na altura do TETO, dava a impressão de que a Faixa neutra inteira ficava ACIMA da
  Média 200d sempre que a MM200 estivesse DENTRO da própria faixa neutra (ex. MM200 776,48 dentro de
  477,51-886,81). 2ª tentativa só trocou pra "Faixa neutra até / Faixa superior acima de X" (um "/" juntando
  os 2 conceitos na mesma linha, só o teto) - rejeitada por ainda juntar 2 conceitos com "/" em vez de 2
  linhas de verdade, e por não mostrar o intervalo completo da Faixa neutra como pedido originalmente.
  3º BUG CORRIGIDO (mesma auditoria): adicionar "Faixa neutra" como uma linha própria (concorrendo por espaço
  vertical com Faixa superior/Média 200d/Faixa inferior 1/2/3 - até 6 linhas no mesmo gráfico) podia empurrar
  a última linha da cascata (ex. "Faixa inferior 3" do PETR4) pra baixo do limite visível do gráfico
  (`yPlot`, onde o `ctx.clip()` corta) - ela sumia da tela sem nenhum aviso. Corrigido: depois de afastar as
  linhas próximas, se a última ainda passar do limite visível, desloca TODAS pra cima juntas (mantém a
  distância entre elas) até a última caber.
  4º BUG CORRIGIDO (mesma auditoria): a folga mínima entre linhas (`FOLGA_MIN_LINHA`) era 12px, baseada só na
  conta de distância entre os PONTOS das linhas - mas o texto de verdade (fonte 10.5px, `textBaseline:
  'middle'`) ocupa mais altura que isso, e em celular (canvas de 280px, bem mais baixo que desktop) "Faixa
  inferior 2" e "Faixa inferior 3" podem ficar a só ~11px uma da outra (ex.: limite3a/limite5a reais da MU,
  181,29 e 103,89) - a regra "passou" (>= 12px não disparava o afastamento) mas o texto já aparecia colado/
  ilegível. Testado com dados reais da MU e PETR4 (Playwright, viewport de celular, dados obtidos de
  `calculos.calcular`+`tela.dados.montar` ao vivo, não um exemplo fixo): 16px e 20px ainda deixavam o texto
  colado; 24px foi o primeiro valor testado que separa de verdade. `FOLGA_MIN_LINHA` subiu de 12 para 24.
  NÃO É BUG (checado e descartado): um print de celular mostrou "103.89" com ponto em vez de vírgula - achado
  que o texto de verdade desenhado no canvas (confirmado interceptando `fillText` via Playwright) É
  "103,89", com vírgula; o "ponto" era só um artefato visual do ambiente de teste (a fonte Google "Inter" não
  carrega sem rede, e a vírgula da fonte substituta fica difícil de distinguir de um ponto nesse tamanho de
  fonte/zoom de print) - nunca existiu no código nem na tela de verdade.
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
  automaticamente na régua de números (função `afastar`, gap mínimo escalado pela largura real de cada rótulo -
  ver acima); o nome da zona
  (Oportunidade/Neutra/Cara) some quando a coluna fica estreita demais pra caber o texto sem quebrar palavra -
  regra geral, vale pra qualquer ativo, não só pra casos específicos. LYNCH
  ignora a faixa e usa só a
  MM200: Oportunidade = MM200 −10% a +5%;
  abaixo de −10% = "Bem abaixo da MM200" (azul, separado, ainda COMPRAR); Neutro = +5% a +15%; Caro = +15% ou mais;
  ponto de oportunidade = MM200 × 1,05.
- "Tendência e força": os cards de Direção/Força da tendência (distância preço÷MM200) e Força (IFR 14 dias)
  ficam num único bloco. Cada um mostra, além do valor de hoje (bolinha cheia), uma bolinha vazada marcando
  onde estava 7 pregões atrás (`calculos.calcular` → `dist_mm200_7d`/`ifr_7d`, calculados em `indicadores()`,
  não um valor aproximado) - com menos de 8 pregões de histórico, fica "Sem dado" (não mostra a bolinha vazada
  nem o rótulo, nunca inventa). As 2 barras usam o MESMO padrão de marcador: sempre as 2 bolinhas visíveis,
  cada uma com seu valor na posição do seu próprio ponto (nunca um valor empilhado embaixo do outro) - valor
  de hoje em azul, em cima da régua, direto acima da própria bolinha cheia (`marca-cima so-valor`); "7 dias
  atrás" (rótulo) e o valor (negrito) em 2 linhas, em cinza pequeno, embaixo da régua, direto abaixo da própria
  bolinha vazada (`marca-baixo`, `<b>` pro valor) - o rótulo deixa claro que aquele número é de 7 pregões
  atrás, não do dia de hoje nem do próprio 0%/ponto neutro da régua. As 2 bolinhas (hoje e 7 dias atrás) nunca
  podem ficar tão perto a ponto de uma esconder a outra: `afastarBolinhas()` afasta a posição visual das duas
  (e dos valores acima/abaixo, que seguem a mesma posição da sua bolinha) só o mínimo necessário - raio de
  cada bolinha (hoje 18px cheia, 7 dias 10px vazada) mais um respiro - preservando a posição real quando já
  há espaço de sobra; com valores iguais ou muito próximos, as 2 continuam sempre visíveis lado a lado. O
  rótulo "7 dias atrás" embaixo da bolinha vazada (nas 2 barras) tem respiro extra (margem maior que o padrão
  de `.marca-baixo`) pra não ficar colado na bolinha. Os
  dois textos de leitura (abaixo da barra de Força da tendência) começam direto pelo
  percentual, com 1 casa decimal (mesma precisão da segunda frase, pra nunca mostrar "20,94%" numa linha e
  "26,5%" na outra), sem rótulo ("Perdeu força"/"Alta"/"Precisa subir"/"Cai" tirados): "20,9% abaixo da média
  de 200 dias." e "26,5% para voltar à média." - sem repetir a mesma distância numa segunda frase ("Preço X
  está Y% abaixo da média de Z"); logo acima desses textos, uma frase fixa lembra o valor da média de 200 dias
  e que ela é o ponto 0% da régua.
  O título/badge "Direção da tendência" e a evolução abaixo usam REGRA TRAVADA, à parte dos limiares de cor da
  régua "Força da tendência" (-10/+10/+20, só pras zonas Perdeu força/Equilíbrio/Alta leve/Forte da própria
  régua): distância < -5% = "Baixa" (vermelho); entre -5% e +5% = "Equilíbrio" (cinza); > +5% = "Alta" (verde).
  PROIBIDO usar "Perdeu força"/"Alta leve"/"Forte" como Direção - são só os nomes das zonas da régua, uma coisa
  diferente (bug corrigido: o título já chegou a usar essas zonas como se fossem a Direção, mostrando "Perdeu
  força" onde devia mostrar "Baixa"). Na régua de Força da tendência, só o RÓTULO de texto da zona vermelha
  (a mais à esquerda) é "Baixa" em vez de "Perdeu força" - mudança só do texto desse rótulo, a cor/posição/
  limite de -10% da própria zona continuam os mesmos. Evolução da Direção da tendência: logo abaixo do título,
  2 linhas em cinza pequeno, só quando há os 7 pregões de histórico (`dist200d7d`) - nunca inventa, com a MESMA
  regra travada (Alta/Baixa/Equilíbrio, limiar ±5%) do título. 1ª linha: "7 dias atrás: [Direção 7 dias]
  ([valor 7 dias]) → Hoje: [Direção hoje] ([valor hoje])" (ex.: "7 dias atrás: Baixa (-12,86%) → Hoje: Baixa
  (-17,01%)"). 2ª linha, automática, NUNCA usa a sigla "p.p." (pouca gente conhece): manteve a direção e o
  valor absoluto cresceu = "Continuou em [direção, minúsculo] e piorou: de [valor 7 dias] para [valor hoje]
  acima/abaixo da média." (palavra acima/abaixo pelo SINAL real de hoje, não pelo nome da direção - a faixa
  "Equilíbrio" pode ter valor levemente negativo ou positivo); manteve e o valor absoluto caiu = mesma forma
  trocando "piorou" por "melhorou"; trocou de direção = "Virou de [direção 7 dias] para [direção hoje]: de
  [valor 7 dias com sinal] para [valor hoje com sinal]." (usa o sinal em vez de acima/abaixo porque a
  referência muda de lado) - mesma regra pra qualquer ativo, sem mudar cor/layout da barra.
  Os nomes das zonas da régua de Força da tendência (diferente da Direção, ver acima): "Baixa" (vermelho) |
  "Equilíbrio" (cinza) | "Alta leve" (verde-claro) | "Forte" (verde-forte) - usava antes "Leve compra" e
  "Compra forte" (renomeados pra padronizar com a Força/IFR) e "Perdeu força" no rótulo vermelho (virou "Baixa"
  pra não confundir com a Direção, ver acima).
  Zonas da barra de Força da tendência: escala fixa de -30% a +30% (só estica além disso se a distância real
  passar desses limites) - abaixo de -10% é "Baixa"; de -10% a +10% é "Equilíbrio" (com a própria média
  de 200 dias, 0%, marcada no meio dessa faixa); de +10% a +20% é "Alta leve"; acima de +20% é "Forte".
  Quando a régua estica bem mais pra um lado só (ex. distância de -38% faz a régua ir de -50% a +30%, bem
  mais aberta à esquerda que à direita), os números do meio (-10%/0%/+10%/+20%) usam a mesma técnica de
  `afastar()` da Faixa de preço: cada um ganha a folga da largura real do próprio texto (+ respiro) e só se
  afasta da borda o mínimo necessário, pra nunca colar no número da ponta que NÃO esticou (ex. "+20%" colado
  em "+30%") - os TRAÇOS de cor na régua continuam na posição exata, só os números escritos acima se ajustam.
  `largContainer`/`largContainerT`/`largContainerF` (largura usada pra converter pixel em %, nessas contas e
  nas de `afastarBolinhas`) descontam, além do padding do `.card` (14px × 2), a borda do card (1px × 2) e a
  margem lateral da própria linha (`.marca-cima`/`.regua` têm `margin` de 6px × 2) - sem contar a borda/margem
  da linha, a largura calculada ficava maior que a real e os rótulos saíam mais próximos do que deveriam.
  A barra de Força (IFR, título "Força - RSI") tem 5 zonas, não 4, no PADRÃO DE MERCADO (regra travada):
  "Muita venda" (vermelho, <30) | "Venda" (âmbar, 30-40) | "Neutro" (cinza, 40-60, com 50 marcado com um traço
  na própria régua, além dos traços de 30/40/60/70 - mesma frase de referência da Força da tendência, adaptada:
  "50 é o ponto neutro da régua acima") | "Compra" (verde-claro, 60-70) | "Muita compra" (verde-forte, >70).
  Os limiares são 30/40/60/70 (não 20/40/60/80 - régua já teve esse limiar errado, bug corrigido porque ficava
  desalinhada do padrão de mercado de RSI).
  O rótulo de cada zona fica centralizado no MEIO visual da própria faixa de cor (ex.: "Equilíbrio"/"Neutro"
  sempre em cima do ponto central da faixa cinza - 0% na barra de tendência, 50 na de IFR; as zonas da ponta -
  "Baixa"/"Muita venda" à esquerda, "Forte"/"Muita compra" à direita - ficam ancoradas na borda, não
  centralizadas), calculado como o ponto médio exato dos limites da zona
  (`position:absolute;left:[meio]%;transform:translateX(-50%)`) - essas 2 barras não usam a classe `.zonas-rot`
  (grade CSS compartilhada com SIMONS/Lynch/Conservador), porque o `gap` da grade deixava o nome fora do centro
  real da faixa; a mudança é só nessas 2 barras, pra não arriscar as outras.
  O texto de leitura da Força (destaque abaixo da régua de IFR) segue o MESMO padrão "de X para Y" da evolução
  da Direção da tendência, pra mostrar a evolução em vez de só o estado de hoje - zona calculada com as MESMAS
  5 faixas/limiares da régua logo acima (Muita venda <30 / Venda 30-40 / Neutro 40-60 / Compra 60-70 / Muita
  compra >70; NÃO usa limiares diferentes dos mostrados na própria barra, tipo o antigo Sobrecomprada/
  Sobrevendida 70/30 OU o esquema de limiares 20/40/60/80 - um texto com zona diferente da cor/posição da
  bolinha na régua já foi bug reportado e corrigido mais de uma vez) pro valor de hoje e pro de 7 dias atrás
  (`forca7d`): mesma zona e subiu = "[Zona]. Subiu de [7 dias] para [hoje]."; mesma zona e caiu = "...Caiu de
  [7 dias] para [hoje]."; zona diferente = "Virou de [zona 7 dias] para [zona hoje]: subiu/caiu de [7 dias]
  para [hoje]." - o verbo entra TAMBÉM na frase de "Virou de..." (antes só dizia "de X para Y" sem verbo; ex.:
  "Virou de Venda para Muita venda: caiu de 32 para 24."). Sem `forca7d` (menos de 8 pregões de histórico):
  mantém uma frase descritiva só da zona de hoje (Muita compra: "Subiu rápido demais."; Compra: "Pressão de
  compra."; Muita venda: "Caiu rápido demais."; Venda: "Pressão de venda."; Neutro: "Sem pressão de compra nem
  de venda."), nunca inventando uma comparação sem dado.
  NÃO é bug o valor de hoje ficar na mesma zona de 7 dias atrás mesmo perto de um limite (ex.: valor caindo de
  35 pra 31, ambos entre 30 e 40 - "Venda. Caiu de 35 para 31.", não "Virou de..."); "Virou de..." só aparece
  quando o valor de hoje realmente cruza um dos limiares 30/40/60/70. Teste travado: RSI 24 cai em Muita venda;
  RSI 31 continua em Venda; RSI 70 é Compra; RSI 71 já é Muita compra.
- Para conferir o que o Yahoo devolve para um ticker: Actions -> "Diagnóstico Yahoo (só leitura)".
- Backtest: 5 anos por padrão; todo o histórico só na escala "Máx.", com aviso.
- DADOS FIXOS (BR + EUA, Issue #29, `utils/dados_fixos.py`): ações em circulação, lucro e dividendo
  de 12 meses NUNCA vêm do Yahoo - só da fonte oficial (release/ITR/DFP na CVM pra B3, SEC EDGAR
  pros EUA). Arquivo `utils/dados_fixos.json` (mesmo padrão de `contabil_br.json`/`contabil_sec.json`:
  ticker -> dicionário), gravado uma única vez por ticker e NUNCA recalculado todo dia - só a cotação
  do dia entra de novo em cada cálculo, buscada pela própria tela (Yahoo), nunca pelo módulo.
  Lista SOB DEMANDA: não há nenhum ticker pré-cadastrado. `obter(ticker, hoje, cotacao)` é o ponto
  de entrada único: (1) ticker já em `dados_fixos.json` -> usa o salvo e só recalcula com a
  `cotacao` recebida; (2) ticker novo -> busca 1x na fonte oficial, grava e calcula; (3) não achou
  na fonte oficial -> NÃO cria a entrada e devolve {"status": "nao_encontrado", "mensagem":
  "Ticker não encontrado na fonte oficial."} (a tela mostra essa mensagem, nunca um número chutado).
  Fontes de fato usadas (sejamos honestos sobre o mecanismo): B3 = documentos entregues à CVM (IPE,
  `utils.fetch_guidance.documentos_cvm`) - hoje só esse passo (release/ITR/DFP é o próprio
  documento entregue pela empresa; a B3 como 2º passo ainda não foi implementada, ver limitação no
  PR). Ações = ON + PN + Units achados na capa do documento ("Composição do Capital Social"),
  somados (NUNCA só ON) - `extrair_acoes_br`, regex sobre o texto do PDF (reaproveita
  `fetch_guidance.texto_do_pdf`); sem nenhuma classe encontrada, o ticker não é criado. Lucro = soma
  dos últimos 4 trimestres consecutivos lidos no release de resultados (reaproveita
  `fetch_guidance.ler_lucro_trimestre`, linha "Lucro Líquido" por padrão - frase e tabela, mesma
  lógica de divergência/unidade do contábil 12m da B3); menos de 4 trimestres consecutivos = não
  cria. Dividendo dos últimos 12 meses (Issue #31, já em R$ por ação - nunca o valor total
  distribuído pela empresa, que precisaria ser dividido pelas ações para comparar com a cotação):
  soma dos mesmos 4 trimestres consecutivos do lucro, por 2 jeitos possíveis, tentados nessa ordem
  (nunca o Yahoo): (a) a própria tabela de destaques do release/relatório de resultados já lido
  para o lucro (`dados_fixos.extrair_dividendo_tabela`, mesma técnica de colunas por cabeçalho de
  `ler_lucro_trimestre`/`colunas_do_cabecalho`, mas sem multiplicador de milhões/bilhões - a linha já
  vem em R$ por ação, ex. BBAS3 "JCP/Dividendos por Ação - R$ 0,07 0,16 0,04..."); (b), só para os
  trimestres que (a) não achou, um documento separado de Fato Relevante/Aviso aos Acionistas sobre
  remuneração ao acionista (`fetch_guidance.documentos_dividendo_cvm`, filtro próprio por
  "remuneração aos acionistas"/dividendo/JCP/juros sobre capital próprio/proventos - documentos que
  `documentos_cvm`, filtrado para resultado/projeção, não lista), lido em texto corrido
  (`dados_fixos.extrair_dividendo_fato_relevante` - "Valor a ser pago: R$ X por ação" ou
  "equivalente a R$ X por ação"; o trimestre vem da própria frase, pela data do balanço ("declarada
  com base no balanço de 30 de setembro de 2026" -> 3T26) ou, no anúncio do 4º trimestre/exercício,
  pelo ordinal ("relativa ao quarto trimestre de 2025" -> 4T25); ex. PETR4, que não tem a tabela por
  ação no release, mas tem esse Fato Relevante a cada trimestre). Só grava `dividendo_12m` com os 4
  trimestres (mesmos do lucro) completos pelos 2 jeitos juntos; faltando 1 ou mais, `dividendo_12m:
  null` e "Sem dado" na tela, nunca inventado (nunca mistura com o Yahoo, nunca estima pelo valor
  total ÷ ações do Yahoo, que poderia usar uma base de ações diferente da declarada pela empresa).
  EUA = SEC EDGAR, XBRL companyfacts (`SEC_DADOS/api/xbrl/companyfacts/CIK.../json`, os mesmos
  fatos estruturados que vêm dos 10-Q/10-K - não precisou de Investor Relations como 2º passo
  porque a SEC já responde pra qualquer ticker listado). Ações = `dei:EntityCommonStockSharesOutstanding`
  (ou `us-gaap:CommonStockSharesOutstanding` se faltar), o valor mais recente. Lucro = soma dos
  últimos 4 trimestres de `us-gaap:NetIncomeLoss` (mesma técnica de `fetch_guidance.lpa_ttm_sec`:
  trimestre de 3 meses direto do 10-Q; 4º trimestre fiscal = ano do 10-K menos os 9 meses
  acumulados do 10-Q). Dividendo = soma dos últimos 4 trimestres de
  `us-gaap:CommonStockDividendsPerShareDeclared`; sem esse fato na SEC, "Sem dado" (nunca estima
  por `PaymentsOfDividendsCommonStock` ÷ ações, que misturaria bases). Exige o mesmo
  `SEC_CONTACT_EMAIL` do resto do projeto (`fetch_guidance.cabecalho_sec`); sem ele, ticker dos EUA
  não encontrado.
  Fórmulas fixas (não mude): `LPA = lucro_12m / acoes_total`; `P/L = cotacao / LPA`;
  `DY = dividendo_12m / cotacao`; `P/L Médio 12m` = média do P/L de cada um dos últimos 4
  trimestres (cotação de fechamento do trimestre ÷ LPA daquele trimestre) - só calculado quando a
  tela injeta as 4 cotações trimestrais (`pl_medio_12m_fixo`); sem elas, "Sem dado" (nunca cai pra
  um método alternativo, pra não confundir com o P/L médio do card de P/L existente, que é outro
  cálculo). ADR: `LPA_ADR = LPA × fator_adr`, `Dividendo_ADR = Dividendo × fator_adr` - `fator_adr`
  default 1 (não é detectado automaticamente pela SEC; pra um ADR real, ex. PBR = 2, hoje só
  editando `fator_adr` direto em `dados_fixos.json`, à mão - limitação conhecida, ver PR). Lucro e
  cotação nunca se misturam entre moedas (`moeda_resultado` registra em que moeda o lucro/dividendo
  foram divulgados).
  Balanço novo: ao buscar de novo um ticker já salvo, uma checagem LEVE (só a data do documento/
  trimestre mais recente na fonte oficial, sem reler PDF nem recalcular XBRL) compara com
  `data_ultimo_balanco` salvo; mais novo -> a tela mostra o aviso "Balanço novo detectado, atualizar
  dados fixos de [TICKER]?" sem sobrescrever nada sozinho (atualização manual, fora do escopo desta
  issue). `verificar_novo=False` pula essa checagem (ex.: testes, ou pra não bater na fonte oficial
  a cada carregamento de página).
  Na tela (`tela/dados.dados_fixos_tela`, plugado em `montar()` como `dadosFixos`; renderizado em
  `tela/detalhe.js`, card "Dados fixos" logo abaixo de "Fundamentos", card próprio - não substitui
  nem duplica o card de P/L existente, que usa o Yahoo/robô de contábil e tem sua própria lógica de
  Início do ano/Previsão atual/Guidance): mostra sempre Ações, LPA, P/L Atual, P/L Médio 12m,
  Dividendo Anual, DY, Fonte + Data do balanço, e a conta de cada indicador embaixo (`contas`, ex.
  "LPA: 140,40 / 12,89"). Ticker fora da fonte oficial mostra só a mensagem "Ticker não encontrado
  na fonte oficial." (sem o card de indicadores). `app.dados_fixos_fonte(ticker)` é cacheado 1 dia
  (ações/lucro/dividendo só mudam com balanço novo - não precisa bater na CVM/SEC a cada refresh);
  a cotação do dia (já buscada pela tela, Yahoo) entra separadamente em `montar()`, nunca pelo
  módulo de dados fixos.
  P/VP, Payout e ROE (Issue #35): mesmo arquivo `dados_fixos.json`, mesmo ticket único por balanço -
  3 campos novos, `patrimonio_liquido` (BR e EUA) e as 2 fórmulas que usam ele. `patrimonio_liquido`
  é um valor de BALANÇO (estoque, "quanto a empresa tem agora"), DIFERENTE de lucro/dividendo
  (fluxo, somado 4 trimestres) - é sempre o valor do balanço MAIS RECENTE, do MESMO documento que já
  deu `acoes_total`/o último trimestre de lucro (nunca um documento adicional, nunca somado entre
  trimestres - igual a como `acoes_total` já pega o valor mais recente, não uma soma). B3 =
  `extrair_patrimonio_liquido_br`, 2 formas vistas nos documentos da CVM: (a) tabela de destaques
  com colunas por trimestre (ex. BBAS3, "3T25 2T26 3T26 ..."), mesma técnica de
  `ler_lucro_trimestre`/`colunas_do_cabecalho` já usada pro lucro - reaproveitada direto, chamando
  `ler_lucro_trimestre(texto, tri, "Patrimônio Líquido", tabela_vence=True)`; (b) Balanço
  Patrimonial com 2 colunas de DATA, mais recente primeiro (ex. PETR4/Petrobras, "PASSIVO - R$
  milhões 30.09.2026 31.12.2025 ... Patrimônio Líquido 505.631 417.587") - usa a 1ª coluna,
  confirmando que a data bate com o trimestre já identificado para lucro/ações (nunca aceita uma
  data diferente), e a unidade (milhões/bilhões) do próprio cabeçalho da tabela; ignora "Retorno
  sobre Patrimônio Líquido"/RSPL (isso é ROE, não o patrimônio em si). Sem achar em nenhuma das 2
  formas: `patrimonio_liquido: null`, `patrimonio_motivo` explica, nunca estima. EUA =
  `us-gaap:StockholdersEquity` (`_patrimonio_sec`; se faltar,
  `StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest` - companhias com
  participação de não controladores às vezes só têm o segundo), valor no MESMO período/instante
  (`end`) que já deu `lucro_12m`/`acoes_total` - NUNCA somado (é fato de instante/estoque na XBRL,
  diferente de `NetIncomeLoss`, que é de período/fluxo). Fórmulas fixas (não mude):
  `VPA = patrimonio_liquido / acoes_total`; `P/VP = cotacao / VPA`;
  `ROE = lucro_12m / patrimonio_liquido` (os 2 totais - equivale a `LPA / VPA`, já que ambos ÷
  `acoes_total` se cancelam: dá o mesmo resultado goste o jeito que for). `Payout = dividendo_12m /
  LPA`, NÃO `dividendo_12m / lucro_12m` ao pé da letra: `dividendo_12m` já é por ação (Issue #31,
  "em R$ por ação") e `lucro_12m` é o total da empresa (R$, não por ação) - dividir um pelo outro
  direto misturaria as 2 bases (R$/ação ÷ R$ total) e daria uma % sem sentido (ordens de grandeza
  bem diferentes). `dividendo_12m / LPA` é matematicamente a MESMA razão que dividendo TOTAL ÷
  lucro TOTAL (os 2 ÷ `acoes_total` se cancelam), só que com os dados que o módulo já tem - decisão
  tomada ao implementar, documentada aqui e no PR da Issue #35, não uma variação livre da fórmula.
  Sem `patrimonio_liquido`: `P/VP`, `ROE` e `VPA` ficam `null`/"Sem dado" (e `Payout` também fica
  "Sem dado" sem `dividendo_12m` ou sem LPA - mesma regra de "nunca estima" dos outros indicadores).
  Sem selo de favorável/neutro/desfavorável pra esses 3 (decisão, não esquecimento): a regra de
  comparar com uma "média de 12 meses" (ver P/L Médio 12m acima) existe pra indicadores com
  histórico TRIMESTRAL de cotação já disponível (P/L) - P/VP, Payout e ROE precisariam do
  patrimônio líquido de cada um dos últimos 4 trimestres (não só o do balanço mais recente), que a
  Issue #35 não pediu e que exigiria ler/guardar 4x mais dados de patrimônio por ticker. Construir
  esse histórico sem pedido claro seria inventar uma comparação não testada - melhor mostrar só o
  número dos 3 indicadores, sem selo, do que simular uma "média" não validada. Na tela
  (`tela/dados.dados_fixos_tela`, `tela/detalhe.js`, mesmo card "Dados fixos" - não um card novo
  separado, mesmo padrão dos indicadores existentes): 3 linhas novas (P/VP, Payout, ROE) na mesma
  lista do card, com a conta embaixo (ex. "Payout: 4,0000 / 10,8922 = 36,7%", "ROE: 140,40 bi /
  505,63 bi = 27,8%", "P/VP: 42,67 / (505,63 bi / 12,89 bi)") e uma nota explicando a ausência do
  selo de média 12m.
  BUG CORRIGIDO - `dados_fixos.json` não estava versionado (27/11/2026, achado pelo usuário: card
  "Dados fixos" mostrava "Ticker não encontrado" pra BBAS3, que calcula certo em todo o resto da
  tela): diferente dos outros caches do mesmo padrão (`contabil_br.json`, `contabil_sec.json`,
  `guidance_auto.json`, todos rastreados no `main`), `utils/dados_fixos.json` nunca tinha sido
  commitado - ficava só local, então qualquer deploy novo (ou este próprio ambiente) começava sem
  nenhum ticker salvo. NÃO é um problema de fonte: testado de verdade, `buscar_fixos_br("BBAS3",
  hoje)` busca direto nos documentos da CVM e acha ações, 4 trimestres de lucro/dividendo com fonte
  e patrimônio líquido corretamente - só é lento (~270s, porque lê vários PDFs), então sem o
  arquivo persistido cada carregamento frio refaria essa busca inteira. Corrigido rastreando
  `utils/dados_fixos.json` no git (mesmo padrão dos caches irmãos) e gravando o resultado real já
  buscado da CVM pra BBAS3 (igual ao que o módulo gravaria sozinho, só que feito manualmente aqui
  pra não repetir os 270s) - o mecanismo de busca sob demanda do módulo não mudou.
  **DECISÃO: `utils/dados_fixos.py` e `utils/biblioteca.py` continuam SEPARADOS, nunca mesclados.**
  Cogitado (e descartado) migrar "Dados fixos" pra ler de `biblioteca.json` em vez do seu próprio
  arquivo, pra ter "uma única fonte de verdade" - mas são 2 caches de propósitos DIFERENTES, não a
  mesma fonte duplicada: `dados_fixos.json` guarda um registro estruturado de VÁRIOS campos por
  ticker (ações, lucro, dividendo, patrimônio líquido, trimestres com fonte individual), buscado
  DIRETO na CVM/SEC por código dedicado deste módulo; `biblioteca.json` guarda só 1 valor por
  campo/ticker (`{valor, fonte, link, pagina, data_hora}`), vindo da Perplexity como ÚLTIMO recurso
  quando não existe (ainda) uma busca direta dedicada pra aquele dado (ver "Biblioteca própria
  (Perplexity)" acima - a REGRA TRAVADA trata a Perplexity como fallback, não como fonte primária).
  Trocar a busca direta e já funcionando da CVM por uma leitura da Perplexity seria uma REGRESSÃO de
  qualidade de dado, não uma simplificação - e exigiria redesenhar `biblioteca.json` pra guardar
  5+ campos estruturados por ticker, duplicando o que `dados_fixos.py` já faz bem. A ausência real
  de "2 fontes de verdade" pro MESMO dado não existe hoje: nenhum campo de `dados_fixos.json` é
  também buscado por `biblioteca.py` pra nenhum ticker (confirmado - `biblioteca.json` só tem
  `lpa_atual`, um campo que `dados_fixos.py` nem calcula desse jeito). O problema real era só a
  falta de versionamento do arquivo, já corrigido acima.
  BUG REAL CORRIGIDO (27/11/2026, achado comparando "Indicadores" com "Dados fixos" na tela pro
  mesmo ticker, BBAS3): os 2 cards mostravam números diferentes pro MESMO indicador - Ações 5,71 bi
  (Indicadores) vs 2,84 bi (Dados fixos); LPA 2,18 vs 3,0113 - não era "Yahoo vs CVM" nem "ON vs
  ON+PN": eram 2 bugs reais na extração própria de `dados_fixos.buscar_fixos_br`, confirmados
  direto no documento oficial (Demonstrações Contábeis 3T26):
  1. **Ações = free float, não o total emitido**: `extrair_acoes_br` batia no 1º número perto de
     "ordinárias" sem checar o contexto - e esse número era "Ações em circulação (free float) no
     fim do período 2.843.025.842" (49,6% do total), não o "Total emitido" (5.730.834.040) nem o
     "Número médio ponderado de ações" (5.709.745.992, a base que a própria BBAS3 usa pro LPA
     oficial) - os 2 batem com "Indicadores" (Yahoo), que estava CERTO. Corrigido: `_primeiro_total`
     pula qualquer match cujo contexto (antes do número E entre a palavra-chave e o número, na
     MESMA linha) tenha "circulação"/"free float"/"tesouraria"/"em poder de", procurando um match
     melhor - nunca aceita um subconjunto como se fosse o total.
  2. **Lucro = linha genérica errada num trimestre**: `buscar_fixos_br` usava sempre a linha
     genérica "Lucro Líquido" (nunca `utils/contabil_br_config.json`, que já tem "Lucro Líquido
     Contábil" pra BBAS3) - testado direto no documento do 4T25: "Lucro Líquido" bate 1,079 bi
     (uma linha diferente/errada), "Lucro Líquido Contábil" bate 4,972 bi (a certa, confirmada em
     `utils/contabil_br.json`). Isso puxava o lucro_12m todo pra baixo (8,56 bi em vez de 12,45 bi).
  **CORREÇÃO ARQUITETURAL, não só os 2 regexes**: em vez de corrigir as 2 extrações em paralelo (e
  arriscar divergir de novo no futuro, já que são 2 pipelines independentes lendo os MESMOS
  documentos da CVM), `buscar_fixos_br` agora REUSA `utils/contabil_br.json` pra ações e lucro
  quando o ticker já está configurado em `utils/contabil_br_config.json` com status "ok"
  (`_contabil_br_configurado`) - só dividendo e patrimônio líquido (que contabil_br.json não
  guarda) continuam extraídos aqui, pros MESMOS 4 trimestres já resolvidos. Sem configuração
  (ticker novo), cai pra extração própria - corrigida pros mesmos 2 bugs: `extrair_acoes_br` com o
  filtro de contexto acima, e a linha de lucro usa a configurada em `contabil_br_config.json`
  quando existir (mesmo sem `contabil_br.json` ainda "ok" pra esse ticker), senão "Lucro Líquido"
  genérico como antes. `fonte_oficial`/`tipo_acao` deixam claro quando o número veio reusado
  ("reusado de contabil_br.json, Issue #26"). Testado ao vivo: BBAS3 agora bate Ações 5,71 bi e
  LPA 2,18 nos 2 cards. `tests/test_dados_fixos.py` tem testes pros 2 bugs (`extrair_acoes_br`
  ignorando free float/tesouraria) e pro reuso (`_contabil_br_configurado`,
  `test_buscar_fixos_br_reusa_contabil_br_json_pra_acoes_e_lucro`,
  `test_buscar_fixos_br_fallback_usa_a_linha_configurada_nao_a_generica`); a fixture `BBAS3_REAL`
  (que documentava, errado, uma teoria de "grupamento de ações" pra explicar a divergência) foi
  corrigida pros valores reais (5,71 bi / 12,45 bi) - a teoria do grupamento nunca aconteceu, era
  só os 2 bugs acima.
  **DIVIDENDO: 2 métodos diferentes, não um bug** - continuam separados de propósito: "Indicadores"
  (card Dividendo anual, Yahoo) soma os dividendos efetivamente PAGOS nos últimos 365 dias corridos
  (por data de pagamento); o valor DECLARADO na CVM (4 últimos trimestres da tabela do release, via
  `buscar_fixos_br`) é mostrado junto, no mesmo card. As datas de declaração e pagamento não
  coincidem exatamente (BBAS3: R$0,66 pago vs R$0,61 declarado, ~8% de diferença, dentro do
  esperado) - a tela deixa isso explícito (sub-texto "pago 365 dias · declarado R$X (CVM)" e nota
  cruzada no card "Dividendos" do bloco único), em vez de dar a entender que é a mesma conta com
  resultados diferentes.

- **"Dados fixos" REMOVIDO como bloco visual próprio, unificado em "Indicadores" (27/11/2026)**:
  os 2 blocos mostravam números parecidos pro MESMO indicador (Ações, LPA, P/L) em cards
  separados, o que já tinha causado confusão e um bug real (ver acima) - decisão: só "Indicadores"
  mostra esses números pra qualquer ticker, nunca mais 2 blocos concorrentes. `utils/dados_fixos.py`
  (`buscar_fixos_br`) **não foi tocado nem deletado** - continua a mesma camada de dados interna,
  reusando `contabil_br.json`/`contabil_br_config.json` (ver correção acima); `tela/dados.montar()`
  continua chamando `dados_fixos_tela()` e gravando o resultado em `d.dadosFixos` (a cotação do dia
  só recalcula ali, nunca no módulo) - só que agora NADA renderiza a seção própria "Dados fixos":
  `tela/detalhe.js` não tem mais a IIFE `DadosFixos`, e `tela/detalhe.html` não tem mais a
  `<section id="dados-fixos">`. Os campos que só existiam lá e não tinham equivalente em
  "Indicadores" migraram pra dentro do mesmo card (`tela/detalhe.js`, IIFE `Indicators`):
  - "Ações em circulação" já existia em Indicadores (vinha de `acoes_oficiais()`/`contabil_12m()`,
    um caminho PRÓPRIO que também já lê `contabil_br.json` - por isso os números já batiam antes
    desta mudança, ver correção acima) - só ganhou a fonte CVM + data do balanço na dica.
  - "Lucro líquido (12 meses)" é um card NOVO em Indicadores (não existia fora de "Dados fixos") -
    `d.dadosFixos.lucro12m`, com "declarado na CVM" e a fonte+data completas na dica.
  - Dividendo anual (Yahoo, pago) ganhou o valor declarado (CVM, `d.dadosFixos.dividendo12m`) como
    sub-texto e nota cruzada na dica - ver "DIVIDENDO" acima.
  - O aviso "Balanço novo detectado" (quando a CVM tem um balanço mais recente que o salvo) migrou
    pro topo de "Indicadores" (antes ficava só em "Dados fixos").
  **P/VP, Payout e ROE migrados depois (mesmo dia)**: 3 cards novos em Indicadores, reusando
  EXATAMENTE `d.dadosFixos.pvp`/`.payout`/`.roe` (já calculados por `utils.dados_fixos.
  calcular_indicadores`, nenhuma conta nova) - Payout usa o dividendo DECLARADO (CVM), não o pago
  (Yahoo); ROE usa o mesmo "Lucro líquido (12 meses)" já mostrado no card ao lado. Diferente dos
  cards do núcleo da tela (P/L, LPA etc.), que mostram "Dados indisponíveis" quando falta o dado,
  esses 3 são indicadores extra/opcionais: sem dado, o card SOME (não aparece vazio).
  **ADR em USD - NÃO implementado, por quê**: pedido inicialmente como "Preço do ADR em USD,
  convertido com a mesma regra de câmbio EUR→USD que o projeto já usa" - RECUSADO, porque mistura
  2 mecanismos sem relação: `fator_adr` (já existente em `dados_fixos.py`) é só um multiplicador de
  proporção (quantas ações compõem 1 ADR) - `LPA_ADR = LPA × fator_adr` fica na MESMA moeda do
  ativo (R$ pra BBAS3), nunca converte pra dólar; `taxa_cambio_historica_eur_usd` converte EUR→USD,
  só pra empresas que arquivam na SEC em euro (ex. ASML) - BBAS3 é precificada em R$, sem nenhuma
  relação com euro. Aplicar a taxa EUR→USD num preço em R$ trataria reais como se fossem euros - um
  número inventado e errado por construção, exatamente o tipo de número que o projeto proíbe (não
  existe conversão BRL→USD implementada, ver Issue #47 item 16). Um ADR de verdade (ex. BDORY, o
  ADR real do Banco do Brasil) tem cotação PRÓPRIA no mercado americano - não é derivado
  matematicamente do preço em R$ via taxa de câmbio. DECISÃO: nenhum card de "ADR em USD" por
  enquanto - só volta a existir se for a cotação REAL do ticker do ADR buscada no Yahoo Finance
  (ex. `yf.Ticker("BDORY")`), nunca por conversão matemática a partir do preço local; exigiria
  mapear o ticker B3 pro ticker do ADR correspondente, hoje inexistente no projeto.
  Testado ao vivo (BBAS3): "Indicadores" mostra Ações 5,71 bi, LPA 2,18, P/L 7,70-7,74 (varia com a
  cotação do momento), Lucro líquido 12,45 bi, Dividendo 0,66 pago / 0,61 declarado, P/VP, Payout e
  ROE - tudo num card só, "Dados fixos" não aparece em lugar nenhum da tela (`document.body.innerText`
  sem a string).

## Issue #47 (26/11/2026): zonas sem julgamento, selo de fundamentos, bloco único LPA+P/L, remoção de backtest e preço justo, retorno sem misturar moeda

- **Item 10 - Zonas sem influenciar o usuário, cores mantidas**: "Oportunidade" e "Cara" saíram do
  texto em todo lugar (cards, barra "Você está aqui", gráfico) - as CORES continuam exatamente as
  mesmas (verde degradê embaixo, cinza no meio, âmbar/amarelo em cima), só o nome mudou, porque o
  nome antigo já era uma recomendação disfarçada de posição de preço. `utils/signals.py`
  (`Estado.zona`, `decidir_estado`/`decidir_estado_conservador`) e `utils/lynch.py` (Lynch, só
  MM200) agora devolvem "Faixa inferior" / "Zona neutra" / "Faixa superior" em vez de "Zona de
  oportunidade" / "Zona neutra" / "Zona cara". No card "Faixa de preço": "Faixa inferior" / "Zona
  neutra" (nome mantido) / "Faixa superior"; na régua (linha `zonas-rot`): "Inferior" / "Neutra" /
  "Superior"; no gráfico (linhas tracejadas do Conservador/Lynch): "Faixa superior acima de" /
  "Faixa neutra até" / "Média 200d" / "Faixa inferior 1" / "Faixa inferior 2" / "Faixa inferior 3"
  (1 = mais perto do neutro, 3 = mais embaixo - mesma ordem de antes, só o nome mudou); legenda do
  gráfico (abaixo dele): "Inferior" / "Neutra" / "Superior" / "Média 200d" / "Bem abaixo" (Lynch).
  DECISÃO SOBRE ESCOPO (ORIGINAL, 26/11/2026 - REVERTIDA DEPOIS, ver regra "Decisão" no topo deste
  arquivo): o rótulo do badge de decisão no topo ("COMPRAR - Oportunidade" / "AGUARDAR - Neutro" /
  "CARO - Evitar") NÃO mudou nesta issue - foi tratado como um conceito diferente (o veredito, não o
  nome da zona de preço). Revertido em 27/11/2026: o usuário apontou que o app não pode dizer
  "AGUARDAR" nem a palavra "oportunidade" pro usuário (soa como recomendação de compra/venda/espera,
  não só posição de preço) - o badge passou a usar as mesmas 3 zonas sem julgamento deste item
  ("Faixa inferior" / "Neutro" / "Faixa superior"), ver a regra "Decisão" no topo deste arquivo para
  os detalhes. O modo SIMONS CONTINUA fora de escopo (nem nesta issue, nem na correção de
  27/11/2026) - continua usando OPORTUNIDADE/NEUTRO/CARO como nome interno da sua própria
  classificação por MM200 - é uma metodologia própria, documentada à parte neste arquivo, e
  renomeá-la arriscava quebrar a lógica de entrada escalonada sem ganho claro; só o badge
  COMPARTILHADO do topo (mesmo componente visual dos outros 2 modos) foi corrigido lá. Se pedido
  depois, o vocabulário interno do próprio SIMONS entra como item separado.
- **Item 11 - Selo de Fundamentos** (fato, nunca recomendação; fica logo abaixo de "Faixa inferior"):
  `utils.signals.avaliar_fundamentos()` implementa a regra travada dos 3 fundamentos - (1) LPA
  CONTÁBIL (nunca ajustado) caindo vs. mesmo trimestre do ano anterior; (2) ROE caindo vs. 12 meses
  atrás; (3) dividendo cortado/reduzido vs. 12 meses atrás (ignorado para quem não paga dividendo,
  ex. MU - usa só lucro + ROE). Níveis: 1 de 3 ruim = "Observar: [fundamento]" (cinza/amarelo
  claro); 2 de 3 = "Fundamentos em alerta" (laranja); os 3 ruins por 2+ trimestres seguidos
  (estrutural: lucro caindo 3-4 trimestres ou prejuízo + ROE caindo e abaixo de 10% por 2+
  trimestres + dividendo cortado 2x seguidas + dívida subindo) = "Fundamentos deteriorados"
  (vermelho escuro). Sem fundamento ruim: sem selo nenhum. **LIMITAÇÃO CONHECIDA, documentada com
  honestidade**: a função está implementada e testada (`tests/test_signals.py`), mas HOJE o projeto
  não guarda o histórico trimestral que ela precisa - nem ROE (não existe em lugar nenhum do app,
  nunca foi calculado) nem LPA contábil trimestral suficiente para comparar "mesmo trimestre do ano
  anterior" (`utils/contabil_br.json` e `utils/contabil_sec.json` guardam só os últimos 4
  trimestres, não 5+). Por isso `tela/dados.montar()` chama `avaliar_fundamentos(lucro_caindo=None,
  roe_caindo=None)`, que sempre devolve `None`, e o selo nunca aparece na tela por enquanto (regra
  "nunca invente comparação" - ver regra geral do projeto). Para o selo aparecer de verdade, uma
  issue futura precisa: (a) o robô de contábil (B3 e EUA) guardar 5+ trimestres em vez de 4; (b)
  calcular e guardar ROE trimestral (lucro ÷ patrimônio líquido), hoje inexistente no projeto.
- **Item 12 e 14 - Bloco único "Lucro e Preço vs Lucro"**: os antigos cards "Preço vs Lucro (P/L)" e
  "Crescimento de Lucro (LPA)" (que podiam se contradizer - ex. lucro caindo -66% com selo
  "Favorável" de P/L) viraram 1 card só, sem o selo "Favorável"/"Desfavorável"/"Neutro" de nenhum
  dos dois (quem avisa fundamento ruim agora é só o Selo de Fundamentos do item 11, lá na Faixa de
  preço) e sem "Ver como calculamos"/texto gigante de cálculo. REGRA TRAVADA: 1 LPA só no app
  inteiro = LPA CONTÁBIL TTM; o ajustado (Yahoo) só aparece como linha extra `[Ajustado]`, cinza
  claro, nunca entra no P/L nem em nenhuma conta. Estrutura do card: conta em 1 linha cinza
  (cotação ÷ LPA contábil TTM = P/L), linha `[Ajustado]` quando existir e divergir 10%+, "Visão do
  ano" (Início do ano = guidance congelado · Contábil 12 meses (TTM) · Previsão atual = guidance
  oficial ou consenso, com o selo de confiabilidade quando poucos analistas), 1 linha "Média: 3
  anos X • 5 anos X • 10 anos X" (cada parte só aparece se tiver dado - nunca escreve "Sem dado"
  solto), e o P/L médio 12m. Linha sem dado: SOME, nunca aparece como "Sem dado" (regra do item 12).
  Dividendos virou um card próprio, simplificado, dentro da mesma seção: DPA, DY atual, DY média
  12m, Projetado `[Projeção]` (guidance), sem selo, sem a simulação "Se você investir R$ 10.000..."
  (tirada - item 14) e sem "Ver como calculamos". DY que sobe só porque o preço caiu não aparece
  como nada "favorável" (não tem mais selo para isso). Frase de fato "Dividendo reduzido vs 12
  meses atrás: de X para Y" aparece quando o dividendo caiu 5%+ - é só informativa (quem decide o
  Selo de Fundamentos é a função do item 11, com a regra própria dela, não esta frase). FONTE
  SEGURA do item 8 (biblioteca de fonte+data por número) ainda não está implementada neste PR - é
  outra issue; por enquanto a linha de fonte do card usa `d.lpaFonte`/`d.balanco`, o que já existe.
  AUDITORIA DA LISTA DE QUINTA (26/11/2026): a frase "Se você investir R$ 10.000, recebe X / ano"
  também sobrevivia no card separado "Indicadores" (`tela/detalhe.js`, cartão "Dividendo anual",
  variável `por10k`) - um card diferente do "Dividendos" dentro deste bloco único, que já estava
  correto. Removida (mesma regra do item 14/13: nunca simular renda).
- **Item 13 - Seção "Os sinais funcionaram no passado?" REMOVIDA** (backtest, cards SINAL
  VALIDADO/INVALIDADO, simulação de R$/US$ 10.000, "comprar em uma semana qualquer rendeu..."):
  tirada inteira de `tela/detalhe.js`, sem substituir por nada - o espaço fica vazio de propósito.
  O cálculo em si (`utils.signals.backtest_percentil`, `tela/dados._backtest`) continua existindo no
  backend (usado só por `decidir_estado`/avisos internos que já não apareciam na tela desde a regra
  "Faixa de 52 semanas" deste arquivo) - não foi removido porque a issue pediu só a remoção da
  TELA, e mexer no backend sem necessidade arriscava quebrar outros pontos à toa.
- **Item 15 - Seção "Preço justo" REMOVIDA** (Bazin, Conservador e P/L histórico como preço-alvo,
  "FAIXA JUSTA ESTIMADA", selo "Faixa justa consistente"): tirada inteira, sem substituir - o app
  mostra só posição de preço (item 10) + fundamentos (item 11), nunca mais um preço-alvo. O card
  "Lucro por ação" do Conservador continua mostrando "P/L Conservador"/"Preço teto conservador"
  como diagnóstico (isso já não era a Faixa de preço desde a mudança anterior documentada acima em
  "CONSERVADOR") - não fazia parte da seção "Preço justo" removida.
- **Item 16 - Retorno acumulado sem misturar moeda, sem simulação de dinheiro**: `app.comparadores()`
  agora devolve 3 valores (comparadores, padrão, renda_fixa) e filtra por moeda - ticker da B3 só
  recebe Ibovespa/IPCA/Poupança (R$); ticker dos EUA só recebe S&P 500/Nasdaq (US$). CDI e Selic
  saíram do dicionário de comparadores e foram para `renda_fixa` (card "Renda fixa `[Outro tipo de
  investimento]`", separado do gráfico de retorno - BR apenas). SEM conversão BCB/Fed implementada
  ainda: por isso um índice em moeda diferente simplesmente não entra, nunca aparece misturado sem
  conversão (ex.: ticker dos EUA não mostra Ibovespa nem CDI/Selic/IPCA/Poupança). **LIMITAÇÃO
  CONHECIDA**: não existe hoje fonte de T-Bill/Fed Funds integrada ao projeto - por isso o card
  "Renda fixa" só aparece para tickers da B3 (CDI/Selic); para os EUA fica vazio (nunca inventado) -
  implementar isso é outra issue. Removida a simulação "Se você tivesse investido R$/US$ 10.000...":
  a tela mostra só % de retorno e a diferença em pontos contra o comparador. Removido "Ver como
  calculamos" do retorno - 1 linha só, "Fonte: Yahoo Finance - Dados até DD/MM/AAAA" (continuam
  mantidos: gráfico de barras, aviso "Retorno passado não garante retorno futuro" e os botões
  1/3/5 anos e Reinvestindo/Sem reinvestir). **LIMITAÇÃO CONHECIDA**: o cálculo de retorno com
  dividendos reinvestidos (`calculos.calcular`) continua usando o preço ajustado do Yahoo
  internamente (não foi trocado por B3/RI ou SEC, que é uma mudança de backend maior, fora do
  escopo deste PR de UI) - só o TEXTO que citava "preço ajustado Yahoo" foi tirado da tela, para não
  prometer uma fonte que o cálculo ainda não usa; a fonte real do cálculo é Yahoo Finance, como a
  linha "Fonte" agora diz.

## UI (Issue #46)

- **Preview do WhatsApp**: o Streamlit é um app de página única - `st.set_page_config(page_title=...)`
  só muda o `<title>` depois que o JavaScript termina de montar a página, e o WhatsApp nunca
  executa JavaScript pra gerar o preview de um link (lê só o HTML que o servidor devolve de cara).
  Esse HTML inicial é sempre o mesmo `streamlit/static/index.html` de dentro do pacote instalado,
  com `<title>Streamlit</title>` e nenhuma meta tag - por isso o preview saía errado. `utils/seo.py`
  (`aplicar_meta_og()`, chamado em `app.py` logo depois do `set_page_config`) reescreve esse arquivo
  estático uma única vez por subida do app (idempotente, por um marcador de comentário), trocando o
  `<title>` e inserindo `og:title`/`og:description`/`og:image` (+ `twitter:card`) antes de
  `</head>`. A imagem é o logo real do projeto, publicado no GitHub
  (`https://raw.githubusercontent.com/imoveispalmassc-wq/FINTAI/main/assets/logo.png`) - nunca uma
  URL inventada; sem um print de tela próprio do app publicado, é a única imagem real disponível.
  LIMITAÇÃO HONESTA: isto não é uma configuração oficial do Streamlit (não existe hoje nenhum
  parâmetro do `set_page_config` nem `config.toml` pra meta tags Open Graph) - é um ajuste no
  arquivo estático do pacote `streamlit` já instalado no mesmo container do app, que só funciona se
  o processo tiver permissão de escrita ali (o Streamlit Cloud tem; falha em silêncio, nunca
  derruba o app, em qualquer hospedagem que não tenha). E não foi possível confirmar visualmente o
  preview real do WhatsApp a partir do ambiente onde isso foi implementado: o WhatsApp precisa
  buscar uma URL pública publicada de verdade (às vezes também cacheia um preview antigo por um
  tempo mesmo depois de corrigido) - só dá pra confirmar depois do deploy, mandando o link do app
  publicado numa conversa de verdade. A página de exemplo (`docs/index.html`, GitHub Pages) já tem
  as mesmas tags (via `utils.seo.tags_og`, reaproveitado em `tools/gerar_demo.py`) e essa, sim, foi
  conferida: usa `og:image` do mesmo logo real e `og:url` apontando pra
  `https://imoveispalmassc-wq.github.io/FINTAI/` (URL padrão de GitHub Pages publicando a partir de
  `/docs` em `main` - não foi possível confirmar com uma requisição de verdade que a página está no
  ar, por restrição de rede do ambiente onde isso foi implementado, mas é a URL real e não inventada
  que corresponde à configuração do repositório).
- **MU - "faixa de preço errada" (item 2)**: investigado com dados reais do Yahoo Finance em
  26/11/2026 - NÃO é bug. A MU disparou de ~US$ 220 pra mais de US$ 1.200 no último ano (supercycle
  de IA em memória) e caiu pra ~US$ 601 em seguida: média de fechamento semanal de 1 ano = US$
  681,96 (âncora/teto), de 3 anos = US$ 301,73, de 5 anos = US$ 207,07 (bem mais baixa, porque pesa
  anos de preço pré-supercycle). A Faixa do Conservador usa exatamente essas médias (ver
  `teto_valuation_conservador` acima) e os números batem matematicamente - é o cenário que a seção
  "Regras de cálculo" já citava como limitação conhecida da Faixa do Conservador ("pode ficar presa
  a um regime de mercado antigo da empresa, ex. MU antes do supercycle de IA"). Valores conferidos e
  travados como teste de regressão em `tests/test_calculos.py`
  (`test_teto_valuation_conservador_mu_dados_reais_26_11_2026`) - não no código do app, só no teste,
  como documentação do que foi checado.
  "SEGUNDA CONTA" (ambíguo, não foi possível esclarecer com quem reportou o item): o único outro
  lugar do código que calcula uma faixa de preço "de outro jeito" pro mesmo ativo é a faixa clássica
  de 52 semanas (`utils/percentile.zonas`, mínima + 30%/70% da amplitude) - ela aparece no modo
  SIMONS e como `fx`/`d.faixas` (alternativa visual quando falta o teto do Conservador). Pra MU, com
  mínima/máxima de 52 semanas de ~US$ 221/US$ 1.255, essa conta dá um ponto de oportunidade bem
  diferente (~US$ 531) do ponto de oportunidade do Conservador (~US$ 477, 70% da âncora de 1 ano) -
  são DUAS contas diferentes de propósito (uma é só a faixa histórica observada; a outra é
  valuation, ponderada pelo preço médio pago no período), e comparar os dois números lado a lado,
  sem saber que são métodos diferentes, pode parecer que um dos dois "está errado". Documentado aqui
  pra esclarecer: nenhum dos dois é bug, são métricas diferentes mostradas em modos diferentes da
  tela (Conservador usa valuation; SIMONS usa a faixa histórica de 52 semanas).
  "SEGUNDA CONTA" de verdade (esclarecido depois, 27/11/2026): não era uma segunda conferência - é
  uma segunda implantação do MESMO repositório (outra conta no Streamlit Cloud/GitHub), que mostrava
  a Faixa de preço da MU diferente da conta principal. 2 causas reais encontradas no repositório
  (nunca confirmadas ao vivo, porque esta sessão não tem acesso a nenhuma implantação publicada, só
  ao código): (1) `requirements.txt`/`requirements-guidance.txt` usavam `yfinance>=0.2.40`,
  `pandas>=2.0`, `streamlit>=1.67` (mínimos, não travados) - 2 implantações feitas em momentos
  diferentes podem instalar versões diferentes dessas libs, e o jeito de ajustar preço/split pode
  mudar entre versões do yfinance, afetando a média de 1/3/5 anos da Faixa de preço; travadas em
  versão exata (`==`), incluindo `numpy` (antes nem citado, dependência transitiva do pandas) -
  plotly/lxml/requests continuam soltos, não influenciam cálculo de preço. (2) existe um branch
  `refatora-sinais` no repositório, 215 commits atrás do `main` (parado em 14/11/2026, antes até da
  Faixa de preço por valuation existir - só tinha a faixa clássica de 52 semanas) - se a segunda
  conta estiver apontando pra esse branch (ou pra um commit antigo do próprio `main`), ela calcula
  a Faixa de preço por um MÉTODO inteiro diferente, não um arredondamento; os números batem: a faixa
  de 52 semanas clássica pra MU (mínimo 192,59/máximo 1.255,00, mesmo exemplo de validação já citado
  no topo deste arquivo) dá 511,31/936,28 - bem diferente dos 477,51/886,81 atuais. Rodapé de
  diagnóstico adicionado em `app.py` (`_versao_deploy()`, `git rev-parse` do branch+commit em
  execução, nunca derruba o app sem `.git` disponível) - mostra "Versão: branch@commit" no fim da
  página, pra comparar as 2 contas sem precisar dar acesso a ninguém. Branch antigo NÃO apagado:
  decisão do usuário, só depois de confirmar as 2 contas no mesmo commit do `main`.
  ITEM 2 FECHADO (confirmado pelo usuário, não por esta sessão - sem acesso a nenhum painel
  publicado): print do share.streamlit.io mostra só 1 app publicado (`fintai • main • app.py`) -
  nenhum app em `refatora-sinais`, nenhum segundo deploy da conta antiga da imobiliária. Nunca
  existiram "2 contas ativas" - só a conta certa (fintai.guidance@gmail.com) e um resquício de
  configuração/lembrança da conta antiga, sem app publicado de verdade. A causa raiz real do
  número errado que o usuário via era a combinação do branch `refatora-sinais` parado +
  `yfinance` destravado (ambos corrigidos no PR #60) - não uma segunda implantação concorrente.
  Nada foi apagado (branch `refatora-sinais` continua existindo, intacto).
- **Ticker fixo no topo (item 3)**: `.topo` (em `tela/detalhe.html`/`.css`/`.js`), fundo sólido e
  sombra/borda ao rolar (classe `.rolou`). ESTADO NORMAL (topo da página, `.rolou` ausente): mostra
  só nome completo + bolsa (`.meio`) - sem preço nem variação, que ficariam duplicados com o cartão
  de decisão logo abaixo (REGRA ATUAL, corrigida depois de ida e volta, ver histórico abaixo).
  ESTADO FIXO (rolando, `.rolou` presente): mostra SÓ O TICKER + A COTAÇÃO + A VARIAÇÃO DO DIA (ex.
  "MU  US$ 601,25  ▼ -4,53%"), escondendo nome completo/bolsa.
  HISTÓRICO (27/11/2026, 3 idas e voltas, todas a pedido do usuário - documentado pra não repetir
  o ciclo): 1ª versão escondia nome E preço ao rolar, mostrando só o ticker ("o pedido era só manter
  o ticker identificável, sem repetir mais nada" - preço já aparecia no cartão de decisão). 2ª volta
  ("Poderíamos travar essa cotação na Barra junto com o ticker?"): preço passou a aparecer de novo,
  mas só no estado ROLADO, ao lado do ticker - no estado normal (topo da página) o preço continuava
  escondido nessa versão. 3ª mudança (pedido de afastar o preço do ticker e acrescentar a variação):
  nesse momento o preço/variação passaram a aparecer SEMPRE (normal e rolado), já que ainda não
  existiam no estado normal - e aí sim ficou duplicado com o cartão de decisão, que o usuário notou e
  pediu pra tirar. REGRA FINAL: preço e variação (`.preco-topo`/`.var-topo`) só aparecem no estado
  ROLADO (`.topo.rolou .preco-topo, .topo.rolou .var-topo { display: block; }`), nunca no normal.
  `#t-ticker` (`ticker-topo`) é um elemento à parte, escondido por padrão e mostrado só com
  `.topo.rolou .ticker-topo`; só `.topo.rolou .meio` (nome completo + bolsa) esconde o resto. No
  HTML, a ordem é `#t-ticker` → `#t-preco` → `#t-var` (mesma ordem em que aparecem lado a lado: "MU
  US\$ 601,25 ▼ -4,53%") - a ordem no DOM só importa pro estado rolado, já que no estado normal os 3
  ficam com `display: none` independente da posição. Gap de 18px (em vez dos 10px padrão) só em
  `.topo.rolou`, pra afastar mais o ticker da cotação/variação - pedido explícito do usuário depois
  de ver os dois colados.
  2º BUG, CORRIGIDO ERRADO NA 1ª TENTATIVA (27/11/2026, PRs #61/#62 - registrado aqui com
  honestidade, porque gastou 2 ciclos de PR do usuário num diagnóstico errado antes de achar a causa
  real): a 1ª tentativa supôs que a tela roda dentro de um IFRAME do componente do Streamlit, que
  cresceria pra caber todo o conteúdo em vez de ter scroll próprio - e "corrigiu" trocando pra
  `position: fixed` com `window.parent`/`window.frameElement`. Essa suposição nunca foi testada
  contra o app de verdade rodando (só contra uma página HTML simulada, montada à mão pra parecer um
  iframe de Streamlit) - o usuário reportou que continuava sem funcionar ("Não está funcionando e só
  está gastando meus créditos"). Investigação de verdade, rodando `streamlit run app.py` e inspecionando
  com Playwright: **não existe nenhum iframe** (`document.querySelectorAll('iframe').length === 0`).
  `st.components.v2.component` (mecanismo interno "BidiComponent") monta o conteúdo direto numa
  SHADOW ROOT (`mode="open"`) dentro da própria página do Streamlit - `position: sticky` no CSS
  sempre funcionou sozinho (confirmado prendendo `.topo` no topo real da tela), então a ideia do
  iframe/`window.parent`/`position:fixed` nunca teve motivo de existir e foi removida por inteiro.
  As causas reais eram 3, todas só visíveis testando o app de verdade (nunca uma simulação):
  (a) `document.querySelector('.topo')` chamado de dentro do próprio script do componente sempre
  retornava `null`, porque consulta de CSS feita a partir do `document` de fora nunca enxerga pra
  dentro de uma shadow root (isolamento por design) - o `if` inteiro nunca rodava, sem erro nenhum;
  corrigido usando `root` (o parâmetro da função `montar(root, d)`, a mesma raiz que o helper `$()`
  já usa) em vez de `document` pra achar elementos do próprio componente; (b) mesmo corrigindo (a),
  quem rola de verdade dentro do Streamlit é um `<main id="stMain">` interno (`overflow: auto`) -
  nunca a `window`/`document` (`window.scrollY` fica sempre 0) - e um evento de scroll disparado
  nesse elemento não "escapa" pra fora da árvore de quem o disparou, então nem um
  `window.addEventListener('scroll', ...)` nem um `document.addEventListener('scroll', ..., {capture:
  true})` registrado de dentro do script do componente conseguem vê-lo; corrigido trocando a
  detecção de "rolou" de escutar evento de scroll para um `IntersectionObserver` numa sentinela de
  1px colocada logo ACIMA de `.topo` no HTML (`#t-sentinela-topo`) - ele mede a posição real do
  elemento na tela (`root: null` = viewport de verdade) e dispara sozinho, não importa qual
  ancestral rolou nem como (não depende de nenhum id interno do Streamlit, que pode mudar de versão
  pra versão); (c) o Streamlit tem a sua PRÓPRIA barra fixa no topo (menu/Deploy, fora da shadow
  root deste componente, `[data-testid="stHeader"]`), `position: absolute`, `top: 0`, com z-index
  altíssimo (999990 na versão testada) - mesmo com `.topo` preso em `top: 0` e seu próprio z-index,
  essa barra do Streamlit ficava por cima e escondia o cabeçalho fixo inteiro atrás dela; corrigido
  medindo a altura real dessa barra em tempo de execução (`getBoundingClientRect().height`, nunca um
  valor fixo em pixels - quebraria se o Streamlit mudar essa altura numa versão futura) e somando ao
  `top` do sticky, pra colar logo ABAIXO da barra, visível. Testado com Playwright contra o app real
  (`mini_app.py`, reproduzindo `tela/detalhe.html`/`.css`/`.js` com dados reais da MU, já que o app
  completo trava buscando dados nesta sandbox por limitação de rede, não um bug do app): rolando
  `#stMain` de verdade, `.topo` ganha a classe `rolou`, prende logo abaixo da barra do Streamlit
  (`rectTop: 60`) e mostra só "MU"; voltando ao topo, volta ao estado normal (nome completo + bolsa +
  preço) sem ficar preso errado.
  BUG CORRIGIDO (27/11/2026, achado pelo usuário num print): o preço no cabeçalho fixo (`$('t-preco')`)
  mostrava só o número ("601,25"), sem "US$"/"R$" na frente - diferente do preço no cartão de decisão
  logo abaixo, que já mostra a moeda. Causa: usava `f(d.preco)` (só formata o número) em vez de
  `din(d.preco)` (que já prefixa `${d.moeda}`, a mesma função usada em todo o resto da tela).
  Corrigido trocando para `din(d.preco)`.
- **CBRS sem Oportunidade 2/3 (item 6)**: investigado com dados reais do Yahoo Finance em
  26/11/2026 - NÃO é bug. CBRS tem só ~6 meses e meio de histórico de preço (IPO recente), então
  `media_fech_3a`/`media_fech_5a` ficam `None` (sem 3/5 anos de histórico - ver
  `_media_fechamento_semanal`), `limite3a`/`limite5a` ficam `None`, e a Faixa do Conservador mostra
  só 1 zona de oportunidade (a âncora de 1 ano, que CBRS já tem) - exatamente o comportamento
  documentado acima ("Sem 1 ano de histórico... sem teto"; aqui já dá pro ano 1, só não pros limites
  de 3/5). Valores conferidos e travados como teste de regressão
  (`test_teto_valuation_conservador_cbrs_dados_reais_26_11_2026_sem_3a_5a`).
  BUG VISUAL ENCONTRADO E CORRIGIDO (ajuste pedido no item, não o bug em si): com uma zona de
  oportunidade estreita (ex. CBRS: só ~16% da régua), o rótulo "Oportunidade" quebrava no meio da
  palavra ("Oportunida"/"de" em 2 linhas) em vez de simplesmente sumir, porque o limiar que decide
  "a coluna é estreita demais, esconde o rótulo" era um número fixo (11%) igual pros 3 rótulos -
  "Cara"/"Neutra" (curtos) cabem em 11%, mas "Oportunidade" (bem mais longo) não. O limiar agora usa
  a largura real estimada de cada rótulo (mesma técnica de `largadorPx`/`pxParaPct` já usada pros
  números da régua logo abaixo), não um valor igual pra todos - confirmado visualmente com
  Playwright (CBRS real: "Oportunidade" some corretamente, sem quebrar palavra; PETR4, com zona bem
  mais larga, continua mostrando os 3 rótulos normalmente). NOTA: este item (#46) foi corrigido
  antes do item 10 da Issue #47 renomear "Oportunidade"/"Cara" para "Inferior"/"Superior" - a lógica
  de ocultar o rótulo quando a coluna é estreita demais continua a mesma, só o texto exibido mudou
  (ver Issue #47 acima).

## Melhoria visual nos cards de LPA/Lucro/Dividendo (27/11/2026) - sem mudar nenhum cálculo

- Pedido do usuário (BBAS3): o mesmo dividendo aparecia 3x com 3 valores diferentes (parecia erro),
  o LPA tinha 4 números com o mesmo peso visual (ninguém sabia qual o app realmente usa) e o bloco
  de guidance tinha um parágrafo de 8 linhas. Mudança só de APRESENTAÇÃO - nenhuma fórmula, fonte ou
  valor novo; só reorganiza o que `d.dadosFixos`/`d.guidance`/`d.lpa` etc. já calculavam.
  1. **Dividendo unificado**: card "Dividendos" (dentro de "Lucro e Preço vs Lucro") passou a ter 5
     linhas na mesma lista - Pago (365 dias, Yahoo), Declarado (CVM), Projetado (guidance, com o DY
     dele do lado), DY atual (sobre o pago) e DY média 12m - com 1 nota só explicando os 3 conceitos
     (antes eram várias notas repetidas dizendo a mesma coisa). O card "Dividendo anual" que existia
     solto em "Indicadores" foi removido (só "Dividend yield" continua lá) - era o mesmo número do
     "Pago" do card novo, duplicado.
  2. **Hierarquia do LPA**: no card "Lucro e Preço vs Lucro", o LPA contábil TTM (o único que entra
     no P/L, REGRA TRAVADA) ficou em destaque, na própria linha "Cotação ÷ LPA contábil TTM = P/L",
     com fonte maior; Início do ano/Previsão atual/[Ajustado] viraram 1 linha de contexto, menor e
     cinza, logo abaixo - são números diferentes de propósito (guidance congelado do início do ano
     vs. resultado real acumulado vs. projeção pro resto do ano), não "o mesmo número corrigido".
  3. **Guidance encurtado**: o card "Lucro por ação" (modo Conservador) mostra agora só 2-3 linhas
     (Lucro esperado, LPA projetado com a variação vs. o ano anterior) com um botão "Ver metodologia"
     que abre o texto completo de sempre (cálculo, fonte, data) no painel lateral já usado em outros
     pontos da tela (`FOLHAS`/`data-folha` - mesmo mecanismo de "Ver como calculamos" já existente,
     reaproveitado, não um componente novo). Sem guidance oficial (só consenso do Yahoo), o texto
     completo de sempre continua visível direto no card (nunca escondido atrás de um botão quando
     não há nada "longo" a esconder).
  4. **Mini gráfico de LPA**: barras simples (`miniBarras()`, `tela/detalhe.js`) no card "Lucro por
     ação", usando só os valores dos últimos 3 anos + projeção que a tela já mostra na tabela logo
     abaixo (nenhuma busca/cálculo novo) - barra do ano de guidance com textura tracejada, pra marcar
     visualmente que é projeção, não resultado fechado.
  5. **P/L médio 12m com contexto**: "P/L médio 12m: 9,47" passou a mostrar "(vs. P/L atual 7,66)" do
     lado, pra o usuário comparar sem precisar rolar até outro card.
  **2 itens pedidos que, checados contra a lógica já existente e documentada, NÃO eram bugs - não
  alterados**:
  - "'Contábil 12m até 3T26 (set/26)' está errado, deveria ser 3T25": não está errado. Hoje
    (27/11/2026) o último trimestre fechado e já divulgado da BBAS3 é mesmo o 3T26 (encerrado
    30/09/2026) - "3T26 (set/26)" é a etiqueta correta pela própria convenção de trimestre do
    projeto (ano civil do fechamento, não o ano anterior). Nenhuma mudança feita.
  - "Trocar a bolinha vermelha em 'Atualizado em 22/11'... parece erro": não é erro, é o indicador de
    idade do dado já documentado acima em "Card de P/L" (🟢 <2h, 🟡 <24h, 🔴 ≥24h desde a última
    atualização do robô) - 22/11 está a 5 dias de hoje (27/11/2026), então vermelho é o resultado
    correto e esperado da própria regra, não uma falha de cor. Nenhuma mudança feita.
  Nada em `tela/dados.py` nem `utils/dados_fixos.py` foi tocado - só `tela/detalhe.js`/`.css` (e o
  teste de ordem do card, `tests/test_dados.py`, ajustado pra continuar verificando a mesma ordem
  cronológica Início do ano -> TTM -> Previsão atual, só que no novo formato visual).
- **Follow-up no mesmo dia - mini gráfico com 2 barras pro ano de guidance**: o ano de projeção
  (2026 pra BBAS3) virou 2 barras lado a lado em vez de 1 só - "2026 Atual (TTM)" (sólida, cor
  normal, o mesmo `d.lpa` já usado no P/L) e "2026E Guidance" (tracejada, como já era). Nenhum
  valor novo: as 2 barras e as 2 linhas da lista abaixo (`linhaAtualTTM`/`linhaProj`) só reusam
  `d.lpa` (TTM) e `proj`/`G.lpa` (guidance/consenso), que já apareciam nos cards "Lucro por ação" e
  "Lucro e Preço vs Lucro". `miniBarras()` ganhou um parâmetro opcional `fantasma` - uma linha
  pontilhada fina sobre a barra do TTM, marcando `d.guidanceInicial.lpa` (o guidance congelado do
  início do ano, reusado da MESMA fonte que já alimenta `lpaIni` no card "Lucro e Preço vs Lucro")
  como contexto de revisão, com uma legenda minúscula e apagada (`.nota` 10.5px, opacity .65) abaixo
  do gráfico - nunca uma barra própria, nunca com o mesmo peso visual dos números atuais. O valor
  fantasma entra na escala do gráfico (pra nunca estourar a altura do traço), mas não vira uma
  barra. Testado ao vivo com BBAS3: 5 barras (2023/2024/2025/2026 Atual TTM/2026E Guidance) e a
  linha pontilhada em R$ 4,20 sobre a barra do TTM (R$ 2,18).
- **2º follow-up no mesmo dia - gráfico combinado Lucro × Receita (estilo Investing) PEDIDO E NÃO
  IMPLEMENTADO - falta a fonte**: o usuário pediu um gráfico de eixo duplo (Receita em barra azul +
  LPA em barra cinza + traço laranja de projeção), condicionado explicitamente a existir receita em
  `d.dadosFixos` - e ele mesmo pediu pra avisar e manter o gráfico atual se não existisse. Checado:
  `utils/dados_fixos.py` (grep por "receita"/"revenue") NÃO tem nenhum campo de receita - o módulo
  só busca ações, lucro, dividendo e patrimônio líquido na fonte oficial (CVM/SEC), nunca receita.
  Existe receita de OUTRA fonte no projeto (`tela/dados.py`, `d.get("receita_anual")`, vindo do
  Yahoo `income_stmt`, já usado no crescimento do Lynch) - mas essa série anual completa não é hoje
  exposta pra tela como um array ano a ano (só TTM/média/previsão de 1 valor cada, não uma lista tipo
  `d.lpaAnos`), e o pedido era condicionado especificamente a `d.dadosFixos`. Por decisão (seguindo a
  instrução explícita do usuário: "me avisar e manter o gráfico atual"), o gráfico combinado NÃO foi
  construído - o mini gráfico de LPA continua como estava (barras de 2023/2024/2025/2026 Atual TTM/
  2026E Guidance + linha fantasma). Pra implementar de verdade no futuro, precisaria: (a) decidir se
  usa a série anual do Yahoo (`receita_anual`, já existe mas não está exposta ano a ano) ou criar uma
  busca de receita trimestral na fonte oficial (CVM/SEC) dentro de `dados_fixos.py`, igual ao lucro -
  ambas são mudanças de BACKEND, fora do escopo de um ajuste só de apresentação.
  Os outros itens do mesmo pedido, independentes de receita, foram implementados: (1) botão "Ver
  metodologia" removido - vira 1 linha pequena e apagada com a própria conta (`contaGuidance`,
  ex. "(R$ 9,0 bi + R$ 11,0 bi) ÷ 2 ÷ 5,71 bi ações = R$ 1,75"), a mesma fórmula de sempre, só
  visível direto em vez de atrás de um painel; o texto completo (`textoProjecaoCompleto`) continua
  existindo só pro caso SEM guidance oficial (consenso do Yahoo, `#g-nota-proj}`), que não tinha
  pedido de mudança. (2) lista de texto abaixo do gráfico (anos + "2026 Atual (TTM)" + guidance)
  removida - os valores já aparecem escritos em cima de cada barra do mini gráfico, então vinham
  duplicados. (3) texto "Dados de 5 e 10 anos indisponíveis... Nenhum ano de prejuízo..." encurtado
  pra "Sem histórico de 5/10 anos para este ticker." + "Sem prejuízo nos últimos 3 anos." (2 linhas
  curtas sucessivas, mesmo sentido, bem mais curto que o parágrafo de antes).

## Textos

- Nunca mostrar "percentil" nem a sigla IFR como título. Título do card "Força - RSI" (em inglês, não "IFR"),
  "Últimos 14 dias" como subtítulo - exceção pedida explicitamente; fora desse card específico, continua valendo
  nunca mostrar sigla nenhuma (só "Força").
- Nunca usar a palavra em inglês para operação de curto prazo: sempre "movimento curto".
- Rodapé: "Fonte: Yahoo Finance. Dados podem mudar após balanço."

## Antes de publicar

- `python -m pytest` precisa passar.
- Se mudar a tela (`tela/detalhe.*`), rodar `python tools/gerar_demo.py` para atualizar a página de exemplo.
- `app.py` recarrega os módulos (`importlib.reload`) numa ordem fixa, porque o Streamlit Cloud pode manter
  versões antigas na memória depois de um deploy. Módulo novo que faz `from outro_modulo import nome` no topo
  do arquivo (ex.: `utils/dados_fixos.py` importando de `utils/fetch_guidance.py`) precisa entrar nessa lista
  DEPOIS do módulo de quem ele importa - senão, ao recarregar só o módulo novo, ele reimporta de uma versão
  antiga do outro módulo ainda em memória, e um nome adicionado depois do último reload vira `ImportError`
  (issue #33, causada pela adição de `utils.dados_fixos` sem adicionar `utils.fetch_guidance` antes dele na
  mesma lista). `tests/test_app_reload.py` tem um teste que falha se essa ordem for quebrada de novo.
