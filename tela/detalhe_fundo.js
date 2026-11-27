/* Segunda metade da tela de detalhes (Fundamentos, Indicadores) - componente separado do principal
   (tela/detalhe.js), criado em 27/11/2026 pra encaixar o gráfico nativo de LPA
   (components/lpa_chart.py) logo abaixo do card "Lucro por ação", sem ficar só no final da tela
   inteira. Um widget nativo do Streamlit não pode ficar embutido no meio do HTML/JS do componente
   único (tela/detalhe.js) - só dá pra encaixar ENTRE dois componentes. Este arquivo é a 2ª metade
   (Fundamentos/Indicadores); tela/detalhe.js é a 1ª (cabeçalho fixo, Visão geral, Faixa/Tendência/
   Mínimo-máximo/bloco de cada modo) - o corte foi feito exatamente na costura que já existia entre
   `#modo-bloco` e `#fundamentos` (tela/detalhe.html), nunca no meio de um card. O cabeçalho fixo e
   a lógica de scroll (IntersectionObserver, barra sticky) ficam 100% na 1ª metade, intocados - esta
   2ª metade não tem cabeçalho nenhum.
   "Retorno acumulado" (que morava aqui também) saiu de vez pra um 3º bloco, nativo do Streamlit
   (`components/retorno_chart.py` + `app._retorno_bloco`, chamado em `app.py` depois deste
   componente) - mesma regra do gráfico de LPA: nenhum gráfico de barra desenhado na mão.

   Troca de modo (Conservador/Crescimento/Quantitativo) é só client-side em tela/detalhe.js (sem
   round-trip no Streamlit) - esta metade não tem os botões, então não tem como saber sozinha
   quando o modo muda. Por isso: lê o modo salvo (mesma chave de sessionStorage) ao montar, e ouve
   o evento 'fintai-modo-mudou' que tela/detalhe.js dispara a cada clique de aba (CustomEvent no
   `document`, atravessa a fronteira de shadow DOM dos 2 componentes) pra aplicar a MESMA regra de
   visibilidade por modo (SECOES) que esses 3 cards já tinham. */

const INDISP = 'Dados indisponíveis';

const tem = v => v !== null && v !== undefined && Number.isFinite(v);
const f = (v, casas = 2) => tem(v) ? v.toLocaleString('pt-BR', { minimumFractionDigits: casas, maximumFractionDigits: casas }) : '—';
const sinal = (v, casas = 2) => tem(v) ? `${v > 0 ? '+' : v < 0 ? '-' : ''}${f(Math.abs(v), casas)}%` : '—';
const ret = v => sinal(v, tem(v) && Math.abs(v) >= 100 ? 0 : 1);
function qtd(v) {
  if (!tem(v)) return null;
  for (const [lim, suf] of [[1e12, 'tri'], [1e9, 'bi'], [1e6, 'mi']]) if (Math.abs(v) >= lim) return `${f(v / lim)} ${suf}`;
  return f(v, 0);
}
function passoBonito(x) {
  const p = Math.pow(10, Math.floor(Math.log10(x))), m = x / p;
  return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 5 ? 5 : 10) * p;
}

