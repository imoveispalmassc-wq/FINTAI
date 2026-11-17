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
  const limpar = [];
  const ex = chave => (d.exemplos && d.exemplos[chave] ? ' <span class="tag-proto">EXEMPLO</span>' : '');
  const FOLHAS = {};
  const fonte = `<p><b>Fonte:</b> ${d.fonte} · atualizado em ${d.atualizado}.</p>`;
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
  const metodosJusto = [['Graham', d.graham], ['P/L histórico', d.justoPL]]
    .concat(naoPagadora ? [] : [['Bazin', d.bazin]]).filter(m => tem(m[1]) && m[1] > 0).sort((a, b) => a[1] - b[1]);

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
  let modo = 'graham';
  try { modo = sessionStorage.getItem('fintai-modo') || 'graham'; } catch (e) { /* sem armazenamento */ }
  if (!['graham', 'lynch', 'simons'].includes(modo)) modo = 'graham';
  let aoMudarModo = () => {};
  const TEXTO_MODO = {
    graham: 'Modo longo prazo. Para segurar por anos. Pode demorar anos até comprar.',
    lynch: 'Modo longo prazo. Para quem entende a empresa e o crescimento. Não é para movimento curto.',
    simons: 'Modo movimento curto: primeiro a média de 200 dias, depois a oportunidade, por último os dias de queda para escalonar a entrada. Não é para segurar anos.',
  };
  // selo do modo Graham: vem do teste real das zonas em 5 anos
  const bt5 = d.backtest['5a'];
  const seloGraham = !bt5 ? ['sem', 'SEM TESTE - Histórico curto para 5 anos']
    : !bt5.oportunidade.vezes ? ['sem', 'SEM CASOS - Preço não esteve na Zona de Oportunidade em 5 anos']
    : bt5.compraValidada ? ['ok', 'VALIDADO - Ganhou do buy-and-hold em 5 anos']
    : bt5.oportunidade.retorno < bt5.referencia.retorno ? ['nao', 'INVALIDADO - Perdeu pro buy-and-hold em 5 anos']
    : ['nao', 'INVALIDADO - Não ganhou do buy-and-hold em 5 anos'];

  function renderDecisao() {
    const el = $('decisao');
    let rotulo, classe = '', texto, pilula = '', selo = null, alerta = '', extra = '';
    if (modo === 'graham') {
      const e = fx.decisao; rotulo = e.rotulo; texto = e.texto; pilula = e.zona;
      selo = fx.testada ? seloGraham : ['sem', `SEM TESTE - Zonas de ${fx.curto} não têm teste histórico`];
      classe = e.codigo === 'COMPRAR' ? (e.validado ? 'COMPRAR' : '') : e.codigo === 'CARO' ? 'CARO' : '';
      alerta = e.alerta || '';
    } else if (modo === 'lynch') {
      // Lynch só pela MM200 (ignora a faixa 30/70): oportunidade de -10% a +5%, neutro até +15%, caro acima
      const LP = d.lynch.preco, e = LP || fx.decisao, v = d.lynch.veredito; rotulo = e.rotulo; texto = e.texto; pilula = e.zona;
      classe = e.codigo === 'COMPRAR' ? (LP || e.validado ? 'COMPRAR' : '') : e.codigo === 'CARO' ? 'CARO' : '';
      alerta = LP ? `Preço ${sinal(LP.dist, 1)} da média de 200 dias (${din(LP.mm200)}). Lynch: oportunidade de ${din(LP.bemAbaixoAte)} a ${din(LP.oportunidadeAte)} (MM200 −10% a +5%), neutro até ${din(LP.caroAcima)}, caro acima.${LP.zona === 'Bem abaixo da MM200' ? ' Hoje está bem abaixo da MM200 (mais de 10%).' : ''}` : (e.alerta || '');
      const zona = LP && LP.zona === 'Bem abaixo da MM200' ? 'faixa Bem abaixo da MM200' : { COMPRAR: 'Zona de Oportunidade', AGUARDAR: 'Zona Neutra', CARO: 'Zona Cara' }[e.codigo];
      const conclusao = v.cor === 'verde'
        ? (e.codigo === 'COMPRAR' ? 'Lynch aprova o crescimento e o preço está na Zona de Oportunidade.'
          : `Lynch aprova o crescimento, mas o preço está na ${zona}. Por isso: AGUARDAR.`)
        : v.cor === 'amarelo' ? `Lynch fica de olho no crescimento, e o preço está na ${zona}.${e.codigo === 'COMPRAR' ? '' : ' Por isso: AGUARDAR.'}`
        : v.cor === 'vermelho' ? `Lynch não compra pelo crescimento, qualquer que seja o preço. O preço está na ${zona}.`
        : `Sem PEG para avaliar o crescimento. O preço está na ${zona}.`;
      const stV = { verde: 'bom', vermelho: 'ruim' }[v.cor] || 'neutro';
      extra = `<div class="lynch-linha"><span class="st ${stV}">${v.titulo}</span>${ex('lucroLongo') || ex('receitaProx')}
        ${tem(d.lynch.pegFuturo) ? `<div class="nota num" style="margin-top:8px">PEG = P/L ${f(d.pl)} / Crescimento ${f(d.lynch.futuro.lucroLongo, 1)}% = ${f(d.lynch.pegFuturo)}</div>` : ''}
        <div class="destaque">${conclusao}</div></div>`;
    } else {
      const sm = d.simons, hA = sm.histAtual;
      const R = { OPORTUNIDADE: ['COMPRAR - Oportunidade', 'COMPRAR'], NEUTRO: ['AGUARDAR - Neutro', 'AGUARDAR'], CARO: ['CARO - Evitar', 'CARO'] }[sm.classe] || [sm.acao, ''];
      rotulo = R[0]; classe = R[1];
      const mmTxt = tem(sm.mm200) ? `Média 200d ${din(sm.mm200)}: preço ${sinal(sm.distMM200, 1)} ${sm.distMM200 < 0 ? 'abaixo' : 'acima'}${sm.mm200Caindo ? ', média caindo' : ''}.` : 'Sem média de 200 dias (histórico curto).';
      const diasTxt = sm.dias ? `${sm.dias} ${sm.dias === 1 ? 'dia' : 'dias'} de queda desde o topo${sm.altas ? ` (${sm.altas} ${sm.altas === 1 ? 'alta' : 'altas'} no meio)` : ''}, ${sinal(sm.queda)}` : 'sem queda no último pregão';
      texto = `1. ${mmTxt} 2. ${sm.classe === 'OPORTUNIDADE' ? 'Oportunidade' : sm.classe === 'CARO' ? 'Caro' : 'Neutro'} (faixa de 52 semanas: ${(sm.zona52 || '').toLowerCase()}). 3. ${diasTxt}: ${sm.entrada}. ${sm.entradaDetalhe}.`
        + (hA && hA.vezes && sm.classe === 'OPORTUNIDADE' ? ` Histórico da ação: subiu no dia seguinte em ${f(hA.pct, 0)}% de ${hA.vezes} ${hA.vezes === 1 ? 'vez' : 'vezes'}${hA.vezes < 20 ? ' (poucos casos)' : ''}.` : '')
        + ` Ponto de oportunidade em ${din(sm.oportunidadeAte)}.`;
      selo = ['sem', sm.selo];
    }
    const nome = document.createElement('div'); nome.className = 'razao'; nome.textContent = `${d.razao} · ${d.ticker}`;
    el.innerHTML = `<div class="decisao">
      <div class="modo-texto">${TEXTO_MODO[modo]}</div>
      <div class="meta">Último pregão ${d.data} · ${d.codMoeda} · ${d.fonte}</div>
      <div class="linha"><span class="preco num">${din(d.preco)}</span>
        ${tem(d.varDia) ? `<span class="var num" style="color:${cor(d.varDia)}">${seta(d.varDia)} ${sinal(d.varDia)} no dia</span>` : ''}</div>
      ${d.after ? `<div class="after num" style="color:${cor(d.after.variacao)}">After Market: ${din(d.after.preco)} ${seta(d.after.variacao)} ${sinal(d.after.variacao)}${d.after.hora ? ` | ${d.after.hora}` : ''}</div>` : ''}
      <div><span class="badge ${classe}" id="d-rotulo"></span></div>
      <div class="ponto" id="d-texto"></div>
      ${pilula ? `<span class="pilula">${pilula}</span>` : ''}
      ${alerta ? `<div class="nota" style="margin-top:10px;color:var(--ambar)">${alerta}</div>` : ''}
      ${selo ? `<div style="margin-top:12px"><span class="selo ${selo[0]}">${selo[1]}</span>${modo === 'simons' ? ex('simons') : ''}</div>` : ''}
      ${extra}
    </div>`;
    el.firstElementChild.insertBefore(nome, el.firstElementChild.children[1]);
    $('d-rotulo').textContent = rotulo; $('d-texto').textContent = texto;
  }

  /* ---------------- gráfico */
  let backtest;
  (function StockChart(el) {
    const ESCALAS = [['10d', '10D'], ['hoje', 'Hoje'], ['1s', '1S'], ['1m', '1M'], ['1a', '1A'], ['5a', '5A'], ['max', 'Máx.']];
    const series = d.series;
    let escala = series['1a'] ? '1a' : (ESCALAS.find(([k]) => k !== '10d' && series[k]) || [null])[0];
    if (!escala) { el.innerHTML = `<div class="aviso">${INDISP}</div>`; return; }
    let velas = false, prog = 1, toque = null, toqueY = 0, raf = 0;
    // média dos valores arredondados que a tela mostra: (452 + 1.661) / 2 = 1.056,5 -> 1.057
    const justoY = metodosJusto.length >= 2 ? Math.round(metodosJusto.reduce((a, m) => a + Math.round(m[1]), 0) / metodosJusto.length) : null;
    const justoDivergem = metodosJusto.length >= 2 && metodosJusto[metodosJusto.length - 1][1] / metodosJusto[0][1] > 2;

    el.innerHTML = `<div class="grafico" id="gbox">
        <canvas id="gcanvas" role="img" aria-label="Gráfico de preço de ${d.ticker}"></canvas>
        <button class="expandir" id="gexp" aria-label="Expandir gráfico"><svg class="i" viewBox="0 0 24 24" style="width:17px;height:17px"><path d="M9 4H4v5M15 4h5v5M9 20H4v-5M15 20h5v-5"/></svg></button>
      </div>
      <div class="escalas" role="group" aria-label="Período do gráfico">
        ${ESCALAS.map(([k, r]) => `<button class="e" data-e="${k}" aria-pressed="${k === escala}" ${series[k] ? '' : 'disabled'}>${r}</button>`).join('')}
        <button class="vela" id="gvela" aria-pressed="false" aria-label="Alternar entre linha e candles"><svg class="i" viewBox="0 0 24 24" style="width:18px;height:18px"><path d="M8 3v4M8 15v6M16 3v6M16 17v4"/><rect x="5.5" y="7" width="5" height="8" rx="1"/><rect x="13.5" y="9" width="5" height="8" rx="1"/></svg></button>
      </div>
      <div class="legenda-var num"><span id="gvar"></span> · <button class="link" data-folha="grafico">Ver como calculamos</button></div>`;

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
      const refsS = modo === 'simons' ? [d.simons.mm200, d.simons.oportunidadeAte, d.simons.caraAcima, d.simons.bemAbaixoAte].filter(tem)
        : LPr && escala !== '5a' && escala !== 'max' ? [LPr.mm200, LPr.oportunidadeAte, LPr.caroAcima].filter(tem) : [];
      const vmin = Math.min(...lo, ...refsS), vmax0 = Math.max(...hi, ...refsS);
      // SIMONS 10D: espaço livre em cima para o % de cada dia de queda
      const vmax = modo === 'simons' && escala === '10d' ? vmax0 + (vmax0 - vmin) * 0.16 : vmax0, folga = (vmax - vmin) * 0.05 || 1;
      const Y = v => yPlot - (v - (vmin - folga)) / (vmax - vmin + 2 * folga) * (yPlot - yTop);
      const X = i => x0 + (x1 - x0) * (n === 1 ? 0 : i / (n - 1));
      ctx.font = '11px Inter, system-ui, sans-serif'; ctx.textBaseline = 'middle';

      // zonas, linhas e rótulos: nos modos Graham e Lynch
      if (modo !== 'simons') {
      const LPg = modo === 'lynch' && d.lynch && d.lynch.preco;
      const zOport = LPg ? LPg.oportunidadeAte : zOportF, zCara = LPg ? LPg.caroAcima : zCaraF;
      ctx.save(); ctx.beginPath(); ctx.rect(x0, yTop - 6, x1 - x0, yPlot - yTop + 6); ctx.clip();
      ctx.fillStyle = '#2fbf8a1c'; ctx.fillRect(x0, Y(zOport), x1 - x0, LPg ? Y(LPg.bemAbaixoAte) - Y(zOport) : 4000);
      if (LPg) { ctx.fillStyle = '#5b8def1a'; ctx.fillRect(x0, Y(LPg.bemAbaixoAte), x1 - x0, 4000); }
      ctx.fillStyle = '#f06a6a1a'; ctx.fillRect(x0, Y(zCara) - 4000, x1 - x0, 4000);
      // tracejados das zonas, com o valor de cada limite
      const tracejado = (y, c) => { ctx.setLineDash([5, 4]); ctx.strokeStyle = c; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(x0, y); ctx.lineTo(x1, y); ctx.stroke(); ctx.setLineDash([]); };
      tracejado(Y(zOport), '#2fbf8a'); tracejado(Y(zCara), '#8c99b0');
      if (LPg) { tracejado(Y(LPg.bemAbaixoAte), '#7aa2f7'); tracejado(Y(LPg.mm200), '#f2994a'); }
      const rotulos = [
        { y: Y(zOport) - 9, t: `Oportunidade até ${f(zOport)}`, c: '#2fbf8a' },
        { y: Y(zCara) + 9, t: `Neutro até ${f(zCara)}`, c: '#aab4c6' },
        { y: Y(zCara) - 9, t: `Caro acima de ${f(zCara)}`, c: '#f06a6a' },
        ...(LPg ? [{ y: Y(LPg.bemAbaixoAte) + 9, t: `Bem abaixo de ${f(LPg.bemAbaixoAte)}`, c: '#7aa2f7' }, { y: Y(LPg.mm200) - 9, t: `Média 200d ${f(LPg.mm200)}`, c: '#f2994a' }] : []),
      ];
      if (justoY !== null && modo === 'graham') {
        const yj = Y(justoY);
        ctx.setLineDash([6, 5]); ctx.strokeStyle = '#f2994a'; ctx.lineWidth = 1.2;
        ctx.beginPath(); ctx.moveTo(x0, yj); ctx.lineTo(x1, yj); ctx.stroke(); ctx.setLineDash([]);
        rotulos.push({ y: yj - 9, t: `Média dos métodos: ${d.moeda} ${f(justoY, 0)} - não validado`, c: '#f2994a' });
      }
      // todos à esquerda; de baixo para cima, afasta os que ficariam um em cima do outro
      rotulos.sort((a, b) => b.y - a.y);
      rotulos.forEach((r, k) => { if (k && rotulos[k - 1].y - r.y < 12) r.y = rotulos[k - 1].y - 12; });
      ctx.textAlign = 'left'; ctx.font = '10.5px Inter, system-ui, sans-serif';
      rotulos.forEach(r => { ctx.fillStyle = r.c; ctx.fillText(r.t, r.y > yPlot - 48 ? x0 + 92 : x0 + 6, r.y); });
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

      // mini-legenda das zonas
      if (modo !== 'simons') {
      ctx.textBaseline = 'middle'; ctx.textAlign = 'left'; ctx.font = '10px Inter, system-ui, sans-serif';
      const legL = [['Caro', '#f06a6a'], ['Neutro', '#8c99b0'], ['Oportunidade', '#2fbf8a'], ...(modo === 'lynch' && d.lynch && d.lynch.preco ? [['Bem abaixo', '#7aa2f7']] : [])];
      ctx.fillStyle = '#0e1420cc'; ctx.beginPath(); ctx.roundRect(x0 + 1, yPlot - 7 - legL.length * 12, 84, legL.length * 12 + 6, 7); ctx.fill();
      legL.forEach(([t, c], k) => {
        const y = yPlot - legL.length * 12 + 2 + k * 12; ctx.fillStyle = c; ctx.fillRect(x0 + 6, y - 3, 6, 6);
        ctx.fillStyle = css('--suave'); ctx.fillText(t, x0 + 16, y);
      });
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
      // toque perto da linha laranja: explica de onde ela vem
      if (modo === 'graham' && toque !== null && justoY !== null && Math.abs(toqueY - Y(justoY)) < 16) {
        const l1 = `Média de ${metodosJusto.map(m => `${m[0]} ${f(Math.round(m[1]), 0)}`).join(' e ')}.`;
        const l2 = justoDivergem ? 'Divergência grande, não usar como alvo.' : 'Não validado por teste histórico, não usar como alvo.';
        ctx.font = '600 11px Inter, system-ui, sans-serif'; ctx.textAlign = 'left';
        const tw = Math.max(ctx.measureText(l1).width, ctx.measureText(l2).width) + 18, ty = Math.min(yPlot - 46, Y(justoY) + 8);
        ctx.fillStyle = '#2a1c0cf2'; ctx.strokeStyle = '#f2994a'; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.roundRect(x0 + 4, ty, Math.min(tw, x1 - x0 - 8), 40, 8); ctx.fill(); ctx.stroke();
        ctx.fillStyle = '#ffd9b0'; ctx.fillText(l1, x0 + 13, ty + 13); ctx.fillText(l2, x0 + 13, ty + 28);
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
      trocarFaixa(k); legenda(); animar(); backtest && backtest(k === 'max');
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
    FOLHAS.grafico = () => ['Variação no gráfico', `
      <p>O gráfico mostra só a variação do preço, sem dividendos: último preço do período dividido pelo primeiro, menos 1.</p>
      ${tem(d.preco1AnoAtras) ? `<p><b>Escala 1A</b></p><code>Retorno só preço: (${f(d.preco)} - ${f(d.preco1AnoAtras)}) / ${f(d.preco1AnoAtras)} = ${f((d.preco / d.preco1AnoAtras - 1) * 100)}%</code>
      <p>Preço em ${d.data1AnoAtras}: <b>${din(d.preco1AnoAtras)}</b>. Preço em ${d.data}: <b>${din(d.preco)}</b>.</p>` : ''}
      <p>Na escala "Hoje", a variação é em relação ao fechamento do pregão anterior.</p>
      <p>O retorno com dividendos fica na seção Retorno acumulado.</p>${fonte}`];
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
    const p = posicao(d.preco, fx.min, fx.max), larg = fx.max - fx.min;
    const a = larg > 0 ? (zOport - fx.min) / larg * 100 : 30, b = larg > 0 ? (zCara - fx.min) / larg * 100 : 70;
    const fundo = `linear-gradient(90deg,var(--verde) 0 ${a}%,var(--ardosia) ${a}% ${b}%,var(--ambar) ${b}% 100%)`;
    el.innerHTML = `<h2>Faixa de preço <small>${fx.rotulo}</small></h2>
      <div class="pilha">
        <div class="zona" style="--c:var(--verde)"><span class="rot">Zona de oportunidade</span><b class="num">até ${din(zOport)}</b></div>
        <div class="zona" style="--c:var(--ardosia)"><span class="rot">Zona neutra</span><b class="num">${f(zOport)} a ${f(zCara)}</b></div>
        <div class="zona" style="--c:var(--ambar)"><span class="rot">Zona cara</span><b class="num">acima de ${din(zCara)}</b></div>
        <div class="card">
          <div class="zonas-rot" style="grid-template-columns:${a}fr ${b - a}fr ${100 - b}fr">
            <span style="color:var(--verde)"><b>Oportunidade</b></span>
            <span style="color:#aab4c6"><b>Neutra</b></span>
            <span style="color:var(--ambar)"><b>Cara</b></span>
          </div>
          <div class="marca-cima limites num">
            <span class="esq">${f(fx.min)}</span><span style="left:${a}%">${f(zOport)}</span>
            <span style="left:${b}%">${f(zCara)}</span><span class="dir">${f(fx.max)}</span>
          </div>
          <div class="regua" style="background:${fundo};margin-top:4px">
            <span class="traco" style="left:${a}%"></span><span class="traco" style="left:${b}%"></span>
            <span class="bola" style="left:${p}%"></span>
          </div>
          <div class="marca-baixo num"><span class="aqui-rot" style="${ancora(p)}"><b>${f(d.preco)}</b>Você está aqui</span></div>
          <div class="nota" style="margin-top:6px">Mínima e máxima ${fx.curto === '52 semanas' ? 'das últimas 52 semanas' : fx.curto === 'todo o histórico' ? 'de todo o histórico' : `dos últimos ${fx.curto}`} nas pontas da barra. A faixa acompanha o período do gráfico (1A, 5A ou Máx.).</div>
        </div>
      </div>`;
  }
  renderFaixa();

  /* ---------------- tendência e força */
  (function TrendStrength(el) {
    const corT = { Alta: 'var(--verde)', Baixa: 'var(--vermelho)' }[d.tendencia] || 'var(--texto)';
    const dist = tem(d.mm200) ? (d.preco / d.mm200 - 1) * 100 : null;
    const leitura = !tem(d.forca) ? '' : d.forca >= 70 ? 'Sobrecomprada. Subiu rápido demais, pode corrigir.'
      : d.forca <= 30 ? 'Sobrevendida. Caiu rápido demais, pode repicar.' : 'Neutra. Sem pressão de compra nem de venda.';
    const fundo = 'linear-gradient(90deg,var(--verde) 0 30%,var(--ardosia) 30% 70%,var(--ambar) 70% 100%)';
    // Força da tendência: distância do preço até a média de 200 dias, numa escala de -5% a +15%.
    // O zero (a própria média) fica no início da faixa Fraca: tudo à direita dele está ACIMA da média.
    const FRACA = 3, FORTE = 10;
    const RMIN = tem(dist) && dist < -4 ? Math.floor((dist - 2) / 5) * 5 : -5;
    const RMAX = tem(dist) && dist > 14 ? Math.ceil((dist + 2) / 5) * 5 : 15;
    // Escala por partes: o lado negativo se abre quando a distância passa de -5% (até 40% da barra),
    // e as faixas Fraca, Média e Forte mantêm proporção fixa, para os valores não se sobreporem.
    const W_NEG = RMIN < -5 ? 40 : 25, RESTO = 100 - W_NEG;
    const W_FRACA = RESTO * 0.2, W_MEDIA = RESTO * 0.47, W_FORTE = RESTO - W_FRACA - W_MEDIA;
    const pt = v => v <= 0 ? W_NEG * Math.max(0, v - RMIN) / -RMIN
      : v <= FRACA ? W_NEG + W_FRACA * v / FRACA
      : v <= FORTE ? W_NEG + W_FRACA + W_MEDIA * (v - FRACA) / (FORTE - FRACA)
      : W_NEG + W_FRACA + W_MEDIA + W_FORTE * Math.min(1, (v - FORTE) / (RMAX - FORTE));
    const fundoT = `linear-gradient(90deg,var(--vermelho) 0 ${pt(0)}%,var(--ambar) ${pt(0)}% ${pt(FRACA)}%,var(--ardosia) ${pt(FRACA)}% ${pt(FORTE)}%,var(--verde) ${pt(FORTE)}% 100%)`;
    let textoT = '', ondeT = '';
    if (tem(dist)) {
      const cair = (d.preco - d.mm200) / d.preco * 100, subir = (d.mm200 / d.preco - 1) * 100;
      const grau = dist > FORTE ? 'forte' : dist >= FRACA ? 'média' : 'fraca';
      textoT = dist < 0 ? `Perdeu força. A ${f(Math.abs(dist))}% abaixo da média de 200d. Precisa subir ${f(subir, 1)}% para voltar acima dela.`
        : `Alta ${grau}. A ${f(dist)}% acima da média de 200d. Se cair ${f(cair, 1)}% perde a tendência.`;
      ondeT = `Preço ${f(d.preco)} está ${f(Math.abs(dist))}% ${dist >= 0 ? 'ACIMA' : 'ABAIXO'} da média de 200d de ${f(d.mm200)}`;
    }
    // mesmo desenho da barra de zonas: nomes em cima de cada cor, limites com traço e valor,
    // distância embaixo da bolinha e o valor da média de 200 dias embaixo do traço do 0%
    const pDist = Math.max(0, Math.min(100, pt(dist))), pZero = pt(0);
    const estreita = pt(FRACA) - pt(0) < 11;          // faixa Fraca sem espaço para nome e valor
    const pct = v => `${v > 0 ? '+' : ''}${f(v, 0)}%`;
    // Embaixo da barra: a distância sob a bolinha e o valor da média de 200 dias sob o traço do 0%.
    // Se os dois ficarem perto, cada um se alinha para o seu lado do traço, sem se sobrepor.
    const perto = Math.abs(pDist - pZero) < 22, direita = pDist >= pZero;
    const posDist = !perto ? ancora(pDist) : direita ? `left:${pDist}%;transform:translateX(4px);text-align:left` : `left:${pDist}%;transform:translateX(calc(-100% - 4px));text-align:right`;
    const posMedia = !perto ? ancora(pZero) : direita ? `left:${pZero}%;transform:translateX(calc(-100% - 6px));text-align:right` : `left:${pZero}%;transform:translateX(6px);text-align:left`;
    const media = `<span style="${posMedia};color:var(--suave);font-weight:500;font-size:11px">Média 200d<b style="color:var(--texto)">${f(d.mm200)}</b></span>`;
    const barraT = !tem(dist) ? '' : `<div class="card">
          <span class="rot">Força da tendência</span>
          <div class="zonas-rot" style="grid-template-columns:${pt(0)}fr ${pt(FRACA) - pt(0)}fr ${pt(FORTE) - pt(FRACA)}fr ${100 - pt(FORTE)}fr">
            <span style="color:var(--vermelho)"><b>Perdeu força</b></span>
            <span style="color:var(--ambar);text-align:center"><b>${estreita ? '' : 'Fraca'}</b></span>
            <span style="color:#aab4c6;text-align:center"><b>Média</b></span>
            <span style="color:var(--verde)"><b>Forte</b></span>
          </div>
          <div class="marca-cima limites num">
            <span class="esq">${pct(RMIN)}</span><span style="left:${pt(0)}%">0%</span>${estreita ? '' : `<span style="left:${pt(FRACA)}%">+3%</span>`}
            <span style="left:${pt(FORTE)}%">+10%</span><span class="dir">${pct(RMAX)}</span>
          </div>
          <div class="regua" style="background:${fundoT};margin-top:4px">
            <span class="traco" style="left:${pt(0)}%"></span><span class="traco" style="left:${pt(FRACA)}%"></span><span class="traco" style="left:${pt(FORTE)}%"></span>
            <span class="bola" style="left:${pDist}%"></span>
          </div>
          <div class="marca-baixo num"><span style="${posDist}">${sinal(dist)}</span>${media}</div>
          ${estreita ? '<div class="nota">Faixa Fraca: de 0% a +3% acima da média de 200 dias.</div>' : ''}
          <div class="destaque num">${textoT}</div>
          <div class="nota num">${ondeT}</div>
        </div>`;
    el.innerHTML = `<h2>Tendência e força</h2>
      <div class="pilha">
        <div class="card duas"><div class="esq"><span class="rot">Direção da tendência</span><small>${!tem(d.mm200) ? INDISP : d.tendencia === 'Alta' ? 'preço acima da média de 200 dias' : 'preço abaixo da média de 200 dias'}</small></div><div class="dir" style="color:${corT}">${tem(d.mm200) ? d.tendencia : '—'}</div></div>
        ${barraT}
        <div class="card duas"><div class="esq"><span class="rot">Média de 200 dias</span><small class="num">${tem(dist) ? `preço ${sinal(dist)} da média` : INDISP}</small></div><div class="dir num">${din(d.mm200)}</div></div>
        <div class="card forca">
          <div class="cab"><div><strong>Força</strong><div class="nota">Últimos 14 dias</div></div><button class="link" data-folha="forca">Ver como calculamos</button></div>
          ${tem(d.forca) ? `<div class="zonas-rot" style="grid-template-columns:30fr 40fr 30fr">
            <span style="color:var(--verde)"><b>Muita venda</b></span>
            <span style="color:#aab4c6;text-align:center"><b>Equilíbrio</b></span>
            <span style="color:var(--ambar)"><b>Muita compra</b></span>
          </div>
          <div class="marca-cima limites num">
            <span class="esq">0</span><span style="left:30%">30</span><span style="left:70%">70</span><span class="dir">100</span>
          </div>
          <div class="regua" style="background:${fundo};margin-top:4px">
            <span class="traco" style="left:30%"></span><span class="traco" style="left:70%"></span>
            <span class="bola" style="left:${d.forca}%"></span>
          </div>
          <div class="marca-baixo so-valor num"><span style="${ancora(d.forca)}">${f(d.forca, 0)}</span></div>
          <div class="destaque">${leitura}</div>` : `<div class="nota" style="margin-top:8px">${INDISP}</div>`}
        </div>
      </div>`;
    FOLHAS.forca = () => ['Como calculamos a força', `
      <p>A força é o <b>IFR (RSI) de 14 dias</b>: compara o tamanho das altas com o das quedas nos últimos 14 pregões, numa escala de 0 a 100.</p>
      <ul><li><b>Até 30:</b> sobrevendida (muita venda).</li><li><b>De 30 a 70:</b> neutra (equilíbrio).</li><li><b>Acima de 70:</b> sobrecomprada (muita compra).</li></ul>
      <code>IFR = 100 − 100 ÷ (1 + média das altas ÷ média das quedas)</code>
      ${tem(d.forca) ? `<p>Valor de hoje: <b>${f(d.forca, 0)}</b>.</p>` : ''}
      <p><b>Direção da tendência:</b> Alta com o preço acima da média de 200 dias; Baixa com o preço abaixo.</p>
      <p><b>Força da tendência:</b> distância do preço até a média de 200 dias. Abaixo da média: perdeu força. De 0% a 3% acima: fraca. De 3% a 10%: média. Mais de 10%: forte.</p>
      ${tem(d.mm200) ? `<code>(${f(d.preco)} − ${f(d.mm200)}) ÷ ${f(d.mm200)} = ${sinal((d.preco / d.mm200 - 1) * 100)}</code>` : ''}${fonte}`];
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

  /* ---------------- fundamentos */
  (function Fundamentals(el) {
    const selo = (dif, menorMelhor) => Math.abs(dif) < 5 ? ['neutro', '⚠️ Neutro'] : ((dif < 0) === menorMelhor ? ['bom', '✅ Favorável'] : ['ruim', '❌ Desfavorável']);
    const semDado = ['neutro', INDISP];

    // 1. P/L
    const difPL = tem(d.pl) && tem(d.plMedio12) && d.plMedio12 > 0 ? (d.pl / d.plMedio12 - 1) * 100 : null;
    // preço que a ação teria hoje se o mercado pagasse o P/L médio dos últimos 12 meses pelo lucro atual
    const precoPLMedio = tem(d.plMedio12) && tem(d.lpa) && d.lpa > 0 ? d.plMedio12 * d.lpa : null;
    const prejuizo = tem(d.lpa) && d.lpa <= 0;
    // P/L pelo lucro ajustado: só quando a soma dos 4 trimestres do Yahoo difere 10%+ do LPA contábil
    const lpaAjustado = d.baseLpa === 'últimos 4 trimestres' && tem(d.lpa) && d.lpa > 0 && tem(d.lpaAgora) && d.lpaAgora > 0
      && Math.abs(d.lpaAgora / d.lpa - 1) > 0.10 ? d.lpaAgora : null;
    const plAjustado = tem(lpaAjustado) ? d.preco / lpaAjustado : null;
    const [cPL, tPL] = prejuizo ? ['neutro', 'Sem lucro em 12 meses'] : tem(difPL) ? selo(difPL, true) : semDado;
    // três colunas: contábil (real, muda a cada balanço) | início do ano (1º guidance, congelado) | previsão atual
    const Fp = d.consensoAno || {}, G0 = d.guidance, GI = d.guidanceInicial || {};
    const anoPrev = (G0 && G0.periodo) || (d.lpaAnos && d.lpaAnos.length ? d.lpaAnos[d.lpaAnos.length - 1].ano + 1 : null);
    const lpaCons = tem(Fp.lpa) && Fp.lpa > 0 ? Fp.lpa : null;
    const lpaGuia = G0 && tem(G0.lpa) && G0.lpa > 0 ? G0.lpa : null;
    const lpaPrev = lpaGuia || lpaCons;                      // previsão atual: guidance da empresa ou consenso
    const plPrev = tem(lpaPrev) ? d.preco / lpaPrev : null;
    const lpaIni = tem(GI.lpa) && GI.lpa > 0 ? GI.lpa : null;
    const plIni = tem(lpaIni) ? d.preco / lpaIni : null;
    const fontePrev = lpaGuia ? `GUIDANCE OFICIAL · ${G0.data}` : tem(lpaCons) ? `Consenso Yahoo${tem(Fp.analistas) ? ` · ${f(Fp.analistas, 0)} ${Fp.analistas === 1 ? 'analista' : 'analistas'}` : ''}${tem(Fp.analistas) && Fp.analistas < 3 ? ' · pouco confiável' : ''}` : '';
    const lpaMedioImpl = tem(d.precoMedio12) && tem(d.plMedio12) && d.plMedio12 > 0 ? d.precoMedio12 / d.plMedio12 : null;
    const B = d.balanco;
    const rotBal = B && B.data ? `último balanço divulgado em ${B.data}` : 'último balanço divulgado';
    const faixaG = g => g.porLpa === false ? `lucro de ${din(g.lucroMin / 1e9, 0)} a ${din(g.lucroMax / 1e9, 0)} bi (LPA ${din(g.lpa)})` : `${g.lucroTipo || g.tipo || 'LPA'} de ${din(g.lpaMin)} a ${din(g.lpaMax)}, médio ${din(g.lpa)}`;
    const linhasPL = prejuizo ? ['A empresa teve prejuízo nos últimos 12 meses, então a relação preço/lucro não se aplica.']
      : !tem(d.pl) ? ['O Yahoo Finance não traz o lucro por ação deste ativo.']
      : [
        lpaIni ? `<b>Início do ano ${GI.ano}</b> (congelado): primeiro guidance da empresa para o ano, ${faixaG(GI)}. Fonte: ${GI.fonte}, ${GI.data}. Não muda.`
          : `<b>Início do ano ${GI.ano || anoPrev || ''}</b>: ${GI.status || 'sem projeção inicial encontrada'}.`,
        (() => { const S = d.lpaSec && d.lpaSec.status === 'ok' ? d.lpaSec : null, aj = S && S.base === 'ajustado', ng = S ? S.trimestres_gaap || 0 : 0;
          const nome = aj ? `Contábil Ajustado 12 meses${ng ? ` (${ng} trimestre${ng > 1 ? 's' : ''} GAAP por falta de Ajustado)` : ''}` : 'Contábil 12 meses';
          const conta = S && S.trimestres ? ` Conta: ${S.trimestres.map(t => `${t.fim.slice(3)} ${f(t.lpa)}${t.tipo === 'GAAP' && aj ? ' (GAAP)' : ''}`).join(' + ')} = ${f(d.lpa)}.` : '';
          return `<b>${nome}</b> (${rotBal}): cotação de hoje ÷ lucro por ação dos últimos 12 meses (soma dos 4 últimos trimestres). Muda a cada balanço. Fonte: ${d.lpaFonte || 'Yahoo Finance'}.${conta}${tem(d.acoes) && d.acoes > 0 ? ` Lucro = lucro por ação × ${f(d.acoes / 1e9, 2)} bi de ações (Yahoo).` : ''}`; })(),
        lpaGuia ? `<b>Previsão atual ${anoPrev || ''}</b>: GUIDANCE OFICIAL · ${G0.data}: ${faixaG(G0)}. Fonte: ${G0.fonte}.${G0.bases && G0.bases.length ? ` Base ${G0.bases[0].ano} recalculada pela empresa: ${din(G0.bases[0].valor)}${tem(G0.bases[0].antes) ? ` (antes ${din(G0.bases[0].antes)})` : ''}, ${sinal((lpaGuia / G0.bases[0].valor - 1) * 100, 1)} no guidance.` : ''}${lpaIni ? ` Desde o início do ano: ${sinal((lpaGuia / lpaIni - 1) * 100, 1)}.` : ''}${tem(lpaCons) ? ` Consenso Yahoo: ${din(lpaCons)}.` : ''}`
          : tem(lpaCons) ? `<b>Previsão atual ${anoPrev || ''}</b>: consenso${tem(Fp.analistas) ? ` de ${f(Fp.analistas, 0)} ${Fp.analistas === 1 ? 'analista' : 'analistas'}` : ' dos analistas'} no Yahoo Finance${tem(Fp.baixa) && tem(Fp.alta) ? `, de ${din(Fp.baixa)} a ${din(Fp.alta)}` : ''}${tem(Fp.analistas) && Fp.analistas < 3 ? ' (poucos analistas: pouco confiável)' : ''}. Pode mudar.`
          : `<b>Previsão atual</b>: sem estimativa no Yahoo nem guidance cadastrado.`,
        !tem(difPL) ? '<b>Média 12m</b>: sem histórico para comparar.'
          : `<b>Média 12m</b>: P/L ${f(d.plMedio12)}${tem(lpaMedioImpl) ? ` (lucro/ação ${f(lpaMedioImpl)}, cotação média ${f(d.precoMedio12)})` : ''}, ${d.plMetodo === 'contabil' ? `com o lucro contábil de cada balanço desde ${d.mediaDesde}` : d.plMetodo === 'simplificado' ? 'preço médio do ano ÷ o mesmo lucro contábil' : 'com o lucro de cada balanço'}. O P/L contábil está ${sinal(difPL, 1)} contra a média: ${difPL < -5 ? 'mais barata que no último ano' : difPL > 5 ? 'mais cara que no último ano' : 'perto da média'}.`];
    const frasePL = linhasPL.join('<br>');
    const notaAjustado = tem(plAjustado) ? `Lucro ajustado (Yahoo): LPA ${din(lpaAjustado)}, P/L ${f(plAjustado)}. É a base de alguns sites.` : '';

    // 2. Dividendos
    const dyDif = tem(dy) && tem(d.dyMedio12) && d.dyMedio12 > 0 ? (dy / d.dyMedio12 - 1) * 100 : null;
    const cortou = tem(d.dividendo12Atras) && d.dividendo12Atras > 0 && d.dividendo < d.dividendo12Atras * 0.95;
    let cD, tD, fraseD;
    if (!tem(dy)) { [cD, tD] = semDado; fraseD = 'Sem dados de proventos para este ativo.'; }
    else if (naoPagadora) {
      [cD, tD] = ['neutro', d.dividendo > 0 ? 'Pagadora baixa' : 'Não paga dividendos'];
      fraseD = d.dividendo > 0
        ? `A ${d.ticker} quase não paga dividendo. Ela reinveste quase todo o lucro na própria empresa. Não é um problema, é o perfil da empresa. Ela é para quem busca crescimento, não renda.`
        : `A ${d.ticker} não pagou dividendo nos últimos 12 meses. Não é necessariamente um problema: é o perfil de quem reinveste o lucro. Ela é para quem busca crescimento, não renda.`;
    } else if (!tem(dyDif)) { [cD, tD] = semDado; fraseD = 'Sem histórico suficiente para comparar com a média do último ano.'; }
    else if (dyDif >= 5) { [cD, tD] = ['bom', '✅ Favorável']; fraseD = 'Os dividendos rendem mais sobre o preço de hoje do que na média do último ano.'; }
    else if (dyDif > -5) { [cD, tD] = ['neutro', '⚠️ Neutro']; fraseD = 'O rendimento dos dividendos está perto da média do último ano.'; }
    else if (cortou) { [cD, tD] = ['ruim', '❌ Desfavorável']; fraseD = `A empresa pagou menos dividendo: de ${din(d.dividendo12Atras)} para ${din(d.dividendo)} por ação em 12 meses.`; }
    else { [cD, tD] = ['neutro', '⚠️ Neutro']; fraseD = 'O rendimento caiu porque o preço da ação subiu, não porque o dividendo foi cortado.'; }

    // 3. Lucro
    const trimestral = d.baseLpa === 'últimos 4 trimestres';
    const proximo = trimestral && tem(d.lpa) && tem(d.lpaAgora) && Math.abs(d.lpaAgora / d.lpa - 1) <= 0.03;
    const lpaAtual = proximo ? d.lpa : d.lpaAgora;   // mesmo LPA das outras seções sempre que possível
    const difLPA = tem(lpaAtual) && tem(d.lpa12Atras) && d.lpa12Atras !== 0 ? (lpaAtual - d.lpa12Atras) / Math.abs(d.lpa12Atras) * 100 : null;
    const [cL, tL] = tem(difLPA) ? selo(difLPA, false) : semDado;
    // série trimestral em outra base (ex.: lucro ajustado x contábil): mesma tolerância de 10% do P/L médio
    const outraBase = trimestral && tem(d.lpa) && d.lpa > 0 && tem(d.lpaAgora) && Math.abs(d.lpaAgora / d.lpa - 1) > 0.10;
    const rotL = trimestral ? [outraBase ? 'Atual (ajustado)' : 'Atual', '12m atrás'] : ['Ano fiscal', 'Ano anterior'];
    const notaBase = outraBase ? ` Os dois valores são do lucro por ação trimestral do Yahoo (lucro ajustado), na mesma base, então a comparação vale. O LPA usado no P/L e no Graham é o contábil, ${din(d.lpa)}.` : '';
    const fraseL = !tem(difLPA) ? 'O Yahoo Finance não traz o histórico de lucros deste ativo.'
      : `O lucro por ação ${difLPA >= 0 ? 'cresceu' : 'caiu'} de ${din(d.lpa12Atras)} para ${din(lpaAtual)} ${trimestral ? 'em relação a 12 meses atrás' : 'de um ano fiscal para o outro'}. Base: ${d.baseLpa}.${notaBase}`;

    const exemplo = tem(dy) ? `<div class="exemplo num">Se você investir ${d.moeda} 10.000 hoje, recebe ${din(10000 * d.dividendo / d.preco)} por ano de dividendo.</div>` : '';
    el.innerHTML = `<h2>Fundamentos</h2>
      <details class="acord" open><summary>Fundamentos: os 3 critérios, um a um</summary><div class="dentro">
        <div class="card crit">
          <div class="topo-c"><span class="nome">Preço vs Lucro (P/L)</span><span class="st ${cPL}">${tPL}</span></div>
          <div class="tab-pl num">
            <span></span><div class="cab"><div>Início do ano</div><div class="i">${GI.ano || anoPrev || ''} · congelado</div></div><div class="cab"><div>Contábil</div><div class="i">12 meses · ${d.lpaSec && d.lpaSec.status === 'ok' && d.lpaSec.base === 'ajustado' ? 'ajustado' : 'real'}</div></div><div class="cab"><div>Previsão atual</div><div class="i">${lpaGuia ? 'guidance' : tem(lpaCons) ? 'analistas' : ''}</div></div>
            <span class="rot">P/L</span><b class="gr">${tem(plIni) ? f(plIni) : '—'}</b><b class="gr">${f(d.pl)}</b><b class="gr">${tem(plPrev) ? f(plPrev) : '—'}</b>
            ${tem(d.acoes) && d.acoes > 0 ? (() => { const tot = l => tem(l) ? l * d.acoes : null; const vals = [tot(lpaIni), tot(d.lpa), tot(lpaPrev)]; const ref = Math.max(...vals.filter(tem).map(Math.abs), 0); const [div, un] = ref >= 1e12 ? [1e12, 'tri'] : ref >= 1e9 ? [1e9, 'bi'] : [1e6, 'mi'];
              return `<span class="rot">Lucro<br>${d.moeda} <span class="un">${un}</span></span>${vals.map(v => `<b>${tem(v) ? f(v / div, 1) : '—'}</b>`).join('')}`; })() : ''}
            <span class="rot">Lucro/ação<br>${d.moeda}</span><b>${tem(lpaIni) ? f(lpaIni) : 'Sem dado'}</b><b>${f(d.lpa)}</b><b>${tem(lpaPrev) ? f(lpaPrev) : 'Sem dado'}</b>
            <span class="rot">Cotação<br>${d.moeda}</span><b>${tem(plIni) ? f(d.preco) : '—'}</b><b>${f(d.preco)}</b><b>${tem(plPrev) ? f(d.preco) : '—'}</b>
          </div>
          <p class="linhas-pl">${frasePL}</p>${notaAjustado ? `<div class="nota" style="margin:-4px 0 8px">${notaAjustado}</div>` : ''}
          <button class="link" data-folha="f-pl">Ver como calculamos</button>
        </div>
        <div class="card crit">
          <div class="topo-c"><span class="nome">Dividendos</span><span class="st ${cD}">${tD}</span></div>
          <div class="lista-v num">
            <div>Dividendo por ação / ano<b>${din(d.dividendo)}</b></div>
            <div>DY atual<b>${tem(dy) ? f(dy) + '%' : '—'}</b></div>
            <div>DY média 12m<b>${tem(d.dyMedio12) ? f(d.dyMedio12) + '%' : '—'}</b></div>
            ${d.guidance && tem(d.guidance.dividendo) ? `<div>Projetado (guidance${d.guidance.dividendoFonte === 'empresa' ? ', anual da empresa' : `, payout ${f(d.guidance.payout * 100, 0)}%`})<b>${din(d.guidance.dividendo)} · ${f(d.guidance.dividendo / d.preco * 100, 1)}%</b></div>` : ''}
            <div>Diferença<b>${sinal(dyDif, 0)}</b></div>
          </div>
          ${exemplo}
          <p>${fraseD}</p>
          <button class="link" data-folha="f-dy">Ver como calculamos</button>
        </div>
        <div class="card crit">
          <div class="topo-c"><span class="nome">Crescimento de Lucro (LPA)</span><span class="st ${cL}">${tL}</span></div>
          <div class="vals num"><div><span>${rotL[0]}</span><b>${din(lpaAtual)}</b></div><div><span>${rotL[1]}</span><b>${din(d.lpa12Atras)}</b></div><div><span>Diferença</span><b style="color:${tem(difLPA) ? cor(difLPA) : 'inherit'}">${sinal(difLPA, 0)}</b></div></div>
          <p>${fraseL}</p>
          <button class="link" data-folha="f-lpa">Ver como calculamos</button>
        </div>
      </div></details>`;
    FOLHAS['f-pl'] = () => ['Preço vs Lucro (P/L)', `<p>P/L = Preço ÷ Lucro por ação dos últimos 12 meses (lucro contábil, Yahoo Finance).</p>
      <p>Outros sites podem mostrar outro P/L: alguns usam o lucro ajustado da empresa, outros um período de 12 meses que ainda não inclui o último balanço.</p>
      ${tem(d.pl) ? `<code>${f(d.preco)} ÷ ${f(d.lpa)} = ${f(d.pl)}</code>` : `<p>${INDISP}.</p>`}
      ${tem(plPrev) ? `<p><b>Previsão ${anoPrev || ''}</b> (${fontePrev}):</p><code>${f(d.preco)} ÷ ${f(lpaPrev)} = ${f(plPrev)}</code>` : ''}
      ${tem(lpaMedioImpl) ? `<p><b>Média 12m:</b> preço médio de fechamento do último ano e o lucro por ação que dá o P/L médio.</p><code>${f(d.precoMedio12)} ÷ ${f(d.plMedio12)} = ${f(lpaMedioImpl)}</code>` : ''}
      ${tem(plAjustado) ? `<p>P/L pelo lucro ajustado (soma dos 4 últimos trimestres do Yahoo):</p><code>${f(d.preco)} ÷ ${f(lpaAjustado)} = ${f(plAjustado)}</code><p>Fica só como referência: o selo e a diferença usam o contábil, na mesma base da média de 12 meses.</p>` : ''}
      ${tem(difPL) ? `<p>Diferença para a média de 12 meses:</p><code>(${f(d.pl)} − ${f(d.plMedio12)}) ÷ ${f(d.plMedio12)} = ${sinal(difPL)}</code>` : ''}
      ${tem(precoPLMedio) ? `<p>Preço que a ação teria hoje se valesse o P/L médio de 12 meses, com o lucro atual:</p><code>P/L médio ${f(d.plMedio12)} × LPA ${f(d.lpa)} = ${din(precoPLMedio)}</code><p>Os dois preços mudam todo dia: o de hoje com a cotação, o do P/L médio com o lucro e a média.</p>` : ''}
      <p>${d.plMetodo === 'contabil' ? `A média de 12 meses usa o lucro contábil de 12 meses em vigor em cada pregão, montado com os balanços trimestrais e anuais do Yahoo (lucro líquido ÷ ações; o trimestre mais recente sai do LPA de 12 meses). Período coberto: desde ${d.mediaDesde}.` : d.plMetodo === 'simplificado' ? 'Sem o lucro de cada trimestre na mesma base do LPA atual (o Yahoo pode trazer o trimestral ajustado e o anual contábil), a média de 12 meses é estimada: preço médio do ano ÷ LPA atual. Assim os dois P/L usam o mesmo lucro.' : 'A média de 12 meses usa o P/L de cada pregão, com o lucro já divulgado em cada data.'}</p>${fonte}`];
    FOLHAS['f-dy'] = () => ['Dividendos (DY)', `<p>DY = Dividendo anual por ação ÷ Preço atual.</p>
      ${tem(dy) ? `<code>${f(d.dividendo)} ÷ ${f(d.preco)} = ${f(dy)}%</code>
      <p>Em ${d.moeda} 10.000 investidos:</p><code>10.000 × ${f(d.dividendo)} ÷ ${f(d.preco)} = ${din(10000 * d.dividendo / d.preco)} por ano</code>` : `<p>${INDISP}.</p>`}
      <p>O dividendo anual é a soma dos proventos pagos nos últimos 12 meses. Com DY abaixo de 0,5% a empresa é tratada como não pagadora de dividendos, e o critério não conta contra ela.</p>
      <p>Só marcamos como desfavorável quando a empresa de fato pagou menos dividendo do que nos 12 meses anteriores.</p>${fonte}`];
    FOLHAS['f-lpa'] = () => ['Crescimento de Lucro (LPA)', `<p>LPA = Lucro líquido ÷ Número de ações.</p>
      ${tem(difLPA) ? `<p>Crescimento:</p><code>(${f(lpaAtual)} − ${f(d.lpa12Atras)}) ÷ ${f(Math.abs(d.lpa12Atras))} = ${sinal(difLPA, 0)}</code><p>Base: ${d.baseLpa}.</p>${outraBase ? `<p>${notaBase.trim()}</p>` : ''}` : `<p>${INDISP}.</p>`}${fonte}`];
  })($('fundamentos'));

  /* ---------------- preço justo */
  // aviso do Graham: lucro de 12 meses abaixo de 60% da média de 3 anos
  const avisoGraham = !d.grahamAviso ? ''
    : d.grahamBase === 'atual'
      ? 'Lucro atual 40%+ abaixo da média de 3 anos. Estamos usando o Graham mais conservador (lucro atual). Se usasse a média, o valor seria otimista.'
      : 'Lucro dos últimos 12 meses negativo: o Graham do lucro atual não se aplica e só resta a média de 3 anos, que pode estar otimista.';
  (function FairPrice(el) {
    const m = metodosJusto, t0 = v => f(Math.round(v), 0);
    const linhaGraham = !tem(d.graham) ? '' : `<div class="nota num" style="margin:-4px 0 10px">Graham usa o menor de dois valores: ${tem(d.grahamAtual) ? `lucro de 12 meses ${din(d.grahamAtual)}` : 'lucro de 12 meses não se aplica'} · ${tem(d.grahamMedia) ? `média de 3 anos ${din(d.grahamMedia)}` : 'média de 3 anos não se aplica'}.</div>
          ${avisoGraham ? `<div class="aviso" style="margin:0 0 10px">${avisoGraham}</div>` : ''}`;
    const formulas = () => `
      <p><b>Graham</b>: calculado com dois lucros por ação; vale o <b>menor</b> valor.</p>
      ${tem(d.grahamAtual) ? `<code>Atual: √(22,5 × LPA 12 meses ${f(d.lpa)} × VPA ${f(d.vpa)}) = ${f(d.grahamAtual)}</code>` : `<p>Atual: não se aplica (${tem(d.lpa) && d.lpa <= 0 ? 'lucro dos últimos 12 meses negativo' : 'sem lucro ou patrimônio no Yahoo'}).</p>`}
      ${tem(d.grahamMedia) ? `<code>Média 3 anos: √(22,5 × LPA médio ${f(d.lpaMedio3a)} × VPA ${f(d.vpa)}) = ${f(d.grahamMedia)}</code>` : `<p>Média 3 anos: não se aplica (${d.regra && d.regra.status === 'recorrente' ? 'prejuízo em 2 ou mais dos últimos 3 anos' : 'sem lucro anual no Yahoo'}).</p>`}
      ${tem(d.graham) ? `<p>Usado: <b>${din(d.graham)}</b> (${d.grahamBase === 'media' ? 'média de 3 anos' : 'lucro dos últimos 12 meses'}).</p>` : '<p>Graham não se aplica a este ativo.</p>'}
      ${avisoGraham ? `<p>${avisoGraham}</p>` : ''}
      ${tem(d.justoPL) ? `<p><b>P/L histórico</b></p><code>P/L médio de ${f(d.plHistAnos, 1)} anos ${f(d.plHistorico)} × LPA ${f(d.lpa)} = ${f(d.justoPL)}</code>` : '<p><b>P/L histórico:</b> sem histórico de lucros suficiente no Yahoo Finance.</p>'}
      ${tem(d.bazin) ? `<p><b>Preço-teto Bazin</b></p><code>Dividendo médio 5 anos ${f(d.divMedio5)} / 6% = ${f(d.bazin)}</code>
        <p>O ${din(d.divMedio5)} é a média de até 5 anos, não o dividendo anual (${din(d.dividendo)}).</p>` : ''}
      <p>Quando um método dá mais que o dobro do outro, mostramos a faixa e não um número único.</p>${fonte}`;
    FOLHAS.justo = () => ['Preço justo', formulas()];
    const bazinOculto = naoPagadora && tem(d.bazin) ? `<details class="acord"><summary>Ver todos os métodos</summary><div class="dentro">
        <div class="card"><span class="rot">Preço-Teto Bazin · Não se aplica</span>
          <p class="nota" style="margin:8px 0 10px">A ${d.ticker} quase não paga dividendo, então o preço-teto Bazin de ${din(d.bazin)} não é uma referência válida. Ignoramos esse método para essa ação.</p>
          <div class="nota num" style="margin:0 0 10px">Dividendo médio 5 anos ${f(d.divMedio5)} / 6% = ${f(d.bazin)}</div>
          <button class="link" data-folha="justo">Ver como calculamos</button></div>
      </div></details>` : '';
    if (!m.length) {
      el.innerHTML = `<h2>Preço justo <small>referência</small></h2><div class="pilha">
        <div class="card"><span class="st neutro">Sem preço justo confiável</span>
          <p class="nota" style="margin:10px 0 10px">${INDISP}: nenhum método de preço justo pôde ser calculado com os dados do Yahoo Finance para este ativo.</p>
          <button class="link" data-folha="justo">Ver como calculamos</button></div>${bazinOculto}</div>`;
      return;
    }
    if (m.length === 1) {
      el.innerHTML = `<h2>Preço justo <small>referência</small></h2><div class="pilha">
        <div class="card"><span class="st neutro">Sem preço justo confiável</span>
          <p class="nota" style="margin:10px 0 10px">Só um método pôde ser calculado: ${m[0][0]}, com ${d.moeda} ${t0(m[0][1])}. Um método sozinho não é referência suficiente, então o Fintai não usa preço justo como decisão.</p>
          <button class="link" data-folha="justo">Ver como calculamos</button></div>${bazinOculto}</div>`;
      return;
    }
    const piso = m[0][1], teto = m[m.length - 1][1], divergem = teto / piso > 2;
    const a = piso * 0.6, b = Math.max(teto, d.preco) * 1.12, pos = v => Math.max(0, Math.min(100, (v - a) / (b - a) * 100));
    const dentro = d.preco >= piso && d.preco <= teto;
    const onde = dentro ? `está dentro dessa faixa, mas mais perto do ${d.preco - piso < teto - d.preco ? 'piso' : 'teto'}` : d.preco < piso ? 'está abaixo dessa faixa' : 'está acima dessa faixa';
    el.innerHTML = `<h2>Preço justo <small>referência</small></h2>
      <div class="pilha">
        <div class="card">
          <span class="rot">Faixa justa estimada</span>
          <div class="num" style="font-size:22px;font-weight:700;margin-top:4px">${d.moeda} ${t0(piso)} a ${d.moeda} ${t0(teto)}</div>
          <div class="marca-cima num" style="margin-top:16px">
            <span style="${ancora(pos(piso))};color:var(--suave)">${m[0][0]}<b>${t0(piso)}</b></span>
            <span style="${ancora(pos(teto))};color:var(--suave)">${m[m.length - 1][0]}<b>${t0(teto)}</b></span>
          </div>
          <div class="regua" style="background:var(--ardosia);margin-top:6px">
            ${m.map(x => `<span class="traco" style="left:${pos(x[1])}%"></span>`).join('')}<span class="bola" style="left:${pos(d.preco)}%"></span>
          </div>
          <div class="marca-baixo num"><span style="${ancora(pos(d.preco))}">Hoje<b>${f(d.preco)}</b></span></div>
          ${m.length > 2 ? `<div class="nota">Traços do meio: ${m.slice(1, -1).map(x => `${x[0]} ${t0(x[1])}`).join(', ')}.</div>` : ''}
          <p class="nota" style="margin:12px 0 10px">${m.map(x => `Pelo ${x[0]}, o justo seria ${d.moeda} ${t0(x[1])}.`).join(' ')} O preço atual de ${d.moeda} ${t0(d.preco)} ${onde}.</p>
          ${linhaGraham}
          <button class="link" data-folha="justo">Ver como calculamos</button>
        </div>
        <div class="card">
          <span class="st neutro">${divergem ? 'Sem preço justo confiável' : 'Faixa justa consistente'}</span>
          <p class="nota" style="margin:10px 0 0">${divergem
            ? `Os métodos divergem demais (de ${d.moeda} ${t0(piso)} a ${d.moeda} ${t0(teto)}). Por isso, o Fintai não usa preço justo como decisão. Usamos faixa de preço, tendência e fundamentos.`
            : 'Os métodos apontam para valores próximos, então a faixa serve como referência. Ainda assim, a decisão do Fintai usa faixa de preço, tendência e fundamentos.'}</p>
        </div>
        ${bazinOculto}
      </div>`;
  })($('justo'));

  /* ---------------- indicadores */
  (function Indicators(el) {
    const difPL = tem(d.pl) && tem(d.plMedio12) && d.plMedio12 > 0 ? (d.pl / d.plMedio12 - 1) * 100 : null;
    const q = qtd(d.acoes), por10k = tem(dy) ? din(10000 * d.dividendo / d.preco) : null;
    const medioSub = { trimestral: 'com o LPA de cada trimestre', contabil: 'com o lucro contábil de cada balanço', simplificado: 'preço médio do ano ÷ LPA atual' }[d.plMetodo] || '';
    const c = (rot, v, sub, dica) => [rot, v, sub, dica];
    const cartoes = [
      c('P/L atual', tem(d.pl) ? f(d.pl) : null, tem(difPL) ? `${sinal(difPL)} vs. média de 12m` : '', `Você paga ${din(d.pl)} para cada ${d.moeda} 1 de lucro. Conta: ${f(d.preco)} / ${f(d.lpa)} = ${f(d.pl)}`),
      c('P/L médio 12 meses', tem(d.plMedio12) ? f(d.plMedio12) : null, medioSub, d.plMetodo === 'simplificado' ? 'Estimativa: preço médio do ano dividido pelo LPA atual, porque o Yahoo não traz o lucro de cada trimestre.' : d.plMetodo === 'contabil' ? `Média do P/L de cada pregão desde ${d.mediaDesde}, com o lucro contábil em vigor em cada data.` : 'Média do P/L de cada pregão do último ano, com o lucro já divulgado em cada data.'),
      c('LPA básico', tem(d.lpa) ? din(d.lpa) : null, 'últimos 12 meses', `Lucro por ação. Cada ação ganhou ${din(d.lpa)} em 12 meses.${q ? ` Conta: Lucro / ${q} de ações` : ''}`),
      c('Dividendo anual', tem(d.dividendo) ? din(d.dividendo) : null, 'pago em 12 meses', `O que pingou na sua conta por ação em 12 meses.${por10k ? ` Se investir ${d.moeda} 10.000, recebe ${por10k} / ano.` : ''}`),
      c('Dividend yield', tem(dy) ? `${f(dy)}%` : null, tem(dy) ? `${f(d.dividendo)} / ${f(d.preco)}` : '', `Quanto o dividendo representa sobre o preço. ${f(d.dividendo)} / ${f(d.preco)} = ${f(dy)}%.${naoPagadora ? ` É baixo porque a ${d.ticker} reinveste o lucro, não porque está com problema.` : ''}`),
      c('Ações em circulação', q, 'quantos pedaços a empresa foi dividida', `A ${d.ticker} foi fatiada em ${q} de ações.`),
    ];
    el.innerHTML = `<h2>Indicadores</h2>
      <div class="sub">Dados de ${d.data} · Fonte: ${d.fonte} · <button class="link" data-folha="ind">Ver como calculamos</button></div>
      <div class="grade2">${cartoes.map(([r, v, s, dica]) => v === null
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
      <p><b>Dividendo anual:</b> soma dos proventos pagos nos últimos 12 meses.</p>
      <p>Toque em um cartão para ver a explicação dele.</p>${fonte}`];
  })($('indicadores'));

  /* ---------------- retorno acumulado */
  (function TotalReturn(el) {
    const idx = d.retorno.periodos.map((_, i) => i).filter(i => tem(d.retorno.total[i]));
    if (!idx.length) { el.innerHTML = `<h2>Retorno acumulado</h2><div class="card nota">Histórico curto demais para calcular retornos.</div>`; return; }
    const comDado = k => d.comparadores[k] && d.comparadores[k].v.some(tem);
    // abre no comparador da bolsa da ação; se ele não tiver dado, no primeiro que tiver
    let reinveste = true, dicaAberta = false, per = idx[0],
      comp = comDado(d.comparadorPadrao) ? d.comparadorPadrao : (Object.keys(d.comparadores).find(comDado) || Object.keys(d.comparadores)[0]);
    const virou = (moeda, v) => `${moeda} ${f(Math.round(10000 * (1 + v / 100) / 10) * 10, 0)}`;
    const ult = idx[idx.length - 1], pUlt = d.retorno.periodos[ult];
    function render() {
      const c = d.comparadores[comp], padrao = d.comparadores[d.comparadorPadrao] || c;
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
      const outraMoeda = c.moeda !== d.moeda;
      // mesma conta das linhas do resumo: US$ 10.000 investidos, arredondado à dezena
      const em10k = v => Math.round(10000 * (1 + v / 100) / 10) * 10;
      const difDinheiro = tem(d.retorno.total[0]) && tem(d.retorno.preco[0]) ? em10k(d.retorno.total[0]) - em10k(d.retorno.preco[0]) : 0;

      // a ação primeiro; depois os indicadores do menor para o maior retorno
      const linhasG = [{ nome: d.ticker, v: vals[per], acao: true },
        ...Object.values(d.comparadores).map(o => ({ nome: o.nome, v: o.v[per], fora: o.moeda !== d.moeda, moeda: o.moeda }))
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
          <em>${({ 'S&P 500': 'S&P', 'S&P 500 (sem dividendos)': 'S&P s/div', 'Ibovespa': 'Ibov', 'Poupança': 'Poup.' })[l.nome] || l.nome}${l.fora ? `<small>${l.moeda}</small>` : ''}</em></div>`).join('')}</div>`;
      const temFora = linhasG.some(l => l.fora && tem(l.v));

      // resumo do período contra o comparador da bolsa
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
          ${dicaAberta ? `<span class="dica-q">p.p. = pontos percentuais. É só a conta: ${f(vals[per], 1)}% - ${f(c.v[per], 1)}% = ${f(Math.abs(dif), casas)} pontos. Não é ${f(Math.abs(dif), casas)}%.</span>` : ''}<br>
          Se você tivesse investido ${c.moeda} 10.000: ${d.ticker}${outraMoeda ? ` (em ${d.moeda})` : ''} virou ${virou(d.moeda, vals[per])} | ${c.curto} virou ${virou(c.moeda, c.v[per])}</div>`;
        }
      }

      const t3 = d.retorno.total[1], t5 = d.retorno.total[2];
      const porque = per === 2 && tem(t3) && tem(t5) && t3 > t5
        ? `Por que 3 anos (${ret(t3)}) rendeu mais que 5 anos (${ret(t5)})? Porque entre 5 e 3 anos atrás a ação caiu ${f(Math.abs(((1 + t5 / 100) / (1 + t3 / 100) - 1) * 100), 0)}%. O ganho veio todo nos últimos 3 anos. ` : '';
      el.innerHTML = `<h2>Retorno acumulado</h2><div class="sub">com dividendos, comparado aos indicadores</div>
        <div class="toggle" role="group" aria-label="Reinvestimento de dividendos">
          <button data-r="1" aria-pressed="${reinveste}">Reinvestindo dividendos</button><button data-r="0" aria-pressed="${!reinveste}">Sem reinvestir</button>
        </div>
        <div class="chips periodos" role="group" aria-label="Período">${idx.map(i => `<button data-p="${i}" aria-pressed="${i === per}">${d.retorno.periodos[i]}</button>`).join('')}</div>
        <p class="nota" style="margin:4px 2px 0">${texto}</p>
        <div class="vbarras">${grafico}</div>
        ${(() => { const tx = ['selic', 'cdi'].map(k => d.comparadores[k]).filter(o => o && tem(o.taxaAno)); return tx.length ? `<p class="nota num" style="margin:4px 2px 6px">Taxa de hoje: ${tx.map(o => `${o.nome} ${f(o.taxaAno)}% a.a.`).join(' · ')}. As barras mostram quanto rendeu em ${d.retorno.periodos[per]}.</p>` : ''; })()}
        ${temFora ? `<p class="nota" style="margin:4px 2px 10px">Indicadores marcados em ${Object.values(d.comparadores).find(o => o.moeda !== d.moeda).moeda} estão em outra moeda, sem conversão.</p>` : ''}
        <div class="card resumo num">${resumo}</div>
        ${per === 0 && tem(d.retorno.total[0]) && tem(d.retorno.preco[0]) ? `<p class="nota num" style="margin:12px 2px 0">Em 1 ano: <b>${sinal(d.retorno.preco[0], 2)}</b> só preço e <b>${sinal(d.retorno.total[0], 2)}</b> com dividendos reinvestidos.${difDinheiro > 0 && d.dividendo > 0 ? ` Diferença de ${d.moeda} ${f(difDinheiro, 0)} é o dividendo de ${din(d.dividendo)} recomprado em ações nas datas de pagamento (preço ajustado Yahoo).` : ''}</p>` : ''}
        <p class="nota" style="margin:12px 2px 0">${porque}Retorno passado não garante retorno futuro.</p>
        <p class="nota" style="margin:8px 2px 0">Dados até ${d.data} · <button class="link" data-folha="retorno">Ver como calculamos</button></p>`;
      el.querySelectorAll('[data-r]').forEach(b => { b.onclick = () => { reinveste = b.dataset.r === '1'; render(); }; });
      el.querySelectorAll('[data-p]').forEach(b => { b.onclick = () => { per = +b.dataset.p; render(); }; });
      const q = $('qpp'); if (q) q.onclick = () => { dicaAberta = !dicaAberta; render(); };
    }
    FOLHAS.retorno = () => ['Retorno acumulado', `
      <p><b>Reinvestindo dividendos (Total Return)</b></p><code>(Preço final + Dividendos reinvestidos) ÷ Preço inicial − 1</code>
      <p><b>Sem reinvestir (Price Return)</b></p><code>Preço final ÷ Preço inicial − 1</code>
      ${tem(d.retorno.total[0]) && tem(d.retorno.preco[0]) ? `<p><b>1 ano:</b> ${ret(d.retorno.total[0])} com dividendos e ${ret(d.retorno.preco[0])} só preço. A diferença de ${f(d.retorno.total[0] - d.retorno.preco[0], 2)} ponto vem dos dividendos do período.</p>` : ''}
      <p><b>Diferença em pontos:</b> retorno da ação menos retorno do comparador.</p>
      <p><b>Conta de cada indicador em ${d.retorno.periodos[per]}</b> (para conferir com outros sites, use as mesmas datas):</p>
      <ul class="contas">${Object.values(d.comparadores).map(o => `<li><b>${o.nome}</b>: ${tem(o.v[per]) ? ret(o.v[per]) : INDISP}${o.conta && o.conta[per] ? ` · ${o.conta[per]}` : ''}</li>`).join('')}</ul>
      <p>Nasdaq (Composite, sem dividendos), S&P 500 (com dividendos) e Ibovespa vêm do Yahoo Finance; CDI, Selic, IPCA e Poupança vêm do Banco Central. Cada comparador fica na própria moeda, sem conversão. O IPCA conta os 12, 36 ou 60 meses até o último mês divulgado pelo IBGE (sai com cerca de um mês de atraso).</p>${fonte}`];
    render();
  })($('retorno'));

  /* ---------------- backtest */
  backtest = (function Backtest(el) {
    function render(expandido) {
      const b = d.backtest[expandido ? 'max' : '5a'];
      const sub = expandido ? 'teste com todo o histórico' : 'teste com até 5 anos de histórico';
      if (!b) { el.innerHTML = `<h2>Os sinais funcionaram no passado? <small>${sub}</small></h2><div class="card nota">Histórico curto demais para testar os sinais.</div>`; return; }
      const ref = b.referencia, o = b.oportunidade, c = b.cara;
      const virou = v => `${d.moeda} ${f(10000 * (1 + v / 100), 0)}`;
      const selo = (s, ok) => !s.vezes ? '<span class="selo sem">SEM CASOS</span>' : `<span class="selo ${ok ? 'ok' : 'nao'}">${ok ? 'SINAL VALIDADO ✅' : 'SINAL INVALIDADO ❌'}</span>`;
      const cols = (s, rot) => `<div class="vals num"><div><span>Vezes</span><b>${s.vezes}</b></div><div><span>Retorno 12m</span><b>${sinal(s.retorno, 0)}</b></div><div><span>${rot}</span><b>${tem(s.acerto) ? f(s.acerto, 0) + '%' : '—'}</b></div></div>`;
      const compra = !o.vezes
        ? ['O preço não esteve na Zona de Oportunidade nesse período, então não há casos para validar.', '']
        : [b.compraValidada
            ? (ref.retorno > 0 ? `Comprar na Zona de Oportunidade deu ${f(o.retorno / ref.retorno, 1)}x mais retorno que comprar em uma semana qualquer.`
                               : 'Comprar na Zona de Oportunidade rendeu mais do que comprar em uma semana qualquer.')
            : `Comprar na Zona de Oportunidade não se validou no histórico. NÃO use esse sinal para comprar ${d.ticker}.`,
           `${d.moeda} 10.000 virava ${virou(o.retorno)} em média em 12 meses, quando comprava na Zona de Oportunidade.`];
      const venda = !c.vezes
        ? ['O preço não esteve na Zona Cara nesse período, então não há casos para validar.', '']
        : b.vendaValidada
          ? [`Depois de entrar na Zona Cara, a ação caiu em ${f(c.acerto, 0)}% das vezes. Vender aqui evitou perdas.`,
             `${d.moeda} 10.000 virava ${virou(c.retorno)} em média em 12 meses para quem ficou.`]
          : c.retorno > 0
            ? [`Quem vendeu porque estava na Zona Cara, perdeu alta. NÃO use esse sinal para vender ${d.ticker}.`,
               `Quem comprou mesmo na Zona Cara, ainda ganhou em média ${sinal(c.retorno, 0)} em 12 meses. Vender aqui não evitou queda.`]
            : [`Vender na Zona Cara não se validou no histórico. NÃO use esse sinal para vender ${d.ticker}.`,
               `Depois de entrar na Zona Cara, a ação rendeu em média ${sinal(c.retorno, 0)} em 12 meses.`];
      const periodo = expandido ? 'em todo o histórico' : `nos últimos ${f(Math.min(b.anos, 5), b.insuficiente ? 1 : 0)} anos`;
      const Periodo = periodo.charAt(0).toUpperCase() + periodo.slice(1);
      let resumoBt = '';
      if (o.vezes && c.vezes) {
        if (b.compraValidada && b.vendaValidada) resumoBt = `${Periodo} as duas zonas ajudaram: comprar barato rendeu mais que a média e o preço caiu depois da Zona Cara.`;
        else if (b.compraValidada) resumoBt = `${Periodo} só a Zona de Oportunidade ajudou. Não use a Zona Cara como sinal de venda para ${d.ticker}.`;
        else if (b.vendaValidada) resumoBt = `${Periodo} só a Zona Cara ajudou. Não use a Zona de Oportunidade como sinal de compra para ${d.ticker}.`;
        else if (o.retorno < ref.retorno && c.retorno > ref.retorno) resumoBt = `${Periodo} as zonas não ajudaram: comprar barato rendeu menos que a média e comprar caro rendeu mais. Não use esses sinais para ${d.ticker}.`;
        else resumoBt = `${Periodo} as zonas não se validaram. Não use esses sinais para ${d.ticker}.`;
      }
      el.innerHTML = `<h2>Os sinais funcionaram no passado? <small>${sub}</small></h2>
        ${resumoBt ? `<p class="nota" style="margin:-4px 2px 12px;color:var(--texto)">${resumoBt}</p>` : ''}
        ${expandido ? '<div class="aviso" style="margin-bottom:10px">Backtest expandido para todo o histórico</div>' : ''}
        ${!expandido && b.insuficiente ? `<div class="aviso" style="margin-bottom:10px">Histórico insuficiente para backtest de 5 anos. Mostrando ${f(b.anos, 1)} anos disponíveis.</div>` : ''}
        <div class="pilha">
          <div class="card bt"><div class="cab"><strong>Comprar na Zona de Oportunidade</strong>${selo(o, b.compraValidada)}</div>
            ${cols(o, 'Subiu em')}<p>${compra[0]}</p><p>${compra[1]}</p></div>
          <div class="card bt"><div class="cab"><strong>Preço na Zona Cara</strong>${selo(c, b.vendaValidada)}</div>
            ${cols(c, 'Caiu em')}<p>${venda[0]}</p><p>${venda[1]}</p></div>
        </div>
        <p class="nota" style="margin:12px 2px"><b>Referência:</b> comprar em uma semana qualquer rendeu em média ${sinal(ref.retorno, 0)} em 12 meses (subiu em ${f(ref.subiu, 0)}% das vezes) ${periodo}. Teste com ${f(b.anos, 1)} anos de histórico, semana a semana, usando só os dados disponíveis em cada data. Retornos com dividendos. Resultado passado não garante resultado futuro.${expandido ? ex('backtestMax') : ''}</p>
        <details class="acord"><summary>Como os números são calculados</summary><div class="dentro"><div class="nota">
          <p style="margin:0 0 8px"><b>Janela:</b> ${expandido ? 'todo o histórico disponível' : 'últimos 5 anos'}, semana a semana. Entram as semanas que já têm 12 meses de resultado.</p>
          <p style="margin:0 0 8px"><b>Zona de Oportunidade</b> = até ${din(d.zOport)} hoje (faixa inferior das 52 semanas). <b>Zona Cara</b> = acima de ${din(d.zCara)} hoje (faixa superior). Em cada semana do passado, as faixas são recalculadas só com os dados que existiam até aquela data, sem olhar o futuro.</p>
          <p style="margin:0 0 8px"><b>Retorno 12M</b> = (valor 12 meses depois, com dividendos reinvestidos) ÷ (valor na semana do sinal) − 1.</p>
          <p style="margin:0 0 8px"><b>Sinal validado:</b> acertou em mais de 60% das vezes, rendeu melhor do que a referência (comprar em uma semana qualquer) e teve pelo menos 8 casos.</p>
          <p style="margin:0">Um sinal invalidado nunca entra na decisão do topo da tela.</p>
        </div></div></details>`;
    }
    render(false);
    return render;
  })($('backtest'));

  /* ---------------- bloco de cada modo */
  function renderBloco() {
    const el = $('modo-bloco');
    if (modo === 'graham') {
      const rg = d.regra, anos = d.lpaAnos;
      const linhas = anos.map(a => `<div>${a.ano}<b style="color:${a.lpa < 0 ? 'var(--vermelho)' : 'inherit'}">${din(a.lpa)}</b></div>`).join('');
      const destaque = rg.status === 'ok' ? `Média de ${anos.length} ${anos.length === 1 ? 'ano' : 'anos'}: ${din(rg.media)}`
        : rg.status === 'excluido' ? 'Ano de prejuízo excluído' : rg.status === 'recorrente' ? rg.mensagem : INDISP;
      const nota = rg.status === 'excluido' ? `Média dos anos com lucro: ${din(rg.media)}.`
        : rg.status === 'recorrente' ? 'Dois ou mais anos de prejuízo nos últimos 3 anos.'
        : rg.status === 'ok' ? 'Nenhum ano de prejuízo nos últimos 3 anos.' : 'O Yahoo Finance não traz o lucro anual deste ativo.';
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
      const linhaProj = anoProj ? `<div class="proj"><span>${anoProj} <span class="tag-proj">${G ? 'guidance' : 'projeção'}</span>${ex('lpaEsteAno')}</span><b>${tem(proj) ? din(proj) : 'Sem estimativa'}</b></div>` : '';
      el.innerHTML = `<h2>Lucro por ação <small>últimos 3 anos${anoProj ? ` + projeção ${anoProj}` : ''}</small></h2>
        <div class="card">${G ? `<div style="margin-bottom:10px"><span class="selo ok">GUIDANCE OFICIAL · ${G.data}</span>
          <div class="nota" style="margin-top:6px">Fonte: ${G.url ? `<a class="link" href="${G.url}" target="_blank" rel="noopener" id="g-fonte"></a>` : '<span id="g-fonte"></span>'}</div></div>` : ''}${linhas ? `<div class="lista-v num" style="margin-top:0">${linhas}${linhaProj}</div>` : ''}
          <div class="destaque" style="${rg.status === 'recorrente' ? 'color:var(--vermelho)' : ''}">${destaque}</div>
          <div class="nota" id="g-nota"></div></div>`;
      if (G) { const fz = el.querySelector('#g-fonte'); if (fz) fz.textContent = G.fonte; }
      el.querySelector('#g-nota').textContent = `${nota}${anoProj ? ` ${tem(proj) ? `Projeção ${anoProj}: ${consenso}${tem(varProj) ? `; ${sinal(varProj, 0)} sobre ${anos[anos.length - 1].ano}${G && G.porLpa ? ' (o guidance é LPA ajustado; o ano anterior é o LPA contábil do Yahoo, bases diferentes)' : ''}` : ''}.${divG}${baseG} Não entra na média.${G ? ' O guidance oficial substitui o consenso dos analistas do Yahoo.' : ''}` : `Sem estimativa no Yahoo para ${anoProj}.`}` : ''}`;
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
            ${rg.status === 'recorrente' ? '<div class="destaque" style="color:var(--vermelho)">Sem PEG - Lynch não compra empresa sem lucro</div>' : ''}
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
        <div class="aviso" style="margin-top:10px">PEG do futuro usa estimativa. Se a empresa não entregar esse crescimento, a tese cai.</div>`;
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
        <p class="nota" style="margin:10px 2px 0">Os dias contam desde o maior fechamento dos últimos ${sm.pregoes} pregões, desde que o último pregão tenha sido de queda. Uma alta no meio não quebra a contagem enquanto o preço não passar do topo. O histórico usa a mesma regra nos últimos 5 anos da ação; cada queda conta uma vez em cada linha (a de 10 ou mais só no dia em que chega a 10). Com menos de 20 casos, a porcentagem é pouco confiável. A régua fixa é igual para qualquer ação e ainda não foi testada.</p>`;
    }
  }

  const SECOES = { faixa: ['graham'], tendencia: ['graham', 'lynch', 'simons'], minmax: ['graham', 'simons'],
    fundamentos: ['graham', 'lynch'], justo: ['graham'], indicadores: ['graham', 'lynch'], retorno: ['graham', 'lynch'], backtest: ['graham'] };
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
