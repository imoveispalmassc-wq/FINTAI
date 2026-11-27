/* Tela de detalhes da ação. Lê tudo de um único pacote de dados (montado em tela/dados.py):
   nenhum número é digitado aqui. Dado ausente vira "Dados indisponíveis". */

const INDISP = 'Dados indisponíveis';

const tem = v => v !== null && v !== undefined && Number.isFinite(v);
const f = (v, casas = 2) => tem(v) ? v.toLocaleString('pt-BR', { minimumFractionDigits: casas, maximumFractionDigits: casas }) : '—';
const sinal = (v, casas = 2) => tem(v) ? `${v > 0 ? '+' : v < 0 ? '-' : ''}${f(Math.abs(v), casas)}%` : '—';
const ret = v => sinal(v, tem(v) && Math.abs(v) >= 100 ? 0 : 1);
const seta = v => (v >= 0 ? '▲' : '▼');
const cor = v => (v >= 0 ? 'var(--verde)' : 'var(--vermelho)');
const posicao = (v, min, max) => max <= min ? 50 : Math.max(0, Math.min(100, (v - min) / (max - min) * 100));
// afasta rótulos que ficariam colados/sobrepostos numa régua 0-100% (ex. ativo perto da mínima de
// 52 semanas, com a zona de oportunidade muito estreita, ou rótulos largos de ativos com preço na
// casa dos milhares): só move o texto, não o traço da zona. `folgas` é a distância mínima que CADA
// ponto precisa do vizinho (ex. metade da largura do próprio rótulo, se ele for centralizado) -
// não um valor fixo igual pra todos, já que rótulos mais largos (ex. "1.999,96") precisam de mais
// espaço do que rótulos curtos (ex. "14,65"). `folgaEsq`/`folgaDir` são a folga extra precisada só
// nas pontas (0%/100%), pelos rótulos fixos da borda (ex. mínima/máxima da régua).
const afastar = (posicoes, folgas, folgaEsq = 0, folgaDir = 0) => {
  const p = posicoes.slice();
  if (!p.length) return p;
  const g = folgas || posicoes.map(() => 8.5);   // sem folgas por rótulo: mantém o antigo padrão (17 ÷ 2)
  if (p[0] < folgaEsq + g[0]) p[0] = folgaEsq + g[0];
  for (let i = 1; i < p.length; i++) { const precisa = g[i - 1] + g[i]; if (p[i] - p[i - 1] < precisa) p[i] = p[i - 1] + precisa; }
  const ult = p.length - 1;
  if (p[ult] > 100 - folgaDir - g[ult]) p[ult] = 100 - folgaDir - g[ult];
  for (let i = p.length - 2; i >= 0; i--) { const precisa = g[i] + g[i + 1]; if (p[i + 1] - p[i] < precisa) p[i] = p[i + 1] - precisa; }
  return p;
};
// as 2 bolinhas (hoje cheia, 18px; 7 dias atrás vazada, 10px) nunca podem ficar tão perto a ponto de uma
// esconder a outra - afasta o mínimo necessário (raio de cada uma + respiro), só quando precisa
const afastarBolinhas = (largContainerPx, posHoje, pos7) => {
  if (pos7 === null || pos7 === undefined) return [posHoje, pos7];
  const pxParaPct = px => px / Math.max(largContainerPx, 100) * 100;
  const folgaHoje = pxParaPct(9 + 2), folga7 = pxParaPct(5 + 2);
  const pontos = [{ k: 'hoje', pos: posHoje, folga: folgaHoje }, { k: 'd7', pos: pos7, folga: folga7 }]
    .sort((a, b) => a.pos - b.pos);
  const ajust = afastar(pontos.map(x => x.pos), pontos.map(x => x.folga));
  const mapa = {}; pontos.forEach((x, i) => { mapa[x.k] = ajust[i]; });
  return [mapa.hoje, mapa.d7];
};
const p2 = n => String(n).padStart(2, '0');
const MESES = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
// os instantes chegam como horário local da bolsa gravado em UTC
const ROTULO_X = {
  hora: t => `${p2(t.getUTCHours())}:${p2(t.getUTCMinutes())}`,
  dia: t => `${p2(t.getUTCDate())}/${p2(t.getUTCMonth() + 1)}`,
  mes: t => `${MESES[t.getUTCMonth()]}/${String(t.getUTCFullYear()).slice(2)}`,
  ano: t => String(t.getUTCFullYear()),
};
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
  const app = root.querySelector('.app');
  const din = (v, casas = 2) => tem(v) ? `${d.moeda} ${f(v, casas)}` : '—';
  // bolinha de atualização (verde <2h, amarelo <24h, vermelho 24h+) a partir de {em, iso, tri, triData}
  const bolaAtualizacao = (A, extra = '') => {
    if (!A || !A.em) return '';
    const h = (Date.now() - Date.parse(A.iso)) / 36e5, bola = h < 2 ? '🟢' : h < 24 ? '🟡' : '🔴';
    const [dia, hora] = A.em.split(' ');
    return `<div class="atualiz" title="Verde: atualizado há menos de 2h. Amarelo: menos de 24h. Vermelho: 24h ou mais sem atualizar.">${bola} Atualizado em ${dia} às ${hora}${A.tri ? `<br><span class="i">Contábil 12m até ${A.tri}${A.triData ? ` (${A.triData})` : ''}</span>` : ''}${extra}</div>`;
  };
  const limpar = [];
  const ex = chave => (d.exemplos && d.exemplos[chave] ? ' <span class="tag-proto">EXEMPLO</span>' : '');
  // mini gráfico de barras (item 4, 27/11/2026) - reaproveita valores já mostrados na tela (nunca
  // busca/calcula nada novo); pontos sem valor (ex.: ano sem dado) viram uma barra vazia, nunca
  // inventam um número. `proj` marca a barra de projeção/guidance com um estilo diferente (tracejado).
  // `fantasma` (opcional, 27/11/2026): valor antigo de referência (ex. guidance do início do ano,
  // já revisado) marcado como uma linha pontilhada fina sobre a própria barra - entra na escala
  // (pro traço nunca estourar a altura do gráfico) mas nunca vira uma barra própria, pra não ter o
  // mesmo peso visual dos números atuais.
  const miniBarras = (pontos, formatar) => {
    const vals = pontos.flatMap(p => [p.v, p.fantasma]).filter(tem);
    if (!vals.length) return '';
    const max = Math.max(...vals.map(Math.abs), 1e-9);
    return `<div class="mini-barras">${pontos.map(p => {
      const vazio = !tem(p.v);
      const h = vazio ? 0 : Math.max(4, Math.round(Math.abs(p.v) / max * 54));
      const hFant = tem(p.fantasma) ? Math.max(4, Math.round(Math.abs(p.fantasma) / max * 54)) : null;
      return `<div class="mini-barra"><span class="mb-val">${vazio ? '—' : formatar(p.v)}</span>
        <div class="mb-col">${hFant != null ? `<div class="mb-fantasma" style="bottom:${hFant}px" title="${p.fantasmaTitulo || ''}"></div>` : ''}<div class="mb-cheia${p.proj ? ' proj' : ''}${!vazio && p.v < 0 ? ' neg' : ''}" style="height:${h}px"></div></div>
        <span class="mb-rot">${p.rot}</span></div>`;
    }).join('')}</div>`;
  };
  const FOLHAS = {};
  const fonte = `<p><b>Fonte:</b> ${d.fonte} · atualizado em ${d.atualizado}.</p>`;
  // Selo de Fundamentos (issue #47, item 11): fato de fundamento, nunca recomendação - fica
  // abaixo da "Faixa inferior". Só aparece quando o robô teve histórico trimestral suficiente
  // para calcular com segurança (lucro contábil, ROE e dividendo vs 12 meses atrás); sem isso,
  // d.seloFundamentos vem null e o selo simplesmente não aparece (nunca inventa comparação -
  // ver limitação documentada no CLAUDE.md).
  const seloFundamentosHtml = () => {
    const S = d.seloFundamentos;
    if (!S || !S.nivel) return '';
    const CLASSE = { 1: 'selo-fund-1', 2: 'selo-fund-2', 3: 'selo-fund-3' }[S.nivel] || 'selo-fund-1';
    return `<div class="selo-fund ${CLASSE}"><b>${S.titulo}</b><span>${S.subtexto}</span></div>`;
  };
  // faixa de preço do período escolhido no gráfico: 52 semanas (padrão), 5 anos ou todo o histórico
  const FAIXA_PADRAO = { min: d.min52, max: d.max52, zOport: d.zOport, zCara: d.zCara, decisao: d.decisao,
    rotulo: 'Últimas 52 semanas', curto: '52 semanas', testada: true };
  let faixaK = '1a', fx = FAIXA_PADRAO, zOport = fx.zOport, zCara = fx.zCara;
  function aplicarFaixa(escala) {
    const k = escala === '5a' || escala === 'max' ? escala : '1a';
    faixaK = d.faixas && d.faixas[k] ? k : '1a';
    fx = (d.faixas && d.faixas[faixaK]) || FAIXA_PADRAO;
    zOport = fx.zOport; zCara = fx.zCara;
  }
  aplicarFaixa('1a');
  // rótulo embaixo da bolinha: centrado nela; perto das pontas, alinhado à ponta para não sair da barra
  const ancora = p => p < 8 ? 'left:0;transform:none;text-align:left'
    : p > 92 ? 'left:auto;right:0;transform:none;text-align:right' : `left:${p}%`;
  const dy = tem(d.dividendo) && d.preco ? d.dividendo / d.preco * 100 : null;
  const naoPagadora = tem(dy) && dy < 0.5;

  /* ---------------- folha "Ver como calculamos" */
  function abrirFolha(titulo, html) {
    $('folha-t').textContent = titulo; $('folha-c').innerHTML = html; $('fundo').hidden = false; $('folha-x').focus();
  }
  const fecharFolha = () => { $('fundo').hidden = true; };
  $('folha-x').onclick = fecharFolha;
  $('fundo').onclick = e => { if (e.target === $('fundo')) fecharFolha(); };
  const tecla = e => { if (e.key === 'Escape') fecharFolha(); };
  document.addEventListener('keydown', tecla); limpar.push(() => document.removeEventListener('keydown', tecla));
  app.onclick = e => {
    const b = e.target.closest('[data-folha]');
    if (b && FOLHAS[b.dataset.folha]) { const [t, h] = FOLHAS[b.dataset.folha](); abrirFolha(t, h); }
  };

  /* ---------------- topo e decisão */
  $('t-nome').textContent = d.nome;
  $('t-bolsa').textContent = d.bolsa ? `${d.bolsa} (${d.ticker})` : d.ticker;
  // cabeçalho fixo (sticky, CSS): nome completo + bolsa + preço no topo da página. Ao rolar (classe
  // .rolou, abaixo), esconde nome completo/bolsa e mostra só o ticker + a cotação + a variação do
  // dia (ex. "MU  US$ 601,25  ▼ -4,53%", a pedido do usuário) - mesma cor/seta/sinal do resto da tela.
  $('t-preco').textContent = din(d.preco);
  $('t-preco').style.color = tem(d.varDia) ? cor(d.varDia) : '';
  $('t-var').textContent = tem(d.varDia) ? `${seta(d.varDia)} ${sinal(d.varDia)}` : '';
  $('t-var').style.color = tem(d.varDia) ? cor(d.varDia) : '';
  $('t-ticker').textContent = d.ticker;
  const topoEl = root.querySelector('.topo');
  const sentinela = $('t-sentinela-topo');
  if (topoEl && sentinela && typeof IntersectionObserver === 'function') {
    // BUG CORRIGIDO (27/11/2026, investigação com a app real): não existe iframe nenhum aqui - o
    // st.components.v2.component (BidiComponent) monta o conteúdo direto numa shadow root
    // (mode=open) dentro da própria página do Streamlit (confirmado: document.querySelectorAll
    // ('iframe').length === 0 na app rodando de verdade). "position: sticky" no CSS já funciona
    // sozinho (confirmado prendendo .topo no topo real da tela ao rolar o #stMain, o scroll de
    // verdade do Streamlit) - uma versão anterior deste código chegou a supor um iframe e tentar
    // corrigir via window.parent + position:fixed (nunca existiu iframe pra isso valer) - removido.
    // 2º BUG, achado só com a app real rodando (document.querySelector('.topo') sempre null aqui,
    // por isso a classe "rolou" nunca ligava - nem no antigo código do iframe, nem numa 1ª tentativa
    // de corrigi-lo escutando scroll em document/window): ".topo" vive dentro da shadow root deste
    // componente, e consulta de CSS feita a partir do "document" de fora (bare document.querySelector)
    // NUNCA enxerga pra dentro de uma shadow root - é assim que shadow DOM isola por design. Por
    // isso topoEl sempre dava null e o "if" inteiro nunca rodava, silenciosamente (sem erro nenhum).
    // Correção: usar "root" (o parâmetro desta função, a própria raiz do componente - mesma técnica
    // que o helper $() já usa) em vez de "document" pra achar elementos do próprio componente.
    // Com isso resolvido, ainda falta como DETECTAR o scroll: o scroll de verdade do Streamlit
    // acontece dentro de um <main id="stMain"> interno (overflow:auto) - nunca na window/document -,
    // e mesmo escutando no "document" certo (document.addEventListener('scroll', fn, {capture:true})
    // pega eventos de QUALQUER elemento da página, inclusive #stMain), isso dependeria de um "id"
    // interno do Streamlit que pode mudar de versão pra versão. Por isso a detecção usa
    // IntersectionObserver em vez de escutar evento de scroll: ele mede a posição real do elemento
    // na tela (root: null = viewport de verdade) e dispara sozinho, não importa qual ancestral rolou
    // nem como. Observa uma sentinela de 1px logo ACIMA do cabeçalho (t-sentinela-topo no HTML):
    // quando ela sai da tela (intersectionRatio 0), o cabeçalho já colou no topo - liga "rolou";
    // quando ela volta a aparecer, desliga.
    const io = new IntersectionObserver(
      (entradas) => { topoEl.classList.toggle('rolou', entradas[0].intersectionRatio === 0); },
      { threshold: [0] }
    );
    io.observe(sentinela);
    limpar.push(() => io.disconnect());

    // 3º BUG, só visível com .rolou já ligando de verdade: o Streamlit tem a sua PRÓPRIA barra fixa
    // no topo (header com o menu/Deploy, fora da shadow root deste componente), position:absolute,
    // top:0, com z-index MUITO alto (999990) - mesmo com .topo preso em top:0 (sticky) e z-index:20,
    // essa barra do Streamlit fica por cima e esconde o cabeçalho fixo inteiro atrás dela. Medindo a
    // altura real dessa barra (quando existir) e somando ao "top" do sticky, o cabeçalho fixo cola
    // logo ABAIXO da barra do Streamlit, visível, em vez de atrás dela. Sem essa barra (ex.: página
    // de exemplo fora do Streamlit), fica 0 como antes - nunca inventa um valor fixo em pixels, que
    // quebraria se o Streamlit mudar a altura da própria barra numa versão futura.
    const barraStreamlit = document.querySelector('[data-testid="stHeader"]');
    topoEl.style.top = barraStreamlit ? `${barraStreamlit.getBoundingClientRect().height}px` : '0';
  }
  let modo = 'graham';
  try { modo = sessionStorage.getItem('fintai-modo') || 'graham'; } catch (e) { /* sem armazenamento */ }
  if (!['graham', 'lynch', 'simons'].includes(modo)) modo = 'graham';
  let aoMudarModo = () => {};

  function renderDecisao() {
    const el = $('decisao');
    // O badge e o texto desta função nunca usam palavra de julgamento ("Oportunidade"/"Evitar")
    // nem verbo de recomendação ("AGUARDAR") - só o nome neutro da zona (Faixa inferior/Neutro/
    // Faixa superior), igual ao resto da tela desde a Issue #47, item 10. `classe` (COMPRAR/CARO,
    // usada só pra cor do badge) continua interna, nunca mostrada como texto. A pequena pílula que
    // repetia a mesma zona embaixo do badge foi removida por ficar redundante com o próprio rótulo.
    let rotulo, classe = '', texto, extra = '';
    if (modo === 'graham') {
      const C = d.conservadorFaixa;
      if (C) {
        // Faixa de preço por valuation (âncora = preço médio de 1 ano), não a faixa histórica
        // de 52 semanas: nunca tem teste histórico, por isso sempre "SEM TESTE".
        const e = C.decisao; rotulo = e.rotulo; texto = e.texto;
        classe = e.codigo === 'COMPRAR' ? 'COMPRAR' : e.codigo === 'CARO' ? 'CARO' : '';
      } else {
        const e = fx.decisao; rotulo = e.rotulo; texto = e.texto;
        classe = e.codigo === 'COMPRAR' ? (e.validado ? 'COMPRAR' : '') : e.codigo === 'CARO' ? 'CARO' : '';
      }
    } else if (modo === 'lynch') {
      // Lynch só pela MM200 (ignora a faixa 30/70): faixa inferior de -10% a +5%, neutro até +15%, faixa superior acima
      const LP = d.lynch.preco, e = LP || fx.decisao, v = d.lynch.veredito; rotulo = e.rotulo; texto = e.texto;
      classe = e.codigo === 'COMPRAR' ? (LP || e.validado ? 'COMPRAR' : '') : e.codigo === 'CARO' ? 'CARO' : '';
      const zona = LP && LP.zona === 'Bem abaixo da MM200' ? 'faixa Bem abaixo da MM200' : { COMPRAR: 'Faixa inferior', AGUARDAR: 'Zona neutra', CARO: 'Faixa superior' }[e.codigo];
      const conclusao = v.cor === 'verde'
        ? (e.codigo === 'COMPRAR' ? 'Crescimento aprovado e o preço está na Faixa inferior.'
          : `Crescimento aprovado, mas o preço está na ${zona}.`)
        : v.cor === 'amarelo' ? `Fica de olho no crescimento, e o preço está na ${zona}.`
        : v.cor === 'vermelho' ? `Não compra pelo crescimento, qualquer que seja o preço. O preço está na ${zona}.`
        : `Sem PEG para avaliar o crescimento. O preço está na ${zona}.`;
      const stV = { verde: 'bom', vermelho: 'ruim' }[v.cor] || 'neutro';
      extra = `<div class="lynch-linha"><span class="st ${stV}">${v.titulo}</span>${ex('lucroLongo') || ex('receitaProx')}
        ${tem(d.lynch.pegFuturo) ? `<div class="nota num" style="margin-top:8px">PEG = P/L ${f(d.pl)} / Crescimento ${f(d.lynch.futuro.lucroLongo, 1)}% = ${f(d.lynch.pegFuturo)}</div>` : ''}
        <div class="destaque">${conclusao}</div></div>`;
    } else {
      const sm = d.simons, hA = sm.histAtual;
      const R = { OPORTUNIDADE: ['Faixa inferior', 'COMPRAR'], NEUTRO: ['Neutro', 'AGUARDAR'], CARO: ['Faixa superior', 'CARO'] }[sm.classe] || [sm.acao, ''];
      rotulo = R[0]; classe = R[1];
      const mmTxt = tem(sm.mm200) ? `Média 200d ${din(sm.mm200)}: preço ${sinal(sm.distMM200, 1)} ${sm.distMM200 < 0 ? 'abaixo' : 'acima'}${sm.mm200Caindo ? ', média caindo' : ''}.` : 'Sem média de 200 dias (histórico curto).';
      const diasTxt = sm.dias ? `${sm.dias} ${sm.dias === 1 ? 'dia' : 'dias'} de queda desde o topo${sm.altas ? ` (${sm.altas} ${sm.altas === 1 ? 'alta' : 'altas'} no meio)` : ''}, ${sinal(sm.queda)}` : 'sem queda no último pregão';
      texto = `1. ${mmTxt} 2. ${sm.classe === 'OPORTUNIDADE' ? 'Faixa inferior' : sm.classe === 'CARO' ? 'Faixa superior' : 'Neutro'} (faixa de 52 semanas: ${(sm.zona52 || '').toLowerCase()}). 3. ${diasTxt}: ${sm.entrada}. ${sm.entradaDetalhe}.`
        + (hA && hA.vezes && sm.classe === 'OPORTUNIDADE' ? ` Histórico da ação: subiu no dia seguinte em ${f(hA.pct, 0)}% de ${hA.vezes} ${hA.vezes === 1 ? 'vez' : 'vezes'}${hA.vezes < 20 ? ' (poucos casos)' : ''}.` : '')
        // limite da PRÓPRIA zona em que o preço está, mesma regra travada de utils.signals.decidir_estado
        + (sm.classe === 'OPORTUNIDADE' ? ` Faixa inferior até ${din(sm.oportunidadeAte)}.`
          : sm.classe === 'CARO' ? ` Faixa superior acima de ${din(sm.caraAcima)}.`
          : ` Faixa neutra a partir de ${din(sm.oportunidadeAte)}.`);
    }
    const nome = document.createElement('div'); nome.className = 'razao'; nome.textContent = `${d.razao} · ${d.ticker}`;
    el.innerHTML = `<div class="decisao">
      <div class="meta">Último pregão ${d.data} · ${d.codMoeda}</div>
      <div class="linha"><span class="preco num">${din(d.preco)}</span>
        ${tem(d.varDia) ? `<span class="var num" style="color:${cor(d.varDia)}">${seta(d.varDia)} ${sinal(d.varDia)} no dia</span>` : ''}</div>
      ${d.after ? `<div class="after num" style="color:${cor(d.after.variacao)}">After Market: ${din(d.after.preco)} ${seta(d.after.variacao)} ${sinal(d.after.variacao)}${d.after.hora ? ` | ${d.after.hora}` : ''}</div>` : ''}
      <div><span class="badge ${classe}" id="d-rotulo"></span></div>
      <div class="ponto" id="d-texto"></div>
      ${extra}
    </div>`;
    el.firstElementChild.insertBefore(nome, el.firstElementChild.children[1]);
    $('d-rotulo').textContent = rotulo; $('d-texto').textContent = texto;
  }

  /* ---------------- gráfico */
  (function StockChart(el) {
    const ESCALAS = [['10d', '10D'], ['hoje', 'Hoje'], ['1s', '1S'], ['1m', '1M'], ['1a', '1A'], ['5a', '5A'], ['max', 'Máx.']];
    const series = d.series;
    let escala = series['1a'] ? '1a' : (ESCALAS.find(([k]) => k !== '10d' && series[k]) || [null])[0];
    if (!escala) { el.innerHTML = `<div class="aviso">${INDISP}</div>`; return; }
    let velas = false, prog = 1, toque = null, toqueY = 0, raf = 0;

    el.innerHTML = `<div class="grafico" id="gbox">
        <canvas id="gcanvas" role="img" aria-label="Gráfico de preço de ${d.ticker}"></canvas>
        <button class="expandir" id="gexp" aria-label="Expandir gráfico"><svg class="i" viewBox="0 0 24 24" style="width:17px;height:17px"><path d="M9 4H4v5M15 4h5v5M9 20H4v-5M15 20h5v-5"/></svg></button>
      </div>
      <div class="escalas" role="group" aria-label="Período do gráfico">
        ${ESCALAS.map(([k, r]) => `<button class="e" data-e="${k}" aria-pressed="${k === escala}" ${series[k] ? '' : 'disabled'}>${r}</button>`).join('')}
        <button class="vela" id="gvela" aria-pressed="false" aria-label="Alternar entre linha e candles"><svg class="i" viewBox="0 0 24 24" style="width:18px;height:18px"><path d="M8 3v4M8 15v6M16 3v6M16 17v4"/><rect x="5.5" y="7" width="5" height="8" rx="1"/><rect x="13.5" y="9" width="5" height="8" rx="1"/></svg></button>
      </div>
      <div class="legenda-var num"><span id="gvar"></span></div>
      <div class="legenda-zonas" id="glegenda"></div>`;

    const cv = $('gcanvas'), ctx = cv.getContext('2d');
    const css = n => getComputedStyle(app).getPropertyValue(n).trim();
    const base = s => (tem(s.base) ? s.base : s.c[0]);

    function desenhar() {
      const s = series[escala], n = s.c.length, dpr = window.devicePixelRatio || 1;
      const W = cv.clientWidth, H = cv.clientHeight;
      if (!W || !H) return;
      if (cv.width !== Math.round(W * dpr) || cv.height !== Math.round(H * dpr)) { cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, W, H);
      const zOportF = zOport, zCaraF = zCara;
      const eixoW = 58, x0 = 4, x1 = W - eixoW, yTop = 44, yBase = H - 22, volH = 30, yPlot = yBase - volH - 8;
      const hi = velas ? s.h.map((v, i) => (tem(v) ? v : s.c[i])) : s.c, lo = velas ? s.l.map((v, i) => (tem(v) ? v : s.c[i])) : s.c;
      // SIMONS: a escala inclui a MM200 e os limites da faixa, como no painel (preço aparece na zona em que está)
      const LPr = modo === 'lynch' && d.lynch && d.lynch.preco;
      const CgR = modo === 'graham' && d.conservadorFaixa;
      const refsS = modo === 'simons' ? [d.simons.mm200, d.simons.oportunidadeAte, d.simons.caraAcima, d.simons.bemAbaixoAte].filter(tem)
        : LPr && escala !== '5a' && escala !== 'max' ? [LPr.mm200, LPr.oportunidadeAte, LPr.caroAcima].filter(tem)
        : CgR && escala !== '5a' && escala !== 'max' ? [CgR.mm200, CgR.oportunidadeAte, CgR.caroAcima, CgR.limite3a, CgR.limite5a].filter(tem) : [];
      const vmin = Math.min(...lo, ...refsS), vmax0 = Math.max(...hi, ...refsS);
      // SIMONS 10D: espaço livre em cima para o % de cada dia de queda
      const vmax = modo === 'simons' && escala === '10d' ? vmax0 + (vmax0 - vmin) * 0.16 : vmax0, folga = (vmax - vmin) * 0.05 || 1;
      const Y = v => yPlot - (v - (vmin - folga)) / (vmax - vmin + 2 * folga) * (yPlot - yTop);
      const X = i => x0 + (x1 - x0) * (n === 1 ? 0 : i / (n - 1));
      ctx.font = '11px Inter, system-ui, sans-serif'; ctx.textBaseline = 'middle';

      // zonas, linhas e rótulos: nos modos Graham e Lynch
      if (modo !== 'simons') {
      const LPg = modo === 'lynch' && d.lynch && d.lynch.preco;
      const Cg = modo === 'graham' && d.conservadorFaixa;
      const zOport = LPg ? LPg.oportunidadeAte : Cg ? Cg.oportunidadeAte : zOportF;
      const zCara = LPg ? LPg.caroAcima : Cg ? Cg.caroAcima : zCaraF;
      // MM200: mesma régua da barra, repetida aqui como linha pontilhada - já existia no Lynch,
      // agora também no Conservador (Graham), só que esse é novo (antes só aparecia na barra)
      const mm200Ref = LPg ? LPg.mm200 : Cg ? Cg.mm200 : null;
      // limites de 3/5 anos (só no Conservador): mesmas 3 faixas de verde da barra, repetidas aqui
      const lim3aRef = Cg && tem(Cg.limite3a) ? Cg.limite3a : null;
      const lim5aRef = Cg && tem(Cg.limite5a) ? Cg.limite5a : null;
      ctx.save(); ctx.beginPath(); ctx.rect(x0, yTop - 6, x1 - x0, yPlot - yTop + 6); ctx.clip();
      if (Cg) {
        // 3 tons de verde dentro da zona de oportunidade, mais forte quanto mais fundo o preço -
        // mesma lógica e cores da barra (Faixa de preço)
        const fimClaro = lim3aRef ?? lim5aRef; // onde o tom mais claro termina (próximo limite existente)
        ctx.fillStyle = '#8fe3c41c'; ctx.fillRect(x0, Y(zOport), x1 - x0, fimClaro ? Y(fimClaro) - Y(zOport) : 4000);
        if (lim3aRef) { ctx.fillStyle = '#2fbf8a1c'; ctx.fillRect(x0, Y(lim3aRef), x1 - x0, lim5aRef ? Y(lim5aRef) - Y(lim3aRef) : 4000); }
        if (lim5aRef) { ctx.fillStyle = '#16805c1c'; ctx.fillRect(x0, Y(lim5aRef), x1 - x0, 4000); }
      } else {
        ctx.fillStyle = '#2fbf8a1c'; ctx.fillRect(x0, Y(zOport), x1 - x0, LPg ? Y(LPg.bemAbaixoAte) - Y(zOport) : 4000);
      }
      if (LPg) { ctx.fillStyle = '#5b8def1a'; ctx.fillRect(x0, Y(LPg.bemAbaixoAte), x1 - x0, 4000); }
      ctx.fillStyle = '#f06a6a1a'; ctx.fillRect(x0, Y(zCara) - 4000, x1 - x0, 4000);
      // tracejados das zonas: título e valor com espaço maior entre si, e a linha só começa depois
      // do próprio texto (nunca passa atrás dele). Todas numa única lista, cada uma com folga
      // mínima de 12px das outras (de baixo pra cima), pra nunca uma cair bem em cima da outra
      // quando os valores são próximos (ex. Oportunidade 1 e 2) ou iguais (Neutro e Caro, que
      // descrevem o mesmo valor de dois lados)
      // Bug original (auditoria 26/11/2026): "Faixa neutra até X" e "Faixa superior acima de X" eram
      // 2 linhas DIFERENTES desenhadas na MESMA altura (y = Y(zCara), o mesmo valor) - a regra de
      // afastar linhas próximas (abaixo) empurrava a segunda 12px pra baixo, fazendo "Faixa superior"
      // parecer visualmente ABAIXO de "Faixa neutra", o contrário do que elas significam.
      // Correção de verdade (não é só juntar o texto numa linha só): são 2 CONCEITOS diferentes,
      // cada um na SUA PRÓPRIA linha, mas em ALTURAS diferentes - nunca na mesma posição:
      // - "Faixa superior acima de X" fica na linha de zCara (é literalmente onde a zona superior
      //   começa - um valor único, igual a qualquer outra linha do gráfico).
      // - "Faixa neutra X a Y" (o INTERVALO inteiro, não só o teto) fica no MEIO da própria zona
      //   neutra (ponto médio entre zOport e zCara) - ela não tem uma única "linha" de fronteira
      //   própria (é delimitada por duas linhas que já existem: "Faixa inferior 1" embaixo e "Faixa
      //   superior" em cima), então o texto fica solto no meio da faixa, não grudado numa fronteira -
      //   isso também evita a confusão de antes (Faixa neutra aparecendo colada, ou implicando estar
      //   só "acima" da Média 200d quando a MM200 está dentro da própria faixa neutra).
      const linhas = [
        { y: Y(zCara), t: 'Faixa superior acima de', v: f(zCara), c: '#f06a6a' },
        { y: Y((zOport + zCara) / 2), t: 'Faixa neutra', v: `${f(zOport)} a ${f(zCara)}`, c: '#aab4c6' },
        ...(LPg ? [{ y: Y(LPg.bemAbaixoAte), t: 'Bem abaixo de', v: f(LPg.bemAbaixoAte), c: '#7aa2f7' }] : []),
        ...(tem(mm200Ref) ? [{ y: Y(mm200Ref), t: 'Média 200d', v: f(mm200Ref), c: '#f2994a' }] : []),
        { y: Y(zOport), t: 'Faixa inferior 1', v: f(zOport), c: '#2fbf8a' },
        ...(lim3aRef ? [{ y: Y(lim3aRef), t: 'Faixa inferior 2', v: f(lim3aRef), c: '#8fe3c4' }] : []),
        ...(lim5aRef ? [{ y: Y(lim5aRef), t: 'Faixa inferior 3', v: f(lim5aRef), c: '#1f9d72' }] : []),
      ];
      // Folga mínima entre linhas (bug corrigido, 27/11/2026): 12px dava certo na conta mas não no
      // texto de verdade - a fonte de 10.5px com textBaseline 'middle' ocupa ~13-14px de altura
      // (ascendente a descendente), e em telas de celular (área do gráfico mais compacta, 280px de
      // altura) 2 linhas próximas em valor (ex. Faixa inferior 2/3 da MU, 181,29 e 103,89) ficavam
      // com só ~11px de distância real - a regra "passou" (>= 12px não disparava) mas o texto já
      // sobrepunha visualmente. Testado com dados reais da MU (Playwright, viewport de celular):
      // 16px e 20px ainda deixavam o texto colado; 24px foi o primeiro valor que separou de verdade.
      const FOLGA_MIN_LINHA = 24;
      linhas.sort((a, b) => a.y - b.y);
      linhas.forEach((r, k) => { if (k && r.y - linhas[k - 1].y < FOLGA_MIN_LINHA) r.y = linhas[k - 1].y + FOLGA_MIN_LINHA; });
      // A cascata de afastar linhas só empurra pra baixo - com muitas linhas próximas (ex. PETR4:
      // Faixa superior + Média 200d + Faixa neutra + Faixa inferior 1/2/3, 6 linhas competindo pelo
      // mesmo espaço depois da Faixa neutra virar uma linha própria), a última podia passar do fundo
      // da área visível (yPlot, onde o clip() abaixo corta) e sumir da tela sem aviso nenhum. Desloca
      // TODAS as linhas pra cima juntas (mantém a distância entre elas) até a última caber.
      const sobra = linhas.length ? linhas[linhas.length - 1].y - yPlot : 0;
      if (sobra > 0) linhas.forEach(r => { r.y -= sobra; });
      ctx.textAlign = 'left'; ctx.font = '10.5px Inter, system-ui, sans-serif';
      linhas.forEach(r => {
        const texto = r.v ? `${r.t}    ${r.v}` : r.t;
        const largura = ctx.measureText(texto).width;
        ctx.setLineDash([5, 4]); ctx.strokeStyle = r.c; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(x0 + 10 + largura, r.y); ctx.lineTo(x1, r.y); ctx.stroke(); ctx.setLineDash([]);
        ctx.fillStyle = r.c; ctx.fillText(texto, x0 + 6, r.y);
      });
      ctx.font = '11px Inter, system-ui, sans-serif';
      ctx.restore();
      }

      // eixo Y
      const yPreco = Y(d.preco);
      ctx.textAlign = 'left';
      for (let k = 0; k < 6; k++) {
        const v = vmin + (vmax - vmin) * k / 5, y = Y(v);
        ctx.strokeStyle = '#26314766'; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(x0, y); ctx.lineTo(x1, y); ctx.stroke();
        if (modo !== 'simons' && Math.abs(y - yPreco) > 13) { ctx.fillStyle = css('--suave'); ctx.fillText(f(v), x1 + 7, y); }
      }

      // volume
      const vm = Math.max(...s.v, 1), bw = Math.max(1, (x1 - x0) / n * 0.6);
      ctx.fillStyle = '#8c99b040';
      for (let i = 0; i < n; i++) { if (i / (n - 1) > prog) break; const h = s.v[i] / vm * volH; ctx.fillRect(X(i) - bw / 2, yBase - h, bw, h); }

      // preço
      ctx.save(); ctx.beginPath(); ctx.rect(x0 - 2, 0, (x1 - x0) * prog + 4, H); ctx.clip();
      if (velas) {
        const cw = Math.max(1.5, (x1 - x0) / n * 0.62);
        for (let i = 0; i < n; i++) {
          const a = tem(s.o[i]) ? s.o[i] : s.c[i], c = s.c[i];
          ctx.strokeStyle = ctx.fillStyle = c >= a ? css('--verde') : css('--vermelho'); ctx.lineWidth = 1;
          ctx.beginPath(); ctx.moveTo(X(i), Y(hi[i])); ctx.lineTo(X(i), Y(lo[i])); ctx.stroke();
          ctx.fillRect(X(i) - cw / 2, Math.min(Y(a), Y(c)), cw, Math.max(1, Math.abs(Y(a) - Y(c))));
        }
      } else {
        ctx.beginPath(); s.c.forEach((c, i) => (i ? ctx.lineTo(X(i), Y(c)) : ctx.moveTo(X(i), Y(c))));
        ctx.strokeStyle = css('--azul'); ctx.lineWidth = 1.6; ctx.lineJoin = 'round'; ctx.stroke();
        ctx.lineTo(x1, yPlot); ctx.lineTo(x0, yPlot); ctx.closePath();
        const g = ctx.createLinearGradient(0, yTop, 0, yPlot); g.addColorStop(0, '#5b8def55'); g.addColorStop(1, '#5b8def00');
        ctx.fillStyle = g; ctx.fill();
      }
      ctx.restore();

      // linha e etiqueta do preço atual
      if (yPreco > yTop - 6 && yPreco < yPlot) {
        ctx.setLineDash([3, 3]); ctx.strokeStyle = 'rgba(255,255,255,.8)'; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(x0, yPreco); ctx.lineTo(x1, yPreco); ctx.stroke(); ctx.setLineDash([]);
        const etq = f(d.preco); ctx.font = '600 11px Inter, system-ui, sans-serif';
        const ew = ctx.measureText(etq).width + 12;
        ctx.fillStyle = css('--claro'); ctx.beginPath(); ctx.roundRect(x1 + 2, yPreco - 10, ew, 20, 7); ctx.fill();
        ctx.fillStyle = css('--tinta'); ctx.textAlign = 'left'; ctx.fillText(etq, x1 + 8, yPreco + 0.5);
      }

      // eixo X: 4 rótulos curtos, sem sobrepor
      ctx.font = '10.5px Inter, system-ui, sans-serif'; ctx.fillStyle = css('--suave'); ctx.textBaseline = 'alphabetic'; ctx.textAlign = 'center';
      let ultimo = '';
      if (escala === '10d') {
        ctx.font = '9.5px Inter, system-ui, sans-serif';
        for (let i = 0; i < n; i++) ctx.fillText(i === n - 1 ? 'Hoje' : String(i - (n - 1)), Math.max(x0 + 10, Math.min(X(i), x1 - 10)), H - 5);
      } else [0.06, 0.31, 0.56, 0.81].forEach(fr => {
        const i = Math.round((n - 1) * fr), txt = ROTULO_X[s.rot](new Date(s.t[i]));
        if (txt !== ultimo) ctx.fillText(txt, X(i), H - 5);
        ultimo = txt;
      });

      // legenda das zonas: HTML normal, fora da posição do gráfico (embaixo dele), não mais
      // desenhada em cima do canvas - evita colidir com qualquer linha/rótulo do próprio gráfico
      const elLeg = $('glegenda');
      if (elLeg) {
        const temMMLeg = (modo === 'lynch' && d.lynch && d.lynch.preco && tem(d.lynch.preco.mm200))
          || (modo === 'graham' && d.conservadorFaixa && tem(d.conservadorFaixa.mm200));
        const legL = modo === 'simons' ? [] : [['Inferior', '#2fbf8a'],
          ...(modo === 'lynch' && d.lynch && d.lynch.preco ? [['Bem abaixo', '#7aa2f7']] : []),
          ...(temMMLeg ? [['Média 200d', '#f2994a']] : []),
          ['Neutra', '#8c99b0'], ['Superior', '#f06a6a']];
        elLeg.innerHTML = legL.map(([t, c]) => `<span><i style="background:${c}"></i>${t}</span>`).join('');
      }

      // modo Simons, passos 1 e 2: MM200 e limites da faixa, iguais ao painel; valores no eixo da direita
      if (modo === 'simons') {
        const S = d.simons;
        const linhas = [[S.caraAcima, '#f06a6a', [5, 4]], [S.mm200, '#f2994a', [7, 4]], [S.oportunidadeAte, '#2fbf8a', [5, 4]], [S.bemAbaixoAte, '#7aa2f7', [3, 4]]].filter(l => tem(l[0]));
        ctx.save(); ctx.beginPath(); ctx.rect(x0, yTop - 6, x1 - x0, yPlot - yTop + 6); ctx.clip();
        if (tem(S.oportunidadeAte)) { ctx.fillStyle = '#2fbf8a14'; ctx.fillRect(x0, Y(S.oportunidadeAte), x1 - x0, tem(S.bemAbaixoAte) ? Y(S.bemAbaixoAte) - Y(S.oportunidadeAte) : 4000); }
        if (tem(S.bemAbaixoAte)) { ctx.fillStyle = '#5b8def14'; ctx.fillRect(x0, Y(S.bemAbaixoAte), x1 - x0, 4000); }
        if (tem(S.caraAcima)) { ctx.fillStyle = '#f06a6a12'; ctx.fillRect(x0, Y(S.caraAcima) - 4000, x1 - x0, 4000); }
        linhas.forEach(([v, c, dash]) => { ctx.setLineDash(dash); ctx.strokeStyle = c; ctx.lineWidth = 1.2; ctx.beginPath(); ctx.moveTo(x0, Y(v)); ctx.lineTo(x1, Y(v)); ctx.stroke(); });
        ctx.setLineDash([]); ctx.restore();
        // nome e valor escritos na própria linha, no canto esquerdo (afasta os que se encostam)
        const nomes = { '#f06a6a': 'Caro acima de', '#f2994a': 'Média 200d', '#2fbf8a': 'Oportunidade até', '#7aa2f7': 'Oportunidade desde' };
        const rots = linhas.map(([v, c]) => ({ y: Y(v) - 7, t: `${nomes[c]} ${f(v)}`, c })).sort((p, q) => q.y - p.y);
        rots.forEach((r, k) => { if (k && rots[k - 1].y - r.y < 15) r.y = rots[k - 1].y - 15; });
        ctx.font = '600 10.5px Inter, system-ui, sans-serif'; ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
        rots.forEach(r => { const w = ctx.measureText(r.t).width + 8; ctx.fillStyle = '#0e1420d9'; ctx.beginPath(); ctx.roundRect(x0 + 2, r.y - 7, w, 14, 4); ctx.fill(); ctx.fillStyle = r.c; ctx.fillText(r.t, x0 + 6, r.y + 0.5); });
        ctx.font = '11px Inter, system-ui, sans-serif';
      }

      // modo Simons, passo 3: dias de queda marcados, contador e termômetro
      if (modo === 'simons' && escala === '10d') {
        const sm = d.simons;
        for (let i = 0; i < n; i++) {   // um ponto por pregão; vermelho na sequência atual de queda
          const naQueda = i > n - 1 - sm.dias;
          ctx.fillStyle = naQueda ? css('--vermelho') : css('--azul');
          ctx.beginPath(); ctx.arc(X(i), Y(s.c[i]), naQueda ? 4 : 2.6, 0, 7); ctx.fill();
        }
        // % de cada dia da sequência em cima do ponto; alturas alternadas para os vizinhos não se encostarem
        ctx.font = '600 9.5px Inter, system-ui, sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
        for (let i = Math.max(1, n - sm.dias), k = 0; i < n; i++, k++) {
          const v = (s.c[i] / s.c[i - 1] - 1) * 100, t = sinal(v, 2), tw = ctx.measureText(t).width + 8;
          const x = Math.max(x0 + tw / 2, Math.min(x1 + 6, X(i))), y = Y(s.c[i]) - ((n - 1 - i) % 2 ? 26 : 12);
          ctx.strokeStyle = '#f06a6a55'; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(X(i), Y(s.c[i]) - 4); ctx.lineTo(X(i), y + 6); ctx.stroke();
          ctx.fillStyle = '#0e1420e6'; ctx.beginPath(); ctx.roundRect(x - tw / 2, y - 7, tw, 14, 4); ctx.fill();
          ctx.fillStyle = v < 0 ? css('--vermelho') : css('--verde'); ctx.fillText(t, x, y + 0.5);
        }
        ctx.textAlign = 'left';
        ctx.textAlign = 'left'; ctx.textBaseline = 'middle'; ctx.font = '600 11px Inter, system-ui, sans-serif';
        const rot = `${sm.dias} ${sm.dias === 1 ? 'dia' : 'dias'} de queda`, lw = ctx.measureText(rot).width, mx = sm.maximo || 5;
        ctx.fillStyle = '#0e1420cc'; ctx.beginPath(); ctx.roundRect(x0 + 44, 8, lw + 30 + mx * 11, 26, 8); ctx.fill();
        ctx.fillStyle = css('--texto'); ctx.fillText(rot, x0 + 52, 21);
        for (let k = 0; k < mx; k++) {
          ctx.beginPath(); ctx.arc(x0 + 64 + lw + k * 11, 21, 3.6, 0, 7);
          if (k < sm.nivel) { ctx.fillStyle = css('--azul'); ctx.fill(); }
          ctx.strokeStyle = css('--azul'); ctx.lineWidth = 1.5; ctx.stroke();
        }
      }

      // toque: cursor e balão com a variação
      if (toque !== null) {
        const i = Math.max(0, Math.min(n - 1, Math.round((toque - x0) / (x1 - x0) * (n - 1)))), x = X(i), y = Y(s.c[i]);
        ctx.strokeStyle = '#8c99b099'; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(x, yTop - 6); ctx.lineTo(x, yBase); ctx.stroke();
        ctx.fillStyle = css('--texto'); ctx.beginPath(); ctx.arc(x, y, 4.5, 0, 7); ctx.fill();
        ctx.strokeStyle = css('--azul'); ctx.lineWidth = 2; ctx.stroke();
        const v = (s.c[i] / base(s) - 1) * 100, txt = sinal(v, s.casas ?? 2) + (s.soPreco && i === n - 1 ? ' só preço' : '');
        ctx.font = '700 12px Inter, system-ui, sans-serif';
        const bw2 = ctx.measureText(txt).width + 18, bx = Math.max(x0, Math.min(x1 - bw2, x - bw2 / 2)), by = Math.max(yTop - 4, y - 34);
        ctx.fillStyle = v >= 0 ? '#1f9d6b' : '#d64545'; ctx.beginPath(); ctx.roundRect(bx, by, bw2, 22, 11); ctx.fill();
        ctx.fillStyle = '#fff'; ctx.textAlign = 'center'; ctx.fillText(txt, bx + bw2 / 2, by + 11.5);
      }
    }
    function animar() {
      cancelAnimationFrame(raf);
      if (matchMedia('(prefers-reduced-motion: reduce)').matches) { prog = 1; desenhar(); return; }
      const t0 = performance.now();
      const passo = t => { const k = Math.min(1, (t - t0) / 480); prog = 1 - Math.pow(1 - k, 3); desenhar(); if (k < 1) raf = requestAnimationFrame(passo); };
      raf = requestAnimationFrame(passo);
    }
    function legenda() {
      const s = series[escala], v = (s.c[s.c.length - 1] / base(s) - 1) * 100;
      $('gvar').innerHTML = `Variação ${s.variacao}: <b style="color:${cor(v)}">${sinal(v, s.casas ?? 2)}</b>${s.soPreco ? ' só preço' : ''}`;
    }
    function trocar(k) {
      escala = k; toque = null;
      el.querySelectorAll('.e').forEach(b => b.setAttribute('aria-pressed', b.dataset.e === k));
      trocarFaixa(k); legenda(); animar();
    }
    el.querySelectorAll('.e').forEach(b => { b.onclick = () => trocar(b.dataset.e); });
    $('gvela').onclick = e => { velas = !velas; e.currentTarget.setAttribute('aria-pressed', velas); animar(); };
    $('gexp').onclick = () => { $('gbox').classList.toggle('grande'); desenhar(); };
    const mover = e => { const r = cv.getBoundingClientRect(); toque = e.clientX - r.left; toqueY = e.clientY - r.top; desenhar(); };
    cv.onpointerdown = mover;
    cv.onpointermove = e => { if (e.pointerType === 'mouse' || e.buttons || toque !== null) mover(e); };
    cv.onpointerleave = () => { toque = null; desenhar(); };
    cv.onpointerup = e => { if (e.pointerType !== 'mouse') { toque = null; desenhar(); } };
    const ro = new ResizeObserver(desenhar); ro.observe(cv);
    limpar.push(() => { ro.disconnect(); cancelAnimationFrame(raf); });
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(desenhar);
    legenda(); desenhar();
    aoMudarModo = () => {
      const b10 = el.querySelector('[data-e="10d"]');
      if (b10) b10.hidden = modo !== 'simons' || !series['10d'];
      if (modo === 'simons' && series['10d']) trocar('10d');
      else if (escala === '10d') trocar('1a');
      else desenhar();
    };
  })($('grafico'));

  /* ---------------- faixa de preço */
  function trocarFaixa(escala) {
    const antes = faixaK;
    aplicarFaixa(escala);
    if (faixaK !== antes) { renderFaixa(); renderDecisao(); }
  }
  function renderFaixa() {
    const el = $('faixa');
    const C = d.conservadorFaixa;
    // Com valuation disponível, os cortes (oportunidade/neutra/cara) vêm do Preço Teto, não do
    // período do gráfico; a barra (mínima/máxima e "você está aqui") continua mostrando só onde
    // o preço está dentro do período escolhido (1A/5A/Máx) — ela não define mais os cortes.
    // Ponto de entrada (zona verde) é FIXO na margem de 30% sobre a âncora de 1 ano; os limites de
    // 3 e 5 anos (40%/50%) são só referências visuais marcadas na própria barra, como a MM200.
    const zO = C ? C.oportunidadeAte : zOport, zC = C ? C.caroAcima : zCara;
    // a escala da barra estica além da faixa natural do período (mínima/máxima) pra caber todos os
    // cortes e referências (oportunidade/cara, limite de 3/5 anos, mm200) - sem isso, um limite bem
    // abaixo da mínima do período (ex. limite de 5 anos) nunca apareceria marcado na régua. A
    // posição de cada um na tela (cor, traço e número) depois passa pelo afastar() (gap mínimo
    // escalado pela largura real do rótulo de cada um - ver abaixo), senão, com vários pontos
    // próximos no preço real (zona de oportunidade estreita), a cor mudaria num lugar e o número
    // escrito em cima diria outro.
    const pontosDisponiveis = C ? [zO, zC, tem(C.limite3a) ? C.limite3a : null, tem(C.limite5a) ? C.limite5a : null,
      tem(C.mm200) ? C.mm200 : null].filter(tem) : [];
    // a mínima/máxima da régua são sempre um dado real (nunca uma margem inventada): a mínima do
    // período, ou o ponto real mais baixo (ex. limite de 5 anos) quando ele é menor que a mínima do
    // período. Se o preço cair abaixo dessa mínima (ou subir acima da máxima), a bolinha fica
    // encostada na borda (posicao() trava em 0%/100%) - não desaparece, só para de se mover.
    const minEfetivo = C ? Math.min(fx.min, ...pontosDisponiveis) : fx.min;
    const maxEfetivo = C ? Math.max(fx.max, ...pontosDisponiveis) : fx.max;
    const larg = maxEfetivo - minEfetivo;
    const posBruta = v => larg > 0 ? Math.max(0, Math.min(100, (v - minEfetivo) / larg * 100)) : 50;
    const pBruta = posicao(d.preco, minEfetivo, maxEfetivo);
    const aBruta = posBruta(zO), bBruta = posBruta(zC);
    const temMM = C && tem(C.mm200), aMMBruta = temMM ? posBruta(C.mm200) : null;
    const tem3a = C && tem(C.limite3a), a3aBruta = tem3a ? posBruta(C.limite3a) : null;
    const tem5a = C && tem(C.limite5a), a5aBruta = tem5a ? posBruta(C.limite5a) : null;
    const pontosAjuste = [
      tem5a ? { k: 'a5a', pos: a5aBruta } : null,
      tem3a ? { k: 'a3a', pos: a3aBruta } : null,
      { k: 'a', pos: aBruta },
      temMM ? { k: 'mm', pos: aMMBruta } : null,
      { k: 'b', pos: bBruta },
    ].filter(Boolean).sort((x, y) => x.pos - y.pos);
    // a mínima/máxima da régua só aparecem na borda quando são um valor DIFERENTE do já marcado por
    // um traço (senão repetiria o mesmo número duas vezes à toa) - nunca escondem o traço/corte em
    // si, só evitam o texto redundante
    const valorReal = { a5a: C && C.limite5a, a3a: C && C.limite3a, a: zO, mm: C && C.mm200, b: zC };
    const repeteEsq = pontosAjuste.length > 0 && Math.abs(valorReal[pontosAjuste[0].k] - minEfetivo) < 1e-6;
    const repeteDir = pontosAjuste.length > 0 && Math.abs(valorReal[pontosAjuste[pontosAjuste.length - 1].k] - maxEfetivo) < 1e-6;
    const textoEsq = repeteEsq ? '' : f(minEfetivo), textoDir = repeteDir ? '' : f(maxEfetivo);
    // ativos com preço na casa dos milhares (ex. US$ 1.999,96) têm rótulos bem mais largos do que
    // ativos de preço baixo (ex. 14,65) - um gap fixo de 17 pontos (bom pra rótulos curtos) não é
    // suficiente pra eles e os números ficam colados/sobrepostos (ex.: zona Cara e a borda direita
    // da régua). O gap mínimo agora escala com a largura real de cada rótulo (estimada pelo nº de
    // caracteres, já que são sempre números formatados no mesmo padrão), convertida em % da largura
    // do card - assim funciona pra qualquer ativo, não só pros de poucos dígitos.
    const largadorPx = txt => txt ? txt.length * 7.3 + 6 : 0;
    // -42 = padding do .card (14px x2) + borda (1px x2) + margem da própria linha (.marca-cima/.regua
    // têm margin: 0/.. 6px nas laterais) - sem contar a borda/margem da linha, a folga calculada ficava
    // ~14px maior do que a largura real disponível, deixando rótulos nas pontas colados/sobrepostos
    // quando a régua estica bastante pra um lado só (ex. NVDA com a régua indo até -50%)
    const largContainer = Math.max(el.clientWidth - 42, 200);
    const pxParaPct = px => px / largContainer * 100;
    const folgas = pontosAjuste.map(x => pxParaPct(largadorPx(f(valorReal[x.k]))) / 2);   // metade: rótulo é centralizado
    const folgaEsq = pxParaPct(largadorPx(textoEsq)), folgaDir = pxParaPct(largadorPx(textoDir));
    const ajustadas = afastar(pontosAjuste.map(x => x.pos), folgas, folgaEsq, folgaDir);
    const mapa = {};
    pontosAjuste.forEach((x, i) => { mapa[x.k] = ajustadas[i]; });
    const a = mapa.a, b = mapa.b;
    const aMM = temMM ? mapa.mm : null;
    const a3a = tem3a ? mapa.a3a : null;
    const a5a = tem5a ? mapa.a5a : null;
    // a bolinha do preço passa pela MESMA transformação dos traços (interpolação entre os pares
    // posição-crua/posição-afastada, com 0%/100% como âncoras quando não coincidem com nenhum
    // ponto já afastado) - senão, com os traços espalhados pra não colar, a bolinha ficaria "presa"
    // perto do traço errado (ex. preço de 14,30 bem perto de 14,65 aparecendo colado no 11,28)
    const pares = pontosAjuste.map((x, i) => [x.pos, ajustadas[i]]);
    if (!pares.length || pares[0][0] > 1e-6) pares.unshift([0, 0]);
    if (pares[pares.length - 1][0] < 100 - 1e-6) pares.push([100, 100]);
    const remapear = v => {
      if (v <= pares[0][0]) return pares[0][1];
      for (let i = 1; i < pares.length; i++) {
        if (v <= pares[i][0]) {
          const [r0, a0] = pares[i - 1], [r1, a1] = pares[i];
          return r1 === r0 ? a0 : a0 + (a1 - a0) * (v - r0) / (r1 - r0);
        }
      }
      return pares[pares.length - 1][1];
    };
    const p = remapear(pBruta);
    // zona de oportunidade em 3 tons de verde: mais clara perto do ponto de entrada (15,21 no ex.
    // real da BBAS3) e mais forte quanto mais funda (perto do limite de 5 anos) - só visual, não
    // muda a classificação, que continua sempre pela margem de 30% sobre a âncora de 1 ano
    const cortesVerde = [a5a, a3a].filter(v => v !== null && v > 0 && v < a).sort((x, y) => x - y);
    const bordasVerde = [0, ...cortesVerde, a];
    const coresVerde = bordasVerde.length - 1 === 3 ? ['var(--verde-forte)', 'var(--verde)', 'var(--verde-claro)']
      : bordasVerde.length - 1 === 2 ? ['var(--verde)', 'var(--verde-claro)'] : ['var(--verde)'];
    const faixaVerde = bordasVerde.slice(0, -1).map((ini, i) => `${coresVerde[i]} ${ini}% ${bordasVerde[i + 1]}%`).join(',');
    const fundo = `linear-gradient(90deg,${faixaVerde},var(--ardosia) ${a}% ${b}%,var(--ambar) ${b}% 100%)`;
    const titulo = C ? 'Valuation (preço médio de 1 ano)' : fx.rotulo;
    el.innerHTML = `<h2>Faixa de preço <small>${titulo}</small></h2>
      <div class="pilha">
        <div class="zona" style="--c:var(--verde)"><span class="rot">Faixa inferior</span><b class="num">até ${din(zO)}</b>${seloFundamentosHtml()}</div>
        <div class="zona" style="--c:var(--ardosia)"><span class="rot">Zona neutra</span><b class="num">${f(zO)} a ${f(zC)}</b></div>
        <div class="zona" style="--c:var(--ambar)"><span class="rot">Faixa superior</span><b class="num">acima de ${din(zC)}</b></div>
        <div class="card">
          ${(() => {
            // o nome da zona some quando a própria coluna é estreita demais pra caber o texto sem
            // quebrar palavra no meio (ex.: "Oportunidade" virando "Oportunida"/"de" em 2 linhas,
            // num ativo com zona de oportunidade estreita, como CBRS) - um limiar fixo (11%) servia
            // pra "Cara"/"Neutra" (curtos) mas não pra "Oportunidade", bem mais longo: o limiar
            // agora usa a largura real estimada de cada rótulo (mesma técnica de largadorPx/
            // pxParaPct já usada acima pros números da régua), não um número igual pra todos
            const precisaRot = texto => pxParaPct(largadorPx(texto));
            const rot = (col, texto) => col < precisaRot(texto) ? '' : texto;
            return `<div class="zonas-rot" style="grid-template-columns:${a}fr ${b - a}fr ${100 - b}fr">
            <span style="color:var(--verde)"><b>${rot(a, 'Inferior')}</b></span>
            <span style="color:#aab4c6"><b>${rot(b - a, 'Neutra')}</b></span>
            <span style="color:var(--ambar)"><b>${rot(100 - b, 'Superior')}</b></span>
          </div>`;
          })()}
          <div class="marca-cima limites num">
            <span class="esq">${textoEsq}</span>
            ${(() => {
              // mesma posição (já afastada) usada na régua embaixo - número e corte sempre batem
              const html = { a5a: a5a !== null ? f(C.limite5a) : '', a3a: a3a !== null ? f(C.limite3a) : '',
                a: f(zO), mm: aMM !== null ? f(C.mm200) : '', b: f(zC) };
              const cor = { mm: '#f2994a' };
              return pontosAjuste.map(x => `<span style="left:${mapa[x.k]}%${cor[x.k] ? `;color:${cor[x.k]}` : ''}">${html[x.k]}</span>`).join('');
            })()}
            <span class="dir">${textoDir}</span>
          </div>
          <div class="regua" style="background:${fundo};margin-top:4px">
            ${aMM !== null ? `<span class="traco" style="left:${aMM}%;background:#f2994a"></span>` : ''}
            ${a3a !== null ? `<span class="traco" style="left:${a3a}%"></span>` : ''}
            ${a5a !== null ? `<span class="traco" style="left:${a5a}%"></span>` : ''}
            <span class="traco" style="left:${a}%"></span><span class="traco" style="left:${b}%"></span>
            <span class="bola" style="left:${p}%"></span>
          </div>
          <div class="marca-baixo num"><span class="aqui-rot" style="${ancora(p)}"><b>${f(d.preco)}</b>Você está aqui</span></div>
        </div>
      </div>`;
  }
  renderFaixa();

  /* ---------------- tendência e força */
  (function TrendStrength(el) {
    const dist = tem(d.mm200) ? (d.preco / d.mm200 - 1) * 100 : null;
    // Força da tendência: distância do preço até a média de 200 dias. Escala fixa de -30% a +30%
    // (só estica além disso se a distância real passar desses limites): abaixo de -10% perdeu força;
    // de -10% a +10% é equilíbrio (a própria média, 0%, fica no meio dessa faixa); +10% a +20% é leve
    // compra; acima de +20% é compra forte.
    const NEG = -10, EQ = 10, LEVE = 20;
    // Título/badge "Direção da tendência" e evolução abaixo: regra travada, à parte dos limiares de cor da
    // régua (-10/+10/+20) - dist < -5% = Baixa; entre -5% e +5% = Equilíbrio; dist > +5% = Alta. PROIBIDO
    // usar "Perdeu força"/"Alta leve"/"Forte" como Direção (esses nomes são só das zonas da régua abaixo).
    const direcaoDist = v => v < -5 ? 'Baixa' : v > 5 ? 'Alta' : 'Equilíbrio';
    const tituloT = tem(dist) ? direcaoDist(dist) : '—';
    const corT = { Alta: 'var(--verde)', Baixa: 'var(--vermelho)', Equilíbrio: 'var(--suave)' }[tituloT] || 'var(--texto)';
    // texto da Força (IFR) no mesmo padrão "de X para Y" da evolução da Direção da tendência acima, pra
    // mostrar a evolução em vez de só o estado de hoje - zona calculada com as MESMAS 5 faixas/limiares da
    // régua abaixo (Muita venda/Venda/Neutro/Compra/Muita compra, padrão de mercado: <30/30-40/40-60/60-70/
    // >70), nunca com limiares diferentes dos mostrados na própria barra (senão o texto pode contradizer a
    // cor/posição da bolinha). Sem o histórico de 7 dias, mantém uma frase descritiva da zona de hoje (nunca
    // inventa uma comparação)
    const zonaIFR = v => v < 30 ? 'Muita venda' : v < 40 ? 'Venda' : v < 60 ? 'Neutro' : v <= 70 ? 'Compra' : 'Muita compra';
    let leitura = '';
    if (tem(d.forca)) {
      const zonaHoje = zonaIFR(d.forca);
      if (tem(d.forca7d)) {
        const zona7 = zonaIFR(d.forca7d);
        const verbo = d.forca > d.forca7d ? 'subiu' : d.forca < d.forca7d ? 'caiu' : null;
        if (zonaHoje !== zona7) {
          leitura = verbo ? `Virou de ${zona7} para ${zonaHoje}: ${verbo} de ${f(d.forca7d, 0)} para ${f(d.forca, 0)}.`
            : `Virou de ${zona7} para ${zonaHoje}: manteve em ${f(d.forca, 0)}.`;
        } else {
          leitura = verbo ? `${zonaHoje}. ${verbo.charAt(0).toUpperCase() + verbo.slice(1)} de ${f(d.forca7d, 0)} para ${f(d.forca, 0)}.` : `${zonaHoje}. Manteve em ${f(d.forca, 0)}.`;
        }
      } else {
        leitura = zonaHoje === 'Muita compra' ? 'Muita compra. Subiu rápido demais.'
          : zonaHoje === 'Compra' ? 'Compra. Pressão de compra.'
          : zonaHoje === 'Muita venda' ? 'Muita venda. Caiu rápido demais.'
          : zonaHoje === 'Venda' ? 'Venda. Pressão de venda.' : 'Neutro. Sem pressão de compra nem de venda.';
      }
    }
    const fundo = 'linear-gradient(90deg,var(--vermelho) 0 30%,var(--ambar) 30% 40%,var(--ardosia) 40% 60%,var(--verde-claro) 60% 70%,var(--verde-forte) 70% 100%)';
    const RMIN = tem(dist) && dist < -30 ? Math.floor((dist - 5) / 10) * 10 : -30;
    const RMAX = tem(dist) && dist > 30 ? Math.ceil((dist + 5) / 10) * 10 : 30;
    const pt = v => (v - RMIN) / (RMAX - RMIN) * 100;
    const fundoT = `linear-gradient(90deg,var(--vermelho) 0 ${pt(NEG)}%,var(--ardosia) ${pt(NEG)}% ${pt(EQ)}%,var(--verde-claro) ${pt(EQ)}% ${pt(LEVE)}%,var(--verde-forte) ${pt(LEVE)}% 100%)`;
    // evolução da direção nos últimos 7 pregões, com a MESMA direcaoDist() do título acima
    let evolucaoT = '';
    if (tem(dist) && tem(d.dist200d7d)) {
      const dirHoje = direcaoDist(dist), dir7 = direcaoDist(d.dist200d7d);
      const absHoje = Math.abs(dist), abs7 = Math.abs(d.dist200d7d);
      // nunca usa "p.p." (pouca gente conhece a sigla): sempre escreve "de X% para Y%", com a palavra
      // abaixo/acima da média pelo sinal real de hoje (a zona "Equilíbrio" pode ter valor levemente negativo
      // ou positivo, então a palavra não pode depender só do nome da zona)
      const qualif = dist > 0 ? ' acima da média' : dist < 0 ? ' abaixo da média' : '';
      const linha2 = dirHoje !== dir7 ? `Virou de ${dir7.toLowerCase()} para ${dirHoje.toLowerCase()}: de ${sinal(d.dist200d7d)} para ${sinal(dist)}.`
        : absHoje > abs7 ? `Continuou em ${dirHoje.toLowerCase()} e piorou: de ${f(abs7)}% para ${f(absHoje)}%${qualif}.`
        : absHoje < abs7 ? `Continuou em ${dirHoje.toLowerCase()} e melhorou: de ${f(abs7)}% para ${f(absHoje)}%${qualif}.`
        : `Continuou em ${dirHoje.toLowerCase()}, sem variação.`;
      evolucaoT = `<div class="nota" style="margin-top:4px">7 dias atrás: ${dir7} (${sinal(d.dist200d7d)}) → Hoje: ${dirHoje} (${sinal(dist)})</div>
          <div class="nota" style="margin-top:2px">${linha2}</div>`;
    }
    let textoT = '', notaSubirCairT = '';
    if (tem(dist)) {
      const cair = (d.preco - d.mm200) / d.preco * 100, subir = (d.mm200 / d.preco - 1) * 100;
      textoT = dist < 0 ? `${f(Math.abs(dist), 1)}% abaixo da média de 200 dias.`
        : `${f(dist, 1)}% acima da média de 200 dias.`;
      notaSubirCairT = dist < 0 ? `${f(subir, 1)}% para voltar à média.`
        : `${f(cair, 1)}% para perder a tendência.`;
    }
    // mesmo desenho da barra de zonas: nomes em cima de cada cor, limites com traço e valor,
    // distância e média de 200 dias embaixo da barra, cada uma sempre alinhada com o próprio ponto
    // (bolinha/traço do 0%) - em linhas separadas, pra nunca precisar empurrar uma pro lado quando
    // ficam perto uma da outra (ex. preço bem perto da própria média de 200 dias)
    const pDist = Math.max(0, Math.min(100, pt(dist)));
    // marcador (bolinha vazada) de onde a Força da tendência estava há 7 pregões, pra dar pra ver
    // pra que lado ela está indo (sem precisar comparar números) - None quando não tem histórico
    const p7T = tem(d.dist200d7d) ? Math.max(0, Math.min(100, pt(d.dist200d7d))) : null;
    const pct = v => `${v > 0 ? '+' : ''}${f(v, 0)}%`;
    // marcador de hoje (bolinha cheia) em cima da régua, valor em azul; marcador de 7 dias atrás (bolinha
    // vazada) embaixo, cada um na posição do seu próprio ponto (nunca empilhados) - rótulo "7 dias atrás"
    // em cima e valor embaixo, pra não parecer o valor de hoje - os dois marcadores de 7 dias (aqui e na
    // Força) usam o mesmo visual
    const txtHojeT = sinal(dist), txt7ValorT = sinal(d.dist200d7d);
    const largContainerT = Math.max(el.clientWidth - 42, 200);   // -42: ver renderFaixa acima
    const [pDistBola, p7TBola] = afastarBolinhas(largContainerT, pDist, p7T);
    const linhaHojeT = `<div class="marca-cima so-valor num"><span style="${ancora(pDistBola)};color:var(--azul);font-weight:600;font-size:12px">${txtHojeT}</span></div>`;
    const linha7T = p7T === null ? '' : `<div class="marca-baixo num" style="margin-top:10px"><span style="${ancora(p7TBola)};color:var(--suave);font-weight:500;font-size:10.5px">7 dias atrás<b style="color:var(--texto)">${txt7ValorT}</b></span></div>`;
    // quando a distância real passa de -30%/+30%, a régua estica só pro lado que precisa (ex. -50% a
    // +30%) - os rótulos do meio (-10%/0%/+10%/+20%) não ficam mais espaçados igual nos dois lados
    // nesse caso, podendo colar no rótulo da ponta que NÃO esticou (ex. +20% colado no +30%). Mesma
    // técnica de afastar() da Faixa de preço: cada rótulo ganha a folga da sua própria largura (texto
    // real, não um gap fixo) e só se afasta da ponta o mínimo necessário - os TRAÇOS da régua (cores,
    // bolinha) continuam na posição exata, só os NÚMEROS escritos acima se ajustam.
    const largPxT = txt => txt.length * 7.3 + 6 + 6;   // +6 extra: respiro visível, não só sem sobrepor
    const pxParaPctLimT = px => px / largContainerT * 100;
    const textoEsqT = pct(RMIN), textoDirT = pct(RMAX);
    const pontosLimT = [{ k: 'neg', pos: pt(NEG), txt: '-10%' }, { k: 'zero', pos: pt(0), txt: '0%' },
      { k: 'eq', pos: pt(EQ), txt: '+10%' }, { k: 'leve', pos: pt(LEVE), txt: '+20%' }];
    const ajustadasLimT = afastar(pontosLimT.map(x => x.pos), pontosLimT.map(x => pxParaPctLimT(largPxT(x.txt)) / 2),
      pxParaPctLimT(largPxT(textoEsqT)), pxParaPctLimT(largPxT(textoDirT)));
    const mapaLimT = {}; pontosLimT.forEach((x, i) => { mapaLimT[x.k] = ajustadasLimT[i]; });
    const divisor = 'margin-top:14px;padding-top:14px;border-top:1px solid var(--borda)';
    const barraT = !tem(dist) ? '' : `<div style="${divisor}">
          <span class="rot">Força da tendência</span>
          <div style="position:relative;height:16px;margin-top:10px;font-size:11px;font-weight:700;white-space:nowrap">
            <span style="position:absolute;left:0;color:var(--vermelho)">Baixa</span>
            <span style="position:absolute;left:${(pt(NEG) + pt(EQ)) / 2}%;transform:translateX(-50%);color:#aab4c6">Equilíbrio</span>
            <span style="position:absolute;left:${(pt(EQ) + pt(LEVE)) / 2}%;transform:translateX(-50%);color:var(--verde-claro)">Alta leve</span>
            <span style="position:absolute;right:0;color:var(--verde-forte)">Forte</span>
          </div>
          <div class="marca-cima limites num">
            <span class="esq">${textoEsqT}</span><span style="left:${mapaLimT.neg}%">-10%</span><span style="left:${mapaLimT.zero}%">0%</span>
            <span style="left:${mapaLimT.eq}%">+10%</span><span style="left:${mapaLimT.leve}%">+20%</span><span class="dir">${textoDirT}</span>
          </div>
          ${linhaHojeT}
          <div class="regua" style="background:${fundoT};margin-top:4px">
            <span class="traco" style="left:${pt(NEG)}%"></span><span class="traco" style="left:${pt(0)}%"></span>
            <span class="traco" style="left:${pt(EQ)}%"></span><span class="traco" style="left:${pt(LEVE)}%"></span>
            ${p7T !== null ? `<span class="bola-7d" style="left:${p7TBola}%"></span>` : ''}
            <span class="bola" style="left:${pDistBola}%"></span>
          </div>
          ${linha7T}
          <div class="nota num" style="margin-top:18px">Média de 200 dias: ${din(d.mm200)} - é o ponto 0% da régua acima (referência de onde o preço está perto ou longe).</div>
          <div class="destaque num">${textoT}</div>
          <div class="nota num">${notaSubirCairT}</div>
        </div>`;
    const largContainerF = Math.max(el.clientWidth - 42, 200);   // -42: ver renderFaixa acima
    const [forcaBola, forca7dBola] = tem(d.forca) ? afastarBolinhas(largContainerF, d.forca, tem(d.forca7d) ? d.forca7d : null) : [null, null];
    el.innerHTML = `<h2>Tendência e força</h2>
      <div class="card">
        <div class="duas"><div class="esq"><span class="rot">Direção da tendência</span></div><div class="dir" style="color:${corT}">${tituloT}</div></div>
        ${evolucaoT}
        ${barraT}
        <div style="${divisor}">
          <strong>Força - RSI</strong><div class="nota">Últimos 14 dias</div>
          ${tem(d.forca) ? `<div style="position:relative;height:16px;margin-top:8px;font-size:11px;font-weight:700;white-space:nowrap">
            <span style="position:absolute;left:0;color:var(--vermelho)">Muita venda</span>
            <span style="position:absolute;left:35%;transform:translateX(-50%);color:var(--ambar)">Venda</span>
            <span style="position:absolute;left:50%;transform:translateX(-50%);color:#aab4c6">Neutro</span>
            <span style="position:absolute;left:65%;transform:translateX(-50%);color:var(--verde-claro)">Compra</span>
            <span style="position:absolute;right:0;color:var(--verde-forte)">Muita compra</span>
          </div>
          <div class="marca-cima limites num">
            <span class="esq">0</span><span style="left:30%">30</span><span style="left:40%">40</span><span style="left:60%">60</span><span style="left:70%">70</span><span class="dir">100</span>
          </div>
          <div class="marca-cima so-valor num"><span style="${ancora(forcaBola)};color:var(--azul);font-weight:600;font-size:12px">${f(d.forca, 0)}</span></div>
          <div class="regua" style="background:${fundo};margin-top:4px">
            <span class="traco" style="left:30%"></span><span class="traco" style="left:40%"></span><span class="traco" style="left:50%"></span><span class="traco" style="left:60%"></span><span class="traco" style="left:70%"></span>
            ${tem(d.forca7d) ? `<span class="bola-7d" style="left:${forca7dBola}%"></span>` : ''}
            <span class="bola" style="left:${forcaBola}%"></span>
          </div>
          ${tem(d.forca7d) ? `<div class="marca-baixo num" style="margin-top:10px"><span style="${ancora(forca7dBola)};color:var(--suave);font-weight:500;font-size:10.5px">7 dias atrás<b style="color:var(--texto)">${f(d.forca7d, 0)}</b></span></div>` : ''}
          <div class="nota num" style="margin-top:18px">50 é o ponto neutro da régua acima (nem sobrecomprada, nem sobrevendida).</div>
          <div class="destaque">${leitura}</div>` : `<div class="nota" style="margin-top:8px">${INDISP}</div>`}
        </div>
      </div>`;
  })($('tendencia'));

  /* ---------------- mínimo, máximo e ponto médio */
  (function MinMaxMidpoint(el) {
    // contas com os valores arredondados que a tela mostra, para o usuário conseguir refazer:
    // (14,72 + 24,97) ÷ 2 = 19,85 e 19,85 − 15,10 = 4,75
    const r2 = v => Math.round(v * 100 + (v >= 0 ? 1e-7 : -1e-7)) / 100;
    const bloco = (id, titulo, minBruto, maxBruto, periodo) => {
      if (!tem(minBruto) || !tem(maxBruto)) return `<div class="card"><strong>${titulo}</strong><div class="nota" style="margin-top:6px">${INDISP}</div></div>`;
      const min = r2(minBruto), max = r2(maxBruto), agora = r2(d.preco);
      const meio = r2((min + max) / 2), dif = r2(agora - meio), p = posicao(agora, min, max);
      const difPct = meio ? dif / meio * 100 : 0;                 // distância, em % do ponto médio
      const volta = agora ? (meio / agora - 1) * 100 : 0;         // quanto o preço precisa andar até o ponto médio
      const frase = dif === 0 ? 'O preço está no ponto médio.'
        : `Precisa ${dif < 0 ? 'subir' : 'cair'} ${f(Math.abs(volta), 1)}% para voltar ao ponto médio de ${f(meio)}.`;
      FOLHAS[id] = () => [`Ponto médio · ${titulo.toLowerCase()}`, `
        <p>O ponto médio é a metade do caminho entre a mínima e a máxima reais do período.</p>
        <code>(${f(min)} + ${f(max)}) ÷ 2 = ${f(meio)}</code>
        <p>Distância do preço até o ponto médio:</p>
        <code>${f(agora)} − ${f(meio)} = ${dif < 0 ? '-' : ''}${f(Math.abs(dif))} (${sinal(difPct, 1)} do ponto médio)</code>
        ${dif === 0 ? '' : `<p>Quanto o preço precisa ${dif < 0 ? 'subir' : 'cair'} para chegar ao ponto médio:</p>
        <code>${f(meio)} ÷ ${f(agora)} − 1 = ${sinal(volta, 1)}</code>
        <p>Os dois percentuais são diferentes porque partem de bases diferentes: o primeiro é medido sobre o ponto médio, o segundo sobre o preço atual.</p>`}${fonte}`];
      return `<div class="card">
        <div class="cab"><strong>${titulo}</strong><button class="link" data-folha="${id}">Ver como calculamos</button></div>
        <div class="marca-cima num"><span class="esq">Mín.<b>${f(min)}</b></span><span style="left:50%">Ponto médio<b>${f(meio)}</b></span><span class="dir">Máx.<b>${f(max)}</b></span></div>
        <div class="regua" style="background:var(--ardosia);margin-top:6px"><span class="traco" style="left:50%"></span><span class="bola" style="left:${p}%"></span></div>
        <div class="marca-baixo num"><span style="${ancora(p)}">Agora<b>${f(agora)}</b></span></div>
        <div class="destaque num">${dif === 0 ? 'Você está no ponto médio' : `Você está ${din(Math.abs(dif))} (${f(Math.abs(difPct), 1)}%) ${dif > 0 ? 'acima' : 'abaixo'} do ponto médio`}</div>
        ${dif === 0 ? '' : `<div class="nota num">${frase}</div>`}
      </div>`;
    };
    el.innerHTML = `<h2>Mínimo, máximo e ponto médio</h2><div class="sub">Valores em ${d.moeda}</div>
      <div class="pilha">${bloco('mm12', 'Últimos 12 meses', d.min52, d.max52, '12 meses')}${bloco('mm30', 'Últimos 30 dias', d.min30, d.max30, '30 dias')}</div>`;
  })($('minmax'));

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

  /* ---------------- "Dados fixos" REMOVIDO como bloco visual próprio (unificação pedida em
     27/11/2026): divergia do bloco "Lucro e Preço vs Lucro"/"Indicadores" pro mesmo indicador
     (bug já corrigido - ver CLAUDE.md), e os 2 blocos mostrando números parecidos confundia.
     utils/dados_fixos.py (`buscar_fixos_br`) continua existindo como camada de dados interna -
     `d.dadosFixos` (tela/dados.dados_fixos_tela) ainda é calculado em tela/dados.montar(), só não
     vira mais a própria seção da tela: os campos que só existiam aqui (Ações em circulação, Lucro
     líquido do período, fonte CVM, data de encerramento) migraram pro card "Indicadores" abaixo -
     ver a seção Indicators. P/VP/Payout/ROE/ADR (Issue #35) eram exclusivos deste bloco e não
     tinham equivalente em Indicadores - ficam só no `d.dadosFixos` (não descartados do cálculo,
     só sem card próprio por enquanto; retomar se for pedido). */

  /* ---------------- preço justo: SEÇÃO REMOVIDA (issue #47, item 15). "Preço justo" era um
     preço-alvo (Bazin/Conservador/P/L histórico) e virava responsabilidade do app, como o
     backtest do item 13. O Fintai mostra só posição de preço (item 10) + fundamentos (item 11).
     O espaço fica vazio de propósito - sem substituir por outra versão. */

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

  /* ---------------- retorno acumulado (issue #47, item 16): nunca mistura moeda - d.comparadores
     já vem filtrado (BR só R$: Ibovespa/IPCA/Poupança; EUA só US$: S&P 500/Nasdaq - ver
     app.comparadores). CDI/Selic (BR) saem para o card "Renda fixa", separado, com a etiqueta
     [Outro tipo de investimento]. Sem simulação de R$/US$ 10.000: só % e diferença em pontos. */
  (function TotalReturn(el) {
    const idx = d.retorno.periodos.map((_, i) => i).filter(i => tem(d.retorno.total[i]));
    if (!idx.length) { el.innerHTML = `<h2>Retorno acumulado</h2><div class="card nota">Histórico curto demais para calcular retornos.</div>`; return; }
    const comDado = k => d.comparadores[k] && d.comparadores[k].v.some(tem);
    // abre no comparador da bolsa da ação; se ele não tiver dado, no primeiro que tiver
    let reinveste = true, dicaAberta = false, per = idx[0],
      comp = comDado(d.comparadorPadrao) ? d.comparadorPadrao : (Object.keys(d.comparadores).find(comDado) || Object.keys(d.comparadores)[0]);
    function render() {
      const c = d.comparadores[comp];
      const vals = reinveste ? d.retorno.total : d.retorno.preco;
      const pSel = d.retorno.periodos[per];
      const difP = tem(d.retorno.preco[per]) && tem(d.retorno.total[per]) ? d.retorno.total[per] - d.retorno.preco[per] : null;
      const recebido = per === 0 ? d.dividendo : per === 2 ? d.dividendos5Anos : null;
      let texto;
      if (reinveste) texto = !tem(difP) ? 'Retorno com os dividendos reinvestidos em mais ações.'
        : difP < 1 ? `Quase nenhuma diferença em ${pSel}. Reinvestir ou não muda ${f(Math.max(difP, 0), 1)} ponto no seu retorno.`
        : `${difP >= 10 ? 'Grande diferença' : 'Faz diferença'}. Em ${pSel}, reinvestir os dividendos faz seu retorno ir de ${ret(d.retorno.preco[per])} para ${ret(d.retorno.total[per])}, porque você compra mais ações com o dividendo.`;
      else texto = (tem(recebido) && recebido > 0 ? `Você recebeu ${din(recebido)} por ação em dividendos em ${pSel}, em dinheiro, e não recomprou.` : `Você recebeu os dividendos de ${pSel} em dinheiro e não recomprou.`)
        + (tem(difP) && difP >= 10 ? ` Deixou de ganhar ${f(difP, 1)} pontos do efeito bola de neve.` : '');

      // a ação primeiro; depois os comparadores (mesma moeda) do menor para o maior retorno
      const linhasG = [{ nome: d.ticker, v: vals[per], acao: true },
        ...Object.values(d.comparadores).map(o => ({ nome: o.nome, v: o.v[per] }))
          .sort((x, y) => (tem(x.v) ? x.v : Infinity) - (tem(y.v) ? y.v : Infinity))];
      const comV = linhasG.map(l => l.v).filter(tem);
      let vhi = Math.max(0, ...comV), vlo = Math.min(0, ...comV);
      const vpasso = passoBonito(Math.max(vhi - vlo, 1) / 4);
      vhi = Math.max(vpasso, Math.ceil(vhi / vpasso) * vpasso); vlo = Math.floor(vlo / vpasso) * vpasso;
      const vamp = vhi - vlo, vpos = v => (v - vlo) / vamp * 100;
      const vmarcas = []; for (let v = vlo; v <= vhi + 1e-9; v += vpasso) vmarcas.push(v);
      const grafico = `<div class="grade-y">${vmarcas.map(v => `<div style="bottom:${vpos(v)}%"><span>${f(v, 0)}%</span></div>`).join('')}<div class="zero" style="bottom:${vpos(0)}%"></div></div>
        <div class="vcols">${linhasG.map(l => `<div class="vc${l.acao ? ' acao' : ''}">${tem(l.v)
          ? `<div class="vb${l.v < 0 ? ' neg' : ''}" style="bottom:${vpos(Math.min(0, l.v))}%;height:${Math.max(Math.abs(l.v) / vamp * 100, 0.8)}%"><i class="num">${ret(l.v)}</i></div>`
          : `<div class="vb vazio" style="bottom:${vpos(0)}%" title="Sem dado"><i>—</i></div>`}
          <em>${({ 'S&P 500': 'S&P', 'S&P 500 (sem dividendos)': 'S&P s/div', 'Ibovespa': 'Ibov', 'Poupança': 'Poup.' })[l.nome] || l.nome}</em></div>`).join('')}</div>`;

      // resumo do período contra o comparador da bolsa: só % e diferença em pontos (sem simulação de dinheiro)
      const p = d.retorno.periodos[per];
      let resumo;
      if (!tem(vals[per])) resumo = `<div><b>Retorno acumulado: ${INDISP} em ${p}</b></div>`;
      else {
        const cab = `<b>${d.ticker}: ${ret(vals[per])} em ${p}</b>${reinveste ? '' : ' (só preço)'}`;
        if (!tem(c.v[per])) resumo = `<div>${cab}<br>${c.nome}: ${INDISP}</div>`;
        else {
          const dif = vals[per] - c.v[per], casas = Math.abs(dif) >= 100 ? 0 : 1;
          resumo = `<div>${cab}<br>
          ${c.nome}: ${ret(c.v[per])} | Diferença: <span class="dif ${dif < 0 ? 'neg' : ''}">${dif >= 0 ? '+' : '-'}${f(Math.abs(dif), casas)} pontos ${dif >= 0 ? 'acima' : 'abaixo'} ${c.artigo}</span><button class="q" id="qpp" aria-label="O que são pontos percentuais?">?</button>
          ${dicaAberta ? `<span class="dica-q">p.p. = pontos percentuais. É só a conta: ${f(vals[per], 1)}% - ${f(c.v[per], 1)}% = ${f(Math.abs(dif), casas)} pontos. Não é ${f(Math.abs(dif), casas)}%.</span>` : ''}</div>`;
        }
      }

      const t3 = d.retorno.total[1], t5 = d.retorno.total[2];
      const porque = per === 2 && tem(t3) && tem(t5) && t3 > t5
        ? `Por que 3 anos (${ret(t3)}) rendeu mais que 5 anos (${ret(t5)})? Porque entre 5 e 3 anos atrás a ação caiu ${f(Math.abs(((1 + t5 / 100) / (1 + t3 / 100) - 1) * 100), 0)}%. O ganho veio todo nos últimos 3 anos. ` : '';
      // Renda fixa (BR): CDI/Selic, separado do gráfico de índices - é outro tipo de investimento
      const rendaFixaHtml = (() => {
        const tx = Object.values(d.rendaFixa || {}).filter(o => tem(o.taxaAno) || (o.v && o.v.some(tem)));
        if (!tx.length) return '';
        return `<div class="card" style="margin-top:10px"><strong>Renda fixa <small>[Outro tipo de investimento]</small></strong>
          <div class="lista-v num" style="margin-top:8px">${tx.map(o => `<div>${o.nome}${tem(o.taxaAno) ? ` (${f(o.taxaAno)}% a.a. hoje)` : ''}<b>${tem(o.v[per]) ? ret(o.v[per]) : INDISP} em ${d.retorno.periodos[per]}</b></div>`).join('')}</div>
          <p class="nota" style="margin-top:6px">CDI e Selic são renda fixa, não um índice de bolsa - ficam fora do gráfico de retorno acima de propósito.</p></div>`;
      })();
      el.innerHTML = `<h2>Retorno acumulado</h2><div class="sub">com dividendos, comparado aos indicadores (${d.moeda})</div>
        <div class="toggle" role="group" aria-label="Reinvestimento de dividendos">
          <button data-r="1" aria-pressed="${reinveste}">Reinvestindo dividendos</button><button data-r="0" aria-pressed="${!reinveste}">Sem reinvestir</button>
        </div>
        <div class="chips periodos" role="group" aria-label="Período">${idx.map(i => `<button data-p="${i}" aria-pressed="${i === per}">${d.retorno.periodos[i]}</button>`).join('')}</div>
        <p class="nota" style="margin:4px 2px 0">${texto}</p>
        <div class="vbarras">${grafico}</div>
        <div class="card resumo num">${resumo}</div>
        ${rendaFixaHtml}
        <p class="nota" style="margin:12px 2px 0">${porque}<b>Retorno passado não garante retorno futuro.</b></p>
        <p class="nota" style="margin:8px 2px 0">Fonte: Yahoo Finance - Dados até ${d.data}.</p>`;
      el.querySelectorAll('[data-r]').forEach(b => { b.onclick = () => { reinveste = b.dataset.r === '1'; render(); }; });
      el.querySelectorAll('[data-p]').forEach(b => { b.onclick = () => { per = +b.dataset.p; render(); }; });
      const q = $('qpp'); if (q) q.onclick = () => { dicaAberta = !dicaAberta; render(); };
    }
    render();
  })($('retorno'));

  /* ---------------- backtest: SEÇÃO REMOVIDA (issue #47, item 13). "Os sinais funcionaram no
     passado?" validava/invalidava sinais e virava responsabilidade do app (SINAL INVALIDADO,
     simulação de R$10.000 etc.). O Fintai não valida sinal nenhum: mostra só posição de preço
     (item 10) + fundamentos (item 11). Espaço vazio de propósito, sem substituir. */

  /* ---------------- bloco de cada modo */
  function renderBloco() {
    const el = $('modo-bloco');
    // Guidance trimestral (informativo, independente do modo de valuation) fica anexado no fim do
    // bloco de cada modo, logo abaixo de "Lucro por ação"/"Crescimento"/"Movimento curto".
    const OT = d.outlookTrimestral;
    const cambioOT = OT && OT.moedaOriginal === 'EUR' && tem(OT.taxaCambio)
      ? ` Convertido de euro pelo câmbio EUR→USD de ${OT.taxaCambioData} (Yahoo Finance): ${f(OT.taxaCambio, 4)}.` : '';
    const proximoOT = OT && OT.proximoAnuncio ? `<div class="nota" style="margin-top:8px">Próximo anúncio previsto: <b>${OT.proximoAnuncio}</b> (Yahoo Finance)</div>` : '';
    const outlookHtml = OT ? `<div class="card" style="margin-top:12px">
        <span class="rot">Guidance da empresa para o próximo trimestre</span>
        ${bolaAtualizacao(OT.atualizacao)}
        <div class="nota" style="margin-top:4px">${OT.periodo} · informativo: não entra no P/L nem na Previsão atual (que é guidance ANUAL)</div>
        <div class="lista-v num" style="margin-top:8px">
          <div>Receita<b>${tem(OT.receitaMin) && tem(OT.receitaMax) ? `${din(OT.receitaMin / 1e9, 1)} a ${din(OT.receitaMax / 1e9, 1)} bi` : 'Sem dado'}</b></div>
          <div>Margem bruta<b>${tem(OT.margemBruta) ? `${f(OT.margemBruta, 1)}%` : 'Sem dado'}</b></div>
          <div>LPA projetado<b>${tem(OT.lpaMin) && tem(OT.lpaMax) ? `${din(OT.lpaMin)} a ${din(OT.lpaMax)}` : 'Sem dado'}</b></div>
        </div>
        <div class="nota" style="margin-top:8px">Fonte: ${OT.fonte ? `<a class="link" href="" target="_blank" rel="noopener" id="ot-fonte"></a>` : '<span id="ot-fonte"></span>'} (${OT.data})${cambioOT}</div>
        ${proximoOT}
      </div>` : '';
    if (modo === 'graham') {
      const rg = d.regra, anos = d.lpaAnos;
      const destaque = rg.status === 'ok' ? `Média de ${anos.length} ${anos.length === 1 ? 'ano' : 'anos'}: ${din(rg.media)}`
        : rg.status === 'excluido' ? 'Ano de prejuízo excluído' : rg.status === 'recorrente' ? rg.mensagem : INDISP;
      const fonteAnual = d.lpaAnualFonte ? `Histórico de lucro por ação verificado na fonte oficial: ${d.lpaAnualFonte}. `
        : d.lpaAnualSecMotivo ? `Yahoo Finance (SEC não usada: ${d.lpaAnualSecMotivo}). ` : '';
      const nota = fonteAnual + (rg.status === 'excluido' ? `Média dos anos com lucro: ${din(rg.media)}.`
        : rg.status === 'recorrente' ? 'Dois ou mais anos de prejuízo nos últimos 3 anos.'
        : rg.status === 'ok' ? 'Sem prejuízo nos últimos 3 anos.' : 'O Yahoo Finance não traz o lucro anual deste ativo.');
      // projeção: LPA estimado pelos analistas para o ano fiscal em curso (o seguinte ao último divulgado)
      const proj = d.lynch && d.lynch.futuro ? d.lynch.futuro.lpaEsteAno : null;
      // com guidance cadastrado, o período vem da empresa (ex.: FY2027); senão, o ano seguinte ao último divulgado
      const anoProj = d.guidance && d.guidance.periodo ? d.guidance.periodo : anos.length ? anos[anos.length - 1].ano + 1 : null;
      const ultimo = anos.length ? anos[anos.length - 1].lpa : null;
      const varProj = tem(proj) && tem(ultimo) && ultimo > 0 ? (proj / ultimo - 1) * 100 : null;
      const Fu = d.lynch && d.lynch.futuro ? d.lynch.futuro : {};
      const G = d.guidance;
      const consenso = !tem(proj) ? '' : G ? (G.porLpa ? `Guidance oficial da empresa (${G.fonte}, ${G.data}): ${G.lucroTipo}${G.periodo ? ` ${G.periodo}` : ''} de ${din(G.lpaMin)} a ${din(G.lpaMax)}, ponto médio ${din(G.lpa)}`
        : `Guidance oficial da empresa (${G.fonte}, ${G.data}): ${G.lucroTipo || 'lucro líquido'} de ${din(G.lucroMin / 1e9, 1)} a ${din(G.lucroMax / 1e9, 1)} bi ÷ ${f(G.acoes / 1e9, 2)} bi de ações${G.acoesFonte === 'Yahoo Finance' ? ' (Yahoo Finance)' : ''} = LPA de ${din(G.lpaMin)} a ${din(G.lpaMax)}, ponto médio ${din(G.lpa)}`) : `Consenso${tem(Fu.analistas) ? ` de ${f(Fu.analistas, 0)} ${Fu.analistas === 1 ? 'analista' : 'analistas'}` : ' dos analistas'} no Yahoo Finance`
        + (tem(Fu.lpaBaixa) && tem(Fu.lpaAlta) ? `, de ${din(Fu.lpaBaixa)} a ${din(Fu.lpaAlta)}` : '')
        + (tem(Fu.analistas) && Fu.analistas < 3 ? '. Poucos analistas: estimativa pouco confiável' : '');
      const baseG = G && G.bases && G.bases.length ? ` Base recalculada pela empresa: ${G.bases.map(b => `${b.ano} = ${din(b.valor)}${tem(b.antes) ? ` (antes ${din(b.antes)})` : ''}`).join(', ')}; o guidance ${G.periodo || ''} (${din(G.lpa)}) fica ${sinal((G.lpa / G.bases[0].valor - 1) * 100, 1)} acima da base ${G.bases[0].ano}. Os LPAs anuais acima são do Yahoo (contábil) e não usam essa base.` : '';
      const divG = G && tem(G.dividendo) ? (G.dividendoFonte === 'empresa' ? ` Dividendo anual divulgado pela empresa: ${din(G.dividendo)}${d.preco ? ` (DY ${f(G.dividendo / d.preco * 100, 1)}%)` : ''}.`
        : ` Dividendo projetado: ${din(G.lpa)} × payout ${f(G.payout * 100, 0)}% = ${din(G.dividendo)}${d.preco ? ` (DY ${f(G.dividendo / d.preco * 100, 1)}%)` : ''}.`) : '';
      // TTM contábil (número real, já parcialmente ou totalmente dentro do ano de guidance) e o
      // guidance/consenso em si (projeção) nunca se misturam - cada um é sua própria barra no
      // gráfico (ver graficoLpa abaixo); a lista de texto equivalente foi removida (follow-up
      // 27/11/2026, a pedido do usuário - os valores já aparecem escritos em cima de cada barra).
      const temTTM = anoProj && tem(d.lpa);
      // ITEM 3 (27/11/2026): guidance encurtado pra 2-3 linhas visíveis. Follow-up no mesmo dia:
      // o botão "Ver metodologia" saiu - vira só a conta em 1 linha pequena (contaGuidance, abaixo);
      // o parágrafo completo (consenso/variação/base recalculada/dividendo) continua existindo só
      // pra quando NÃO há guidance oficial (textoProjecaoCompleto, caso `!G`, ver #g-nota-proj).
      const resumoGuidance = G ? [
        !G.porLpa && tem(G.lucroMin) && tem(G.lucroMax) ? `Lucro esperado: ${din(G.lucroMin / 1e9, 1)} a ${din(G.lucroMax / 1e9, 1)} bi` : null,
        tem(G.lpaMin) && tem(G.lpaMax) ? `LPA projetado: ${din(G.lpaMin)} a ${din(G.lpaMax)} (média ${din(G.lpa)})${tem(varProj) ? ` · ${sinal(varProj, 0)} vs ${anos.length ? anos[anos.length - 1].ano : ''}` : ''}` : null,
      ].filter(Boolean) : [];
      // follow-up (27/11/2026): botão "Ver metodologia" removido a pedido do usuário - vira 1 linha
      // pequena com a própria conta (o cálculo que já existia, só reposicionado pra ficar visível
      // direto, sem precisar abrir painel nenhum). Mesma fórmula de sempre, nenhum número novo.
      const contaGuidance = G && tem(G.lpaMin) && tem(G.lpaMax)
        ? (G.porLpa ? `(${din(G.lpaMin)} + ${din(G.lpaMax)}) ÷ 2 = ${din(G.lpa)}`
          : `(${din(G.lucroMin / 1e9, 1)} bi + ${din(G.lucroMax / 1e9, 1)} bi) ÷ 2 ÷ ${f(G.acoes / 1e9, 2)} bi ações = ${din(G.lpa)}`) : '';
      // ITEM 4 (27/11/2026): mini gráfico de barras, só com valores já mostrados na tela (os `anos`,
      // o TTM contábil já exibido no card "Lucro e Preço vs Lucro" e a projeção/guidance do ano
      // seguinte) - nenhuma fonte ou cálculo novo. 2ª mudança no mesmo dia: o ano de projeção virou
      // 2 barras (TTM real sólida + guidance/projeção tracejada) em vez de 1 só, pra não misturar
      // resultado já apurado com estimativa na mesma barra. GI.lpa (guidance do início do ano,
      // congelado) vira só uma linha pontilhada fina sobre a barra do TTM - contexto de revisão, não
      // uma barra própria (nunca com o mesmo peso visual dos números atuais).
      const GIb = d.guidanceInicial || {};
      const lpaIniBarra = tem(GIb.lpa) ? GIb.lpa : null;
      const graficoLpa = miniBarras([
        ...anos.map(a => ({ v: a.lpa, rot: a.ano })),
        temTTM ? { v: d.lpa, rot: `${anoProj} Atual (TTM)`, fantasma: lpaIniBarra, fantasmaTitulo: tem(lpaIniBarra) ? `Estimativa inicial jan/${String(anoProj).slice(-2)}: ${din(lpaIniBarra)} - revisada` : '' } : null,
        anoProj ? { v: proj, rot: `${anoProj}E ${G ? 'Guidance' : 'Projeção'}`, proj: true } : null,
      ].filter(Boolean), v => din(v));
      const notaFantasma = temTTM && tem(lpaIniBarra) ? `<div class="nota" style="margin-top:2px;opacity:.65;font-size:10.5px">╌╌╌ Estimativa inicial jan/${String(anoProj).slice(-2)}: ${din(lpaIniBarra)} - revisada</div>` : '';
      // médias mais longas (mesma fonte anual do Yahoo; "Sem dado" quando ele não tem os anos pedidos)
      // e, só no Conservador, o P/L e o preço teto sobre a média de 10 anos - regra: nunca mostra
      // "Sem dado" repetido (4 linhas vazias confundem); SÓ mostra a linha se tiver valor, e quando
      // um grupo inteiro falta, uma única nota cinza substitui as linhas vazias desse grupo.
      const grupo5e10 = [
        tem(d.lpaMedia5a) ? `<div>Média 5 anos<b>${din(d.lpaMedia5a)}</b></div>` : null,
        tem(d.lpaMedia10a) ? `<div>Média 10 anos<b>${din(d.lpaMedia10a)}</b></div>` : null,
      ].filter(Boolean);
      const grupoConservador = [
        tem(d.plConservador) ? `<div>P/L Conservador<b>${f(d.plConservador)}</b></div>` : null,
        tem(d.tetoConservador) ? `<div>Preço teto conservador<b>${din(d.tetoConservador)}</b></div>` : null,
      ].filter(Boolean);
      const linhasLongas = grupo5e10.join('') + grupoConservador.join('');
      // ITEM 6 (27/11/2026, a pedido do usuário): texto encurtado - a explicação completa (que o
      // P/L Conservador e o Preço teto também dependem da média de 10 anos) continua verdadeira,
      // só não repetida por extenso aqui; a régua de "quando falta a quê" continua a mesma.
      const notaIndisponivel = !grupo5e10.length && !grupoConservador.length
        ? 'Sem histórico de 5/10 anos para este ticker.'
        : !grupo5e10.length ? 'Sem histórico de 5/10 anos para este ticker.'
        : !grupoConservador.length ? 'P/L Conservador e Preço teto conservador indisponíveis para este ticker.'
        : '';
      const avisoAnualHtml = d.avisoGuidanceAnual ? `<div class="aviso" style="margin-bottom:10px">${d.avisoGuidanceAnual}</div>` : '';
      // texto completo da projeção (consenso/variação/base recalculada/dividendo) - igual ao de
      // antes, palavra por palavra; só mudou de lugar (visível direto -> "Ver metodologia" quando
      // há guidance oficial, ver resumoGuidance acima).
      const textoProjecaoCompleto = anoProj ? `${tem(proj) ? `Projeção ${anoProj}: ${consenso}${tem(varProj) ? `; ${sinal(varProj, 0)} sobre ${anos.length ? anos[anos.length - 1].ano : ''}${G && G.porLpa ? ' (o guidance é LPA ajustado; o ano anterior é o LPA contábil do Yahoo, bases diferentes)' : ''}` : ''}.${divG}${baseG} Não entra na média.${G ? ' O guidance oficial substitui o consenso dos analistas do Yahoo.' : ''}` : `Sem estimativa no Yahoo para ${anoProj}.`}` : '';
      el.innerHTML = `<h2>Lucro por ação <small>últimos 3 anos${anoProj ? ` + projeção ${anoProj}` : ''}</small></h2>
        ${avisoAnualHtml}
        <div class="card">${G ? `<div style="margin-bottom:10px">
          <span class="selo ok">GUIDANCE OFICIAL · ${G.data}</span>
          ${resumoGuidance.length ? `<div class="nota num" style="margin-top:6px">${resumoGuidance.join('<br>')}</div>` : ''}
          ${contaGuidance ? `<div class="nota num" style="margin-top:4px;opacity:.75;font-size:11.5px">${contaGuidance}</div>` : ''}
          </div>` : ''}
          ${graficoLpa}
          ${notaFantasma}
          <div class="destaque" style="${rg.status === 'recorrente' ? 'color:var(--vermelho)' : ''}">${destaque}</div>
          ${linhasLongas ? `<div class="lista-v num" style="margin-top:10px">${linhasLongas}</div>` : ''}
          ${notaIndisponivel ? `<div class="nota" style="margin-top:10px">${notaIndisponivel}</div>` : ''}
          <div class="nota" id="g-nota"></div>${!G ? `<div class="nota" id="g-nota-proj" style="margin-top:4px"></div>` : ''}</div>${outlookHtml}`;
      el.querySelector('#g-nota').textContent = nota;
      if (!G) { const gp = el.querySelector('#g-nota-proj'); if (gp) gp.textContent = textoProjecaoCompleto; }
    } else if (modo === 'lynch') {
      const L = d.lynch, v = L.veredito, F = L.futuro, pc = x => tem(x) ? `${sinal(x, 1)} ao ano` : 'Sem dado';
      // crescimento acima de 100% ao ano vem de base quase zero: mostra quantas vezes multiplicou
      const cresc = (x, anos) => !tem(x) ? 'Sem dado' : x > 100 && anos ? `${f(Math.pow(1 + x / 100, anos), 1)}x no período` : pc(x);
      const corV = { verde: 'var(--verde)', amarelo: 'var(--ambar)', vermelho: 'var(--vermelho)' }[v.cor] || 'var(--suave)';
      const stV = { verde: 'bom', vermelho: 'ruim' }[v.cor] || 'neutro';
      const mini = (r, val) => `<div class="ind"><span class="rot">${r}</span><span class="v num" style="font-size:18px">${val}</span></div>`;
      const rg = d.regra, anos = d.lpaAnos;
      const lpas = anos.map(a => `<div>${a.ano}<b style="color:${a.lpa < 0 ? 'var(--vermelho)' : 'inherit'}">${din(a.lpa)}</b></div>`).join('');
      const media = rg.status === 'ok' ? `<div>Média de ${anos.length} ${anos.length === 1 ? 'ano' : 'anos'}<b>${din(rg.media)}</b></div>`
        : rg.status === 'excluido' ? `<div>Média (ano de prejuízo excluído)<b>${din(rg.media)}</b></div>` : '';
      const fut = (titulo, valor, base, chave) => `<div class="fut"><div class="duas"><span>${titulo}${ex(chave)}</span><b class="num">${valor}</b></div><div class="nota">Base: ${base}</div></div>`;
      const semEstimativa = !tem(F.lucroLongo) && !tem(F.receitaProx) && !tem(F.lpaEsteAno);
      el.innerHTML = `<h2>Crescimento <small>passado x futuro</small></h2>
        <div class="grade2">
          ${mini('P/L', tem(d.pl) ? f(d.pl) : '—')}${mini('PEG (Yahoo)', tem(L.pegYahoo) ? f(L.pegYahoo) : '—')}
          ${mini('Receita no trimestre', tem(L.receitaTrimestre) ? sinal(L.receitaTrimestre, 1) : '—')}${mini('Lucro no trimestre', tem(L.lucroTrimestre) ? sinal(L.lucroTrimestre, 1) : '—')}
        </div>
        <div class="nota" style="margin:6px 2px 12px">Trimestre mais recente contra o mesmo trimestre do ano anterior.</div>
        <div class="pilha">
          <div class="card"><span class="rot">Passado</span><div class="nota">Últimos 3 anos · lucro por ação de cada ano</div>
            ${lpas ? `<div class="lista-v num">${lpas}${media}</div>` : `<div class="nota" style="margin-top:8px">Sem dado</div>`}
            ${rg.status === 'excluido' ? '<div class="destaque">Ano de prejuízo excluído</div>' : ''}
            ${rg.status === 'recorrente' ? '<div class="destaque" style="color:var(--vermelho)">Sem PEG - não compra empresa sem lucro</div>' : ''}
            <div class="lista-v num" style="margin-bottom:0"><div>Lucro${L.passado.anosLucro ? ` (em ${L.passado.anosLucro} ${L.passado.anosLucro === 1 ? 'ano' : 'anos'})` : ''}<b>${cresc(L.passado.lucro, L.passado.anosLucro)}</b></div><div>Receita${L.passado.anosReceita ? ` (em ${L.passado.anosReceita} ${L.passado.anosReceita === 1 ? 'ano' : 'anos'})` : ''}<b>${cresc(L.passado.receita, L.passado.anosReceita)}</b></div></div>
            ${[L.passado.lucro, L.passado.receita].some(x => tem(x) && x > 100) ? '<div class="nota" style="margin-top:8px">Base inicial muito baixa: o valor multiplicou no período, e o crescimento ao ano não serve para comparar.</div>' : ''}
          </div>
          <div class="card"><span class="rot">Futuro</span><div class="nota">O que o Yahoo fornece de estimativa</div>
            ${semEstimativa ? '<div class="destaque">Sem PEG - Sem estimativa no Yahoo para este ativo</div>' : ''}
            ${fut('Lucro - Longo prazo', tem(F.lucroLongo) ? `${sinal(F.lucroLongo, 1)} ao ano` : 'Sem dado', 'Estimativa longo prazo Yahoo', 'lucroLongo')}
            ${fut('Receita - Próximo ano fiscal', tem(F.receitaProx) ? sinal(F.receitaProx, 1) : 'Sem dado', `Próximo ano fiscal Yahoo${tem(F.analistasReceita) ? ` · ${f(F.analistasReceita, 0)} analistas` : ''}`, 'receitaProx')}
            ${fut('Lucro - Este ano', tem(F.lpaEsteAno) ? `LPA ${d.guidance ? 'do guidance' : 'estimado'} ${din(F.lpaEsteAno)}` : 'Sem dado', d.guidance ? `Guidance oficial · ${d.guidance.fonte} · ${d.guidance.data}` : `Estimativa ano atual Yahoo${tem(F.analistas) ? ` · ${f(F.analistas, 0)} analistas` : ''}${tem(F.lpaBaixa) && tem(F.lpaAlta) ? ` · de ${din(F.lpaBaixa)} a ${din(F.lpaAlta)}` : ''}`, 'lpaEsteAno')}
          </div>
        </div>
        <div class="card" style="margin-top:10px;border-left:3px solid ${corV}">
          <div class="cab"><span class="rot">PEG do Futuro${ex('lucroLongo')}</span><span class="st ${stV}">${v.titulo}</span></div>
          <div class="num" style="font-size:26px;font-weight:700;margin:6px 0 2px;color:${corV}">${tem(L.pegFuturo) ? f(L.pegFuturo) : '—'}</div>
          <div class="nota num">${tem(L.pegFuturo) ? `PEG = P/L ${f(d.pl)} / Crescimento ${f(F.lucroLongo, 1)}% = ${f(L.pegFuturo)}` : 'PEG do Futuro = P/L dividido pelo Crescimento Longo Prazo do Lucro'}</div>
          ${v.motivo ? `<div class="destaque">${v.motivo}</div>` : ''}
        </div>
        <div class="aviso" style="margin-top:10px">PEG do futuro usa estimativa. Se a empresa não entregar esse crescimento, a tese cai.</div>${outlookHtml}`;
    } else {
      const sm = d.simons, mx = sm.maximo || 5, bolas = Array.from({ length: mx }, (_, k) => `<i class="${k < sm.nivel ? 'on' : ''}"></i>`).join('');
      const dias = `${sm.dias} ${sm.dias === 1 ? 'dia' : 'dias'}`;
      // régua visual (mesmo padrão das outras barras): nomes em cima, valores dos limites, bola com o valor embaixo
      const barra = ({ ini, fim, segs, marcas = [], bola, rotBola, extra = '' }) => {
        const pos = v => Math.max(0, Math.min(100, (v - ini) / (fim - ini) * 100));
        let ant = ini; const cols = segs.map(g => { const w = pos(g.ate) - pos(ant); ant = g.ate; return w; });
        let acc = 0; const grad = segs.map((g, k) => { const a0 = acc; acc += cols[k]; return `${g.cor} ${a0}% ${acc}%`; }).join(',');
        return `<div class="zonas-rot" style="grid-template-columns:${cols.map(w => `${Math.max(w, 0.01)}fr`).join(' ')}">${segs.map(g => `<span style="color:${g.corTxt || g.cor}"><b>${g.nome}</b></span>`).join('')}</div>
          <div class="marca-cima limites num">${marcas.map((m, k) => `<span class="${k === 0 && m.v === ini ? 'esq' : k === marcas.length - 1 && m.v === fim ? 'dir' : ''}" style="${(k === 0 && m.v === ini) || (k === marcas.length - 1 && m.v === fim) ? '' : `left:${pos(m.v)}%`};${m.cor ? `color:${m.cor}` : ''}">${m.t}</span>`).join('')}</div>
          <div class="regua" style="background:linear-gradient(90deg,${grad});margin-top:4px">${segs.slice(0, -1).map(g => `<span class="traco" style="left:${pos(g.ate)}%"></span>`).join('')}${extra.replace(/POS\((.+?)\)/g, (_, v) => pos(+v))}${tem(bola) ? `<span class="bola" style="left:${pos(bola)}%"></span>` : ''}</div>
          ${tem(bola) ? `<div class="marca-baixo so-valor num"><span style="${ancora(pos(bola))}">${rotBola}</span></div>` : ''}`;
      };
      const nomeClasse = { OPORTUNIDADE: 'Oportunidade', NEUTRO: 'Neutro', CARO: 'Caro' }[sm.classe] || '—';
      const corClasse = { OPORTUNIDADE: 'var(--verde)', CARO: 'var(--vermelho)' }[sm.classe] || 'var(--texto)';
      const tendTxt = !tem(sm.mm200Incl) ? '' : `Média 200d ${sm.mm200Incl > 1 ? 'subindo' : sm.mm200Incl < -1 ? 'caindo' : 'de lado'} (${sinal(sm.mm200Incl, 1)} em 3 meses); preço ${sinal(sm.distMM200, 1)} da média.`;
      // 2. classificação na faixa de 52 semanas, com a MM200 marcada
      // barra da classificação, só pela MM200: bem abaixo (< -10%), oportunidade (-10% a +5%), neutra (+5% a +15%), cara (+15%+)
      const temFaixa = [sm.min52, sm.max52, sm.oportunidadeAte, sm.caraAcima].every(tem) && sm.max52 > sm.min52;
      const bA = tem(sm.bemAbaixoAte) ? sm.bemAbaixoAte : null;
      const ini2 = temFaixa ? Math.min(sm.min52, (bA || sm.oportunidadeAte) * 0.95, d.preco) : 0;
      const fim2 = temFaixa ? Math.max(sm.max52, sm.caraAcima * 1.05, d.preco) : 1, amp2 = fim2 - ini2;
      const limites2 = [bA, sm.oportunidadeAte, sm.caraAcima].filter(tem);
      const marcas2 = [{ v: ini2, t: f(ini2), ponta: 1 }, ...limites2.map(v => ({ v, t: f(v) })), { v: fim2, t: f(fim2), ponta: 1 }]
        .filter(m => !m.ponta || Math.min(...limites2.map(l => Math.abs(m.v - l))) / amp2 > 0.12);
      const cartao2 = !temFaixa ? '<div class="nota">Sem faixa de 52 semanas.</div>' : barra({
        ini: ini2, fim: fim2, bola: d.preco, rotBola: `Hoje ${f(d.preco)}`,
        segs: [...(bA ? [{ ate: bA, cor: '#3b6fd8', corTxt: '#7aa2f7', nome: 'Bem abaixo' }] : []),
          { ate: sm.oportunidadeAte, cor: 'var(--verde)', nome: 'Oportunidade' }, { ate: sm.caraAcima, cor: 'var(--ardosia)', corTxt: '#aab4c6', nome: 'Neutra' }, { ate: fim2, cor: 'var(--ambar)', nome: 'Cara' }],
        marcas: marcas2,
        // rótulo da MM200 embaixo; se ficar perto do "Hoje", desce uma linha para não sobrepor
        extra: tem(sm.mm200) ? `<span class="traco mm" style="left:POS(${sm.mm200})%"></span><span class="mm-rot" style="left:POS(${sm.mm200})%;${Math.abs(sm.mm200 - d.preco) / amp2 < 0.25 ? 'top:38px' : ''}">MM200 ${f(sm.mm200)}</span>` : '' });
      const mmPerto = tem(sm.mm200) && temFaixa && Math.abs(sm.mm200 - d.preco) / amp2 < 0.25;
      // 3. dias de queda: régua de 0 a 10 com as partes da entrada
      const foraOp = sm.classe !== 'OPORTUNIDADE';
      const segsBase = sm.conservador
        ? [{ ate: 4, cor: 'var(--ardosia)', corTxt: '#aab4c6', nome: 'Observa' }, { ate: 7, cor: '#2fbf8a66', corTxt: 'var(--verde)', nome: '1/3' }, { ate: 10, cor: '#2fbf8aaa', corTxt: 'var(--verde)', nome: '2/3' }]
        : [{ ate: 2, cor: 'var(--ardosia)', corTxt: '#aab4c6', nome: 'Observa' }, { ate: 4, cor: '#2fbf8a55', corTxt: 'var(--verde)', nome: '1/3' }, { ate: 7, cor: '#2fbf8a99', corTxt: 'var(--verde)', nome: '2/3' }, { ate: 10, cor: 'var(--verde)', nome: '3/3' }];
      // fora da oportunidade a régua continua com as partes, mas apagada: mostra o que valeria se fosse oportunidade
      const segsDias = foraOp ? segsBase.map(g => ({ ...g, cor: '#3a4558', corTxt: 'var(--fraco)' })) : segsBase;
      const marcasDias = [0, ...segsDias.slice(0, -1).map(g => g.ate), 10].map(v => ({ v, t: v === 10 ? '10+ dias' : v === 0 ? '0 dia' : `${v} dias` }));
      const cartao3 = barra({ ini: 0, fim: 10, segs: segsDias, marcas: marcasDias, bola: Math.min(sm.dias, 10), rotBola: sm.dias ? `Hoje: ${dias} de queda (${sinal(sm.queda)})` : 'Hoje: sem queda' });
      // histórico: quantas vezes subiu e caiu no dia seguinte (sem porcentagem solta)
      const maxV = Math.max(1, ...(sm.historico || []).map(h => h.vezes));
      // "melhor" vem do cálculo: 30+ casos, 8+ pontos acima da média geral e 5+ acima da segunda melhor
      const M = sm.melhor || {}, melhor = M.dias ? (sm.historico || []).find(h => h.dias === M.dias) : null;
      const linhasHist = (sm.historico || []).map(h => {
        const caiu = h.vezes - h.altas, wS = h.altas / maxV * 100, wC = caiu / maxV * 100, atual = h.dias === Math.min(sm.dias, mx), top = melhor && h.dias === melhor.dias;
        return `<div class="hist-l${atual ? ' atual' : ''}${top ? ' melhor' : ''}"><span class="n">${h.dias}${h.dias === mx ? '+' : ''} ${h.dias === 1 ? 'dia' : 'dias'}${atual ? '<em class="tag-h hoje">hoje</em>' : ''}${top ? '<em class="selo-melhor">★ MELHOR</em>' : ''}</span>
          <span class="t">${h.vezes ? `<i class="s" style="width:${wS}%"></i><i class="c" style="width:${wC}%"></i>` : ''}</span>
          <span class="v num">${h.vezes ? `<b class="vs">${h.altas}</b> / <b class="vc">${caiu}</b>` : 'nenhum caso'}</span></div>`;
      }).join('');
      // régua fixa: mesma barra, de 1 a 5+ dias
      const RG = [[1, 51, 'Nada', 'var(--ardosia)', '#aab4c6'], [2, 54, 'Observa', '#f2c94c66', 'var(--ambar)'], [3, 58, 'Pequeno', '#2fbf8a55', 'var(--verde)'], [4, 61, 'Médio', '#2fbf8a99', 'var(--verde)'], [5, 64, 'Maior', 'var(--verde)', 'var(--verde)']];
      const cartaoRegua = barra({ ini: 0.5, fim: 5.5, segs: RG.map(([n, , nome, cor, corTxt]) => ({ ate: n + 0.5, cor, corTxt, nome })),
        marcas: RG.map(([n, p]) => ({ v: n, t: `${n}${n === 5 ? '+' : ''}d · ${p}%` })), bola: sm.nivel ? Math.min(sm.nivel, 5) : null, rotBola: dias });
      el.innerHTML = `<h2>Movimento curto <small>MM200 → oportunidade → dias</small></h2>
        <div class="card"><span class="rot">1-2. Média de 200 dias e classificação</span>
          <div class="duas" style="margin:8px 0 2px"><span class="esq">Classificação</span><span class="dir" style="color:${sm.subzona === 'Bem abaixo da MM200' ? '#7aa2f7' : corClasse}">${sm.subzona === 'Bem abaixo da MM200' ? 'Bem abaixo da MM200' : nomeClasse}${sm.conservador ? ' · conservador' : ''}</span></div>
          ${cartao2}
          <div class="nota" style="margin-top:${mmPerto ? 20 : 2}px">${tendTxt} Faixa de 52 semanas (30/70): Oportunidade = zona verde (até ${din(sm.oportunidadeAte)}) e preço até +5% da MM200. Caro = zona amarela (acima de ${din(sm.caraAcima)}) ou +15% ou mais acima da MM200. O resto é Neutro.${sm.conservador ? ' Conservador: abaixo da MM200 com a média caindo.' : ''}</div></div>
        <div class="card" style="margin-top:8px"><span class="rot">3. Dias de queda (momento da entrada)</span>
          <div class="duas" style="margin:8px 0 2px"><span class="esq">Entrada hoje</span><span class="dir">${sm.entrada}</span></div>
          <div class="nota" style="margin:0 0 4px">${foraOp ? `Régua apagada: a classificação é ${nomeClasse}, então os dias de queda não abrem compra. As partes mostram como seria numa oportunidade.` : `Quanto comprar conforme os dias de queda${sm.conservador ? ' (modo conservador)' : ''}.`}</div>
          ${cartao3}
          <div class="nota" style="margin-top:2px">${sm.dias ? `Topo ${din(sm.topo)} em ${sm.topoData}${sm.altas ? `, ${sm.altas} ${sm.altas === 1 ? 'alta' : 'altas'} no meio` : ''}. ` : ''}${sm.entradaDetalhe}. ${sm.classe === 'OPORTUNIDADE' ? (sm.conservador ? 'A última parte só com o preço acima da MM200 ou a média parando de cair.' : 'O 5º dia sozinho nunca manda a compra toda.') : ''}</div></div>
        <div class="card" style="margin-top:8px"><span class="rot">O que aconteceu no dia seguinte · desde ${sm.histDesde}</span>
          ${(() => { const h = (sm.historico || []).find(x => x.dias === Math.min(sm.dias, mx)); return h && h.vezes ? `<p class="destaque" style="margin:8px 0 10px;font-size:14px">Nos últimos 5 anos, a ${d.ticker} chegou a ${h.dias}${h.dias === mx ? ' ou mais' : ''} ${h.dias === 1 ? 'dia' : 'dias'} de queda <b>${h.vezes} vezes</b>. No pregão seguinte, <b style="color:var(--verde)">subiu em ${h.altas}</b> e <b style="color:var(--vermelho)">caiu em ${h.vezes - h.altas}</b>.</p>` : ''; })()}
          ${melhor ? `<p class="nota" style="margin:-4px 0 10px"><b style="color:var(--texto)">★ Melhor resultado no período:</b> ${melhor.dias}${melhor.dias === mx ? ' ou mais' : ''} ${melhor.dias === 1 ? 'dia' : 'dias'} de queda. Subiu no dia seguinte em ${melhor.altas} de ${melhor.vezes} vezes (${f(M.pct, 0)}%, contra ${f(M.media, 0)}% na média de todas as linhas)${melhor.dias === Math.min(sm.dias, mx) ? '. É a situação de hoje' : ''}.</p>`
            : M.motivo === 'ruido' ? (() => {
                const dd = n => `${n}${n === mx ? '+' : ''} ${n === 1 ? 'dia' : 'dias'}`;
                const porque = [M.falhaMedia ? `fica só ${f(M.topPct - M.media, 0)} pontos acima da média geral (${f(M.media, 0)}%; precisa de 8)` : '',
                  M.falhaSegundo ? `fica só ${f(M.topPct - M.segundo, 0)} pontos acima do segundo, ${dd(M.segundoDias)} com ${f(M.segundo, 0)}% (precisa de 5)` : ''].filter(Boolean).join(' e ');
                return `<p class="nota" style="margin:-4px 0 10px"><b style="color:var(--texto)">Nenhum padrão forte.</b> O maior resultado, ${dd(M.topDias)} com ${f(M.topPct, 0)}% de alta no dia seguinte, ${porque}. Diferença dentro do ruído.</p>`; })()
            : `<p class="nota" style="margin:-4px 0 10px">Poucos casos para apontar um padrão.</p>`}
          <div class="hist-l cab"><span class="n">Dias de queda</span><span class="t-cab"><i style="--c:var(--verde)">subiu</i><i style="--c:var(--vermelho)">caiu</i></span><span class="v">subiu / caiu</span></div>
          <div class="hist">${linhasHist}</div>
          <div class="nota" style="margin-top:6px">Cada linha: quantas vezes a ação chegou àquele número de dias de queda e, no pregão seguinte, quantas vezes subiu (verde) e caiu (vermelho). Barra maior = mais casos. Contorno azul = hoje. ★ MELHOR só aparece com 30+ casos, 8+ pontos acima da média geral e 5+ pontos acima da segunda melhor.</div></div>
        <div class="card" style="margin-top:8px"><span class="rot">Régua fixa (igual para qualquer ação)</span>
          ${cartaoRegua}</div>
        <div style="margin-top:10px"><span class="selo sem">${sm.selo}</span></div>
        <p class="nota" style="margin:10px 2px 0">Os dias contam desde o maior fechamento dos últimos ${sm.pregoes} pregões, desde que o último pregão tenha sido de queda. Uma alta no meio não quebra a contagem enquanto o preço não passar do topo. O histórico usa a mesma regra nos últimos 5 anos da ação; cada queda conta uma vez em cada linha (a de 10 ou mais só no dia em que chega a 10). Com menos de 20 casos, a porcentagem é pouco confiável. A régua fixa é igual para qualquer ação e ainda não foi testada.</p>${outlookHtml}`;
    }
    if (OT) { const oz = el.querySelector('#ot-fonte'); if (oz) { oz.textContent = OT.fonte; oz.href = OT.url || ''; } }
  }

  const SECOES = { faixa: ['graham'], tendencia: ['graham', 'lynch', 'simons'], minmax: ['graham', 'simons'],
    fundamentos: ['graham', 'lynch'], indicadores: ['graham', 'lynch'], retorno: ['graham', 'lynch'] };
  function renderModo() {
    root.querySelectorAll('.modos button').forEach(b => b.setAttribute('aria-pressed', b.dataset.modo === modo));
    Object.entries(SECOES).forEach(([id, modos]) => { $(id).hidden = !modos.includes(modo); });
    renderDecisao(); renderBloco(); aoMudarModo();
  }
  root.querySelectorAll('.modos button').forEach(b => { b.onclick = () => {
    modo = b.dataset.modo;
    try { sessionStorage.setItem('fintai-modo', modo); } catch (e) { /* sem armazenamento */ }
    renderModo();
  }; });
  renderModo();

  return () => limpar.forEach(fn => fn());
}

export default function (component) {
  const { data, parentElement } = component;
  if (!data || !data.dados) return;
  if (parentElement.__fintaiLimpar) { try { parentElement.__fintaiLimpar(); } catch (e) { /* já desmontado */ } }
  parentElement.__fintaiLimpar = montar(parentElement, data.dados);
  return parentElement.__fintaiLimpar;
}