function montar(root, d) {
  const $ = id => root.querySelector('#' + id);
  const din = (v, casas = 2) => tem(v) ? `${d.moeda} ${f(v, casas)}` : '—';
  // bolinha de atualização (verde <2h, amarelo <24h, vermelho 24h+) - mesma função de tela/detalhe.js
  const bolaAtualizacao = (A, extra = '') => {
    if (!A || !A.em) return '';
    const h = (Date.now() - Date.parse(A.iso)) / 36e5, bola = h < 2 ? '🟢' : h < 24 ? '🟡' : '🔴';
    const [dia, hora] = A.em.split(' ');
    return `<div class="atualiz" title="Verde: atualizado há menos de 2h. Amarelo: menos de 24h. Vermelho: 24h ou mais sem atualizar.">${bola} Atualizado em ${dia} às ${hora}${A.tri ? `<br><span class="i">Contábil 12m até ${A.tri}${A.triData ? ` (${A.triData})` : ''}</span>` : ''}${extra}</div>`;
  };
  const limpar = [];
  const FOLHAS = {};
  const fonte = `<p><b>Fonte:</b> ${d.fonte} · atualizado em ${d.atualizado}.</p>`;
  const dy = tem(d.dividendo) && d.preco ? d.dividendo / d.preco * 100 : null;
  const naoPagadora = tem(dy) && dy < 0.5;

  /* ---------------- folha "Ver como calculamos" - modal PRÓPRIO desta metade (componente
     separado, shadow root separado de tela/detalhe.js), usado só pelo card "Indicadores" aqui */
  function abrirFolha(titulo, html) {
    $('folha-t').textContent = titulo; $('folha-c').innerHTML = html; $('fundo').hidden = false; $('folha-x').focus();
  }
  const fecharFolha = () => { $('fundo').hidden = true; };
  $('folha-x').onclick = fecharFolha;
  $('fundo').onclick = e => { if (e.target === $('fundo')) fecharFolha(); };
  const tecla = e => { if (e.key === 'Escape') fecharFolha(); };
  document.addEventListener('keydown', tecla); limpar.push(() => document.removeEventListener('keydown', tecla));
  root.querySelector('.app').onclick = e => {
    const b = e.target.closest('[data-folha]');
    if (b && FOLHAS[b.dataset.folha]) { const [t, h] = FOLHAS[b.dataset.folha](); abrirFolha(t, h); }
  };

  /* ---------------- fundamentos (issue #47, itens 12 e 14: bloco único "Lucro e Preço vs Lucro",
     sem selo "Favorável"/"Desfavorável" (isso é só o Selo de Fundamentos do item 11, lá na Faixa
     de preço) e sem "Ver como calculamos"/texto gigante. REGRA TRAVADA: 1 LPA só no app = LPA
     CONTÁBIL TTM; ajustado só como [Ajustado] extra, nunca no cálculo principal. Linha sem dado
     nunca aparece como "Sem dado" - some. */
  (function Fundamentals(el) {
    const prejuizo = tem(d.lpa) && d.lpa <= 0;
    // LPA ajustado: só informativo, nunca no cálculo (REGRA TRAVADA)
    const lpaAjustado = d.baseLpa === 'últimos 4 trimestres' && tem(d.lpa) && d.lpa > 0 && tem(d.lpaAgora) && d.lpaAgora > 0
      && Math.abs(d.lpaAgora / d.lpa - 1) > 0.10 ? d.lpaAgora : null;
    const plAjustado = tem(lpaAjustado) ? d.preco / lpaAjustado : null;
    // Visão do ano: início do ano (guidance congelado) | contábil 12 meses | previsão atual (guidance ou consenso)
    const Fp = d.consensoAno || {}, G0 = d.guidance, GI = d.guidanceInicial || {};
    const anoPrev = (G0 && G0.periodo) || (d.lpaAnos && d.lpaAnos.length ? d.lpaAnos[d.lpaAnos.length - 1].ano + 1 : null);
    const lpaCons = tem(Fp.lpa) && Fp.lpa > 0 ? Fp.lpa : null;
    const lpaGuia = G0 && tem(G0.lpa) && G0.lpa > 0 ? G0.lpa : null;
    const lpaPrev = lpaGuia || lpaCons;
    const plPrev = tem(lpaPrev) ? d.preco / lpaPrev : null;
    const lpaIni = tem(GI.lpa) && GI.lpa > 0 ? GI.lpa : null;
    const plIni = tem(lpaIni) ? d.preco / lpaIni : null;
    const fonteLinha = (() => { const S = d.lpaSec && d.lpaSec.status === 'ok' ? d.lpaSec : null;
      if (S && S.trimestres && S.trimestres.length) return `Fonte: ${d.lpaFonte || 'Yahoo Finance'} · release XTXX · ${d.balanco && d.balanco.data ? d.balanco.data : ''}`;
      return d.lpaFonte ? `Fonte: ${d.lpaFonte}` : ''; })();

    // HIERARQUIA DO LPA (27/11/2026, a pedido do usuário): TTM é o único LPA que entra no cálculo
    // de P/L (REGRA TRAVADA acima) - os outros 3 valores (início do ano, previsão atual, ajustado)
    // são só referência/contexto, nunca o LPA usado. Por isso TTM fica em destaque na própria linha
    // do cálculo (acima), e os outros 3 viram 1 única linha pequena/cinza, sem o peso visual de
    // linhas separadas em negrito - "Início do ano" é o guidance CONGELADO no começo do ano fiscal
    // (não muda); "Contábil 12 meses (TTM)" acima é o que realmente atualiza a cada balanço.
    const contexto = [
      lpaIni ? `Início do ano ${din(lpaIni)}${GI.ano ? ` (${GI.ano})` : ''}` : null,
      tem(lpaPrev) ? `Previsão atual${anoPrev ? ` (${anoPrev})` : ''} ${din(lpaPrev)}${lpaGuia ? ' · guidance' : lpaCons ? ' · consenso' : ''}` : null,
    ].filter(Boolean);
    const linhasMedias = [
      tem(d.lpaMedio3a) ? `3 anos ${din(d.lpaMedio3a)}` : null,
      tem(d.lpaMedia5a) ? `5 anos ${din(d.lpaMedia5a)}` : null,
      tem(d.lpaMedia10a) ? `10 anos ${din(d.lpaMedia10a)}` : null,
    ].filter(Boolean);

    // Dividendos (item 14, unificado 27/11/2026): ANTES o mesmo dividendo aparecia em 3 lugares
    // com 3 valores diferentes (pago/declarado/projetado) sem dizer qual era qual - parecia erro.
    // Agora as 3 linhas ficam juntas, nomeadas, só aqui - "Indicadores" não repete mais o valor
    // bruto do dividendo (só o Dividend Yield, uma conta diferente). DF = utils.dados_fixos (CVM,
    // declarado); d.dividendo = Yahoo (pago); d.guidance.dividendo = projeção da empresa.
    const DF = d.dadosFixos, temDF = DF && DF.status === 'ok';
    const cortou = tem(d.dividendo12Atras) && d.dividendo12Atras > 0 && d.dividendo < d.dividendo12Atras * 0.95;
    const linhasDiv = [
      tem(d.dividendo) ? ['Pago (365 dias)', din(d.dividendo)] : null,
      temDF && tem(DF.dividendo12m) ? ['Declarado (CVM)', din(DF.dividendo12m)] : null,
      d.guidance && tem(d.guidance.dividendo) ? [`Projetado${anoPrev ? ` ${anoPrev}` : ''}`, `${din(d.guidance.dividendo)} · DY ${f(d.guidance.dividendo / d.preco * 100, 1)}%`] : null,
      tem(dy) ? ['DY atual (sobre o pago)', `${f(dy)}%`] : null,
      tem(d.dyMedio12) ? ['DY média 12m', `${f(d.dyMedio12)}%`] : null,
    ].filter(Boolean);
    const fraseDiv = !tem(dy) ? ''
      : naoPagadora ? (d.dividendo > 0 ? `A ${d.ticker} quase não paga dividendo; reinveste quase todo o lucro na própria empresa. É o perfil da empresa, para quem busca crescimento, não renda.`
          : `A ${d.ticker} não pagou dividendo nos últimos 12 meses. É o perfil de quem reinveste o lucro, não necessariamente um problema.`)
      : cortou ? `Dividendo reduzido vs 12 meses atrás: de ${din(d.dividendo12Atras)} para ${din(d.dividendo)} por ação.` : '';
    // UMA única nota explicando os 3 métodos do dividendo (antes repetida, com texto diferente,
    // em 3 cards - unificado 27/11/2026 a pedido do usuário).
    const notaDiv = 'Pago = dinheiro que caiu na sua conta nos últimos 365 dias corridos (Yahoo Finance). '
      + 'Declarado = valor aprovado pela empresa, somado dos últimos 4 trimestres na CVM.'
      + (d.guidance && tem(d.guidance.dividendo) ? ' Projetado = estimativa da empresa pro ano em curso, ainda não paga nem declarada.' : '')
      + ' Pago e declarado quase nunca batem exatamente - são 2 datas diferentes (pagamento x aprovação), não um erro.';

    el.innerHTML = `<h2>Lucro e Preço vs Lucro</h2>
      <div class="pilha">
        <div class="card">
          ${bolaAtualizacao(d.atualizacao)}
          ${prejuizo ? `<div class="destaque" style="color:var(--vermelho)">A empresa teve prejuízo nos últimos 12 meses: a relação preço/lucro não se aplica.</div>` : !tem(d.pl) ? `<div class="nota">${INDISP}</div>` : `
          <div class="duas"><span class="rot">Cotação ÷ LPA contábil TTM = P/L</span></div>
          <div class="nota num" style="margin-top:2px;font-size:15px">${f(d.preco)} ÷ <b style="color:var(--texto);font-size:17px">${f(d.lpa)}</b> = <b style="color:var(--texto);font-size:17px">P/L ${f(d.pl)}</b></div>
          ${contexto.length || tem(lpaAjustado) ? `<div class="nota" style="margin-top:6px;opacity:.85">${[...contexto, tem(lpaAjustado) ? `[Ajustado] ${din(lpaAjustado)}${tem(plAjustado) ? ` · P/L ${f(plAjustado)}` : ''}` : null].filter(Boolean).join(' · ')}</div>` : ''}
          ${linhasMedias.length ? `<div class="nota num" style="margin-top:8px">Média: ${linhasMedias.join(' • ')}</div>` : ''}
          ${tem(d.plMedio12) ? `<div class="nota num" style="margin-top:4px">P/L médio 12m: ${f(d.plMedio12)}${tem(d.pl) ? ` (vs. P/L atual ${f(d.pl)})` : ''}</div>` : ''}
          `}
          ${fonteLinha ? `<div class="nota" style="margin-top:10px">${fonteLinha}</div>` : ''}
        </div>
        <div class="card">
          <strong>Dividendos</strong>
          ${linhasDiv.length ? `<div class="lista-v num" style="margin-top:8px">${linhasDiv.map(([r, v]) => `<div>${r}<b>${v}</b></div>`).join('')}</div>` : `<div class="nota" style="margin-top:8px">${INDISP}</div>`}
          ${linhasDiv.length ? `<div class="nota" style="margin-top:6px">${notaDiv}</div>` : ''}
          ${fraseDiv ? `<p class="nota" style="margin-top:8px">${fraseDiv}</p>` : ''}
        </div>
      </div>`;
  })($('fundamentos'));

  /* ---------------- indicadores */
  (function Indicators(el) {
    const difPL = tem(d.pl) && tem(d.plMedio12) && d.plMedio12 > 0 ? (d.pl / d.plMedio12 - 1) * 100 : null;
    const q = qtd(d.acoes);
    const medioSub = { trimestral: 'com o LPA de cada trimestre', contabil: 'com o lucro contábil de cada balanço', simplificado: 'preço médio do ano ÷ LPA atual' }[d.plMetodo] || '';
    // Campos que só existiam no bloco "Dados fixos" (removido, unificação de 27/11/2026) -
    // utils.dados_fixos.buscar_fixos_br continua a camada de dados interna (contabil_br.json /
    // contabil_br_config.json), só não tem mais seção própria: Ações em circulação, Lucro líquido
    // do período, fonte CVM e data de encerramento migraram pra cá.
    const DF = d.dadosFixos;
    const temDF = DF && DF.status === 'ok';
    const fonteDF = temDF ? `${DF.fonteOficial || 'CVM'} · balanço de ${DF.dataUltimoBalanco || '—'}.` : '';
    const avisoHtml = (temDF && DF.avisoBalancoNovo) ? `<div class="aviso" style="margin-bottom:10px">${DF.avisoBalancoNovo}</div>` : '';
    const c = (rot, v, sub, dica) => [rot, v, sub, dica];
    const cartoes = [
      c('P/L atual', tem(d.pl) ? f(d.pl) : null, tem(difPL) ? `${sinal(difPL)} vs. média de 12m` : '', `Você paga ${din(d.pl)} para cada ${d.moeda} 1 de lucro. Conta: ${f(d.preco)} / ${f(d.lpa)} = ${f(d.pl)}`),
      c('P/L médio 12 meses', tem(d.plMedio12) ? f(d.plMedio12) : null, medioSub, d.plMetodo === 'simplificado' ? 'Estimativa: preço médio do ano dividido pelo LPA atual, porque o Yahoo não traz o lucro de cada trimestre.' : d.plMetodo === 'contabil' ? `Média do P/L de cada pregão desde ${d.mediaDesde}, com o lucro contábil em vigor em cada data.` : 'Média do P/L de cada pregão do último ano, com o lucro já divulgado em cada data.'),
      c('LPA básico', tem(d.lpa) ? din(d.lpa) : null, 'últimos 12 meses', `Lucro por ação. Cada ação ganhou ${din(d.lpa)} em 12 meses.${q ? ` Conta: Lucro / ${q} de ações` : ''}`),
      // Dividendo anual (pago/declarado/projetado) unificado no card "Dividendos" (bloco "Lucro e
      // Preço vs Lucro" acima, 27/11/2026) - aqui só o Dividend Yield, uma conta diferente (não
      // duplica o valor bruto do dividendo).
      c('Dividend yield', tem(dy) ? `${f(dy)}%` : null, tem(dy) ? `${f(d.dividendo)} / ${f(d.preco)}` : '', `Quanto o dividendo representa sobre o preço. ${f(d.dividendo)} / ${f(d.preco)} = ${f(dy)}%.${naoPagadora ? ` É baixo porque a ${d.ticker} reinveste o lucro, não porque está com problema.` : ''}`),
      c('Ações em circulação', q, 'quantos pedaços a empresa foi dividida', `A ${d.ticker} foi fatiada em ${q} de ações.${temDF ? ` Fonte: ${fonteDF}` : ''}`),
      c('Lucro líquido (12 meses)', temDF && tem(DF.lucro12m) ? `${f(DF.lucro12m / 1e9, 2)} bi` : null, 'declarado na CVM', `Lucro líquido total da empresa nos últimos 4 trimestres declarados na CVM. Fonte: ${fonteDF}`),
    ];
    // P/VP, Payout, ROE (Issue #35) - só existiam no bloco "Dados fixos" removido; reusam o
    // MESMO cálculo já feito em utils.dados_fixos.calcular_indicadores (d.dadosFixos.pvp/payout/
    // roe), nenhuma conta nova aqui. Ao contrário dos cartões acima, um card sem dado aqui SOME
    // (não mostra "Dados indisponíveis") - são indicadores extra, opcionais, não o núcleo da tela.
    const cartoesExtra = [
      temDF && tem(DF.pvp) ? c('P/VP', f(DF.pvp, 2), 'Preço / Valor Patrimonial por Ação',
        `P/VP = Preço ÷ VPA.${tem(DF.vpa) ? ` Conta: ${f(d.preco)} ÷ ${f(DF.vpa, 2)} = ${f(DF.pvp, 2)}.` : ''} Fonte: ${fonteDF}`) : null,
      temDF && tem(DF.payout) ? c('Payout', `${f(DF.payout * 100, 1)}%`, 'dividendo declarado ÷ LPA',
        `Payout = Dividendo declarado na CVM ÷ LPA.${tem(DF.dividendo12m) && tem(d.lpa) ? ` Conta: ${din(DF.dividendo12m)} ÷ ${din(d.lpa)} = ${f(DF.payout * 100, 1)}%.` : ''} Fonte: ${fonteDF}`) : null,
      temDF && tem(DF.roe) ? c('ROE', `${f(DF.roe * 100, 1)}%`, 'lucro líquido ÷ patrimônio líquido',
        `ROE = Lucro líquido (12 meses) ÷ Patrimônio líquido.${tem(DF.lucro12m) && tem(DF.patrimonioLiquido) ? ` Conta: ${f(DF.lucro12m / 1e9, 2)} bi ÷ ${f(DF.patrimonioLiquido / 1e9, 2)} bi = ${f(DF.roe * 100, 1)}%.` : ''} Fonte: ${fonteDF}`) : null,
    ].filter(Boolean);
    const todosCartoes = [...cartoes, ...cartoesExtra];
    el.innerHTML = `<h2>Indicadores</h2>
      <div class="sub">Dados de ${d.data} · Fonte: ${d.fonte} · <button class="link" data-folha="ind">Ver como calculamos</button></div>
      ${avisoHtml}
      <div class="grade2">${todosCartoes.map(([r, v, s, dica]) => v === null
        ? `<div class="ind"><span class="rot">${r}</span><span class="s" style="margin-top:8px">${INDISP}</span></div>`
        : `<button class="ind" aria-expanded="false"><span class="rot">${r}</span><span class="v num">${v}</span><span class="s num">${s}</span><span class="dica">${dica}</span></button>`).join('')}</div>`;
    el.querySelectorAll('button.ind').forEach(b => { b.onclick = () => {
      const abrir = b.getAttribute('aria-expanded') !== 'true';
      el.querySelectorAll('button.ind').forEach(o => o.setAttribute('aria-expanded', 'false')); b.setAttribute('aria-expanded', abrir);
    }; });
    FOLHAS.ind = () => ['Como calculamos os indicadores', `
      <p><b>P/L atual</b></p>${tem(d.pl) ? `<code>${f(d.preco)} ÷ ${f(d.lpa)} = ${f(d.pl)}</code>` : `<p>${INDISP}.</p>`}
      <p><b>Dividend yield</b></p>${tem(dy) ? `<code>${f(d.dividendo)} ÷ ${f(d.preco)} = ${f(dy)}%</code>` : `<p>${INDISP}.</p>`}
      <p><b>LPA básico:</b> lucro líquido dos últimos 12 meses dividido pelo número de ações.</p>
      <p>Dividendo pago/declarado/projetado: card "Dividendos", no bloco "Lucro e Preço vs Lucro" acima.</p>
      <p>Toque em um cartão para ver a explicação dele.</p>${fonte}`];
  })($('indicadores'));

  /* ---------------- retorno acumulado: MOVIDO pra fora deste componente (27/11/2026) - vira
     bloco nativo do Streamlit (components/retorno_chart.py + app._retorno_bloco), mesma regra do
     gráfico de LPA (nenhuma barra desenhada com div/CSS). Ver nota no topo deste arquivo. */

  /* ---------------- sincronia de modo (NOVO, só nesta 2ª metade): os botões CONSERVADOR/
     CRESCIMENTO/QUANTITATIVO ficam todos na 1ª metade (tela/detalhe.js) - esta metade não tem
     como saber sozinha quando o modo muda. Lê o modo salvo ao montar (mesma chave usada lá) e
     escuta o evento que a 1ª metade dispara a cada clique de aba, aplicando a MESMA regra SECOES
     que esses 3 cards já tinham (fundamentos/indicadores/retorno somem no modo Quantitativo). */
  const SECOES_FUNDO = { fundamentos: ['graham', 'lynch'], indicadores: ['graham', 'lynch'] };
  function aplicarModo(modo) {
    Object.entries(SECOES_FUNDO).forEach(([id, modos]) => { const el = $(id); if (el) el.hidden = !modos.includes(modo); });
  }
  let modoInicial = 'graham';
  try { modoInicial = sessionStorage.getItem('fintai-modo') || 'graham'; } catch (e) { /* sem armazenamento */ }
  if (!['graham', 'lynch', 'simons'].includes(modoInicial)) modoInicial = 'graham';
  aplicarModo(modoInicial);
  const aoMudarModo = e => aplicarModo(e.detail.modo);
  document.addEventListener('fintai-modo-mudou', aoMudarModo);
  limpar.push(() => document.removeEventListener('fintai-modo-mudou', aoMudarModo));

  return () => limpar.forEach(fn => fn());
}

export default function (component) {
  const { data, parentElement } = component;
  if (!data || !data.dados) return;
  if (parentElement.__fintaiLimparFundo) { try { parentElement.__fintaiLimparFundo(); } catch (e) { /* já desmontado */ } }
  parentElement.__fintaiLimparFundo = montar(parentElement, data.dados);
  return parentElement.__fintaiLimparFundo;
}
