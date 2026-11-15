/* Tela de detalhes da ação. Lê tudo de um único pacote de dados (montado em tela/dados.py):
   nenhum número é digitado aqui. Dado ausente vira "Dados indisponíveis". */

const P_OPORTUNIDADE = 30, P_CARO = 70;
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
  const FOLHAS = {};
  const fonte = `<p><b>Fonte:</b> ${d.fonte} · atualizado em ${d.atualizado}.</p>`;
  const zOport = d.min52 + (d.max52 - d.min52) * P_OPORTUNIDADE / 100;
  const zCara = d.min52 + (d.max52 - d.min52) * P_CARO / 100;
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
  (function DecisionCard(el) {
    const e = d.decisao;
    const nome = document.createElement('div'); nome.className = 'razao'; nome.textContent = `${d.razao} · ${d.ticker}`;
    el.innerHTML = `<div class="decisao">
      <div class="meta">Último pregão ${d.data} · ${d.codMoeda} · ${d.fonte}</div>
      <div class="linha"><span class="preco num">${din(d.preco)}</span>
        ${tem(d.varDia) ? `<span class="var num" style="color:${cor(d.varDia)}">${seta(d.varDia)} ${sinal(d.varDia)} no dia</span>` : ''}</div>
      ${d.after ? `<div class="after num" style="color:${cor(d.after.variacao)}">After Market: ${din(d.after.preco)} ${seta(d.after.variacao)} ${sinal(d.after.variacao)}${d.after.hora ? ` | ${d.after.hora}` : ''}</div>` : ''}
      <div><span class="badge ${e.codigo}">${e.rotulo}</span></div>
      <div class="ponto" id="d-texto"></div>
      <span class="pilula">${e.zona}</span>
    </div>`;
    el.firstElementChild.prepend(nome);
    $('d-texto').textContent = e.texto;
  })($('decisao'));

  /* ---------------- gráfico */
  let backtest;
  (function StockChart(el) {
    const ESCALAS = [['hoje', 'Hoje'], ['1s', '1S'], ['1m', '1M'], ['1a', '1A'], ['5a', '5A'], ['max', 'Máx.']];
    const series = d.series;
    let escala = series['1a'] ? '1a' : (ESCALAS.find(([k]) => series[k]) || [null])[0];
    if (!escala) { el.innerHTML = `<div class="aviso">${INDISP}</div>`; return; }
    let velas = false, prog = 1, toque = null, raf = 0;
    const justoY = metodosJusto.length >= 2 ? (metodosJusto[0][1] + metodosJusto[metodosJusto.length - 1][1]) / 2 : null;

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
      const eixoW = 58, x0 = 4, x1 = W - eixoW, yTop = 44, yBase = H - 22, volH = 30, yPlot = yBase - volH - 8;
      const hi = velas ? s.h.map((v, i) => (tem(v) ? v : s.c[i])) : s.c, lo = velas ? s.l.map((v, i) => (tem(v) ? v : s.c[i])) : s.c;
      const vmin = Math.min(...lo), vmax = Math.max(...hi), folga = (vmax - vmin) * 0.04 || 1;
      const Y = v => yPlot - (v - (vmin - folga)) / (vmax - vmin + 2 * folga) * (yPlot - yTop);
      const X = i => x0 + (x1 - x0) * (n === 1 ? 0 : i / (n - 1));
      ctx.font = '11px Inter, system-ui, sans-serif'; ctx.textBaseline = 'middle';

      // zonas ao fundo
      ctx.save(); ctx.beginPath(); ctx.rect(x0, yTop - 6, x1 - x0, yPlot - yTop + 6); ctx.clip();
      ctx.fillStyle = '#2fbf8a1c'; ctx.fillRect(x0, Y(zOport), x1 - x0, 4000);
      ctx.fillStyle = '#f06a6a1a'; ctx.fillRect(x0, Y(zCara) - 4000, x1 - x0, 4000);
      if (justoY !== null) {
        const yj = Y(justoY);
        ctx.setLineDash([6, 5]); ctx.strokeStyle = '#f2994a'; ctx.lineWidth = 1.2;
        ctx.beginPath(); ctx.moveTo(x0, yj); ctx.lineTo(x1, yj); ctx.stroke(); ctx.setLineDash([]);
        ctx.fillStyle = '#f2994a'; ctx.textAlign = 'left'; ctx.fillText('Preço-Justo não validado', x0 + 6, yj - 9);
      }
      ctx.restore();

      // eixo Y
      const yPreco = Y(d.preco);
      ctx.textAlign = 'left';
      for (let k = 0; k < 6; k++) {
        const v = vmin + (vmax - vmin) * k / 5, y = Y(v);
        ctx.strokeStyle = '#26314766'; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(x0, y); ctx.lineTo(x1, y); ctx.stroke();
        if (Math.abs(y - yPreco) > 13) { ctx.fillStyle = css('--suave'); ctx.fillText(f(v), x1 + 7, y); }
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
      [0.06, 0.31, 0.56, 0.81].forEach(fr => {
        const i = Math.round((n - 1) * fr), txt = ROTULO_X[s.rot](new Date(s.t[i]));
        if (txt !== ultimo) ctx.fillText(txt, X(i), H - 5);
        ultimo = txt;
      });

      // mini-legenda das zonas
      ctx.textBaseline = 'middle'; ctx.textAlign = 'left'; ctx.font = '10px Inter, system-ui, sans-serif';
      ctx.fillStyle = '#0e1420cc'; ctx.beginPath(); ctx.roundRect(x0 + 1, yPlot - 43, 84, 42, 7); ctx.fill();
      [['Caro', '#f06a6a'], ['Neutro', '#8c99b0'], ['Oportunidade', '#2fbf8a']].forEach(([t, c], k) => {
        const y = yPlot - 34 + k * 12; ctx.fillStyle = c; ctx.fillRect(x0 + 6, y - 3, 6, 6);
        ctx.fillStyle = css('--suave'); ctx.fillText(t, x0 + 16, y);
      });

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
      legenda(); animar(); backtest && backtest(k === 'max');
    }
    el.querySelectorAll('.e').forEach(b => { b.onclick = () => trocar(b.dataset.e); });
    $('gvela').onclick = e => { velas = !velas; e.currentTarget.setAttribute('aria-pressed', velas); animar(); };
    $('gexp').onclick = () => { $('gbox').classList.toggle('grande'); desenhar(); };
    const mover = e => { toque = e.clientX - cv.getBoundingClientRect().left; desenhar(); };
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
  })($('grafico'));

  /* ---------------- faixa de preço */
  (function PriceRange(el) {
    const p = posicao(d.preco, d.min52, d.max52), larg = d.max52 - d.min52;
    const a = larg > 0 ? (zOport - d.min52) / larg * 100 : 30, b = larg > 0 ? (zCara - d.min52) / larg * 100 : 70;
    const fundo = `linear-gradient(90deg,var(--verde) 0 ${a}%,var(--ardosia) ${a}% ${b}%,var(--ambar) ${b}% 100%)`;
    el.innerHTML = `<h2>Faixa de preço <small>Últimas 52 semanas</small></h2>
      <div class="pilha">
        <div class="zona" style="--c:var(--verde)"><span class="rot">Zona de oportunidade</span><b class="num">até ${din(zOport)}</b></div>
        <div class="zona" style="--c:var(--ardosia)"><span class="rot">Zona neutra</span><b class="num">${f(zOport)} a ${f(zCara)}</b></div>
        <div class="zona" style="--c:var(--ambar)"><span class="rot">Zona cara</span><b class="num">acima de ${din(zCara)}</b></div>
        <div class="card">
          <div class="regua" style="background:${fundo}">
            <span class="aqui" style="left:${Math.min(Math.max(p, 18), 82)}%">VOCÊ ESTÁ AQUI</span><span class="bola" style="left:${p}%"></span>
          </div>
          <div class="pontas num"><span>Mín. 52 sem. ${f(d.min52)}</span><span>Máx. 52 sem. ${f(d.max52)}</span></div>
          <div class="leg num"><span style="--c:var(--verde)">Oportunidade até ${f(zOport)}</span><span style="--c:var(--ardosia)">Neutra</span><span style="--c:var(--ambar)">Cara acima de ${f(zCara)}</span></div>
        </div>
      </div>`;
  })($('faixa'));

  /* ---------------- tendência e força */
  (function TrendStrength(el) {
    const corT = { Alta: 'var(--verde)', Baixa: 'var(--vermelho)' }[d.tendencia] || 'var(--texto)';
    const dist = tem(d.mm200) ? (d.preco / d.mm200 - 1) * 100 : null;
    const leitura = !tem(d.forca) ? '' : d.forca >= 70 ? 'Sobrecomprada. Subiu rápido demais, pode corrigir.'
      : d.forca <= 30 ? 'Sobrevendida. Caiu rápido demais, pode repicar.' : 'Neutra. Sem pressão de compra nem de venda.';
    const fundo = 'linear-gradient(90deg,var(--verde) 0 30%,var(--ardosia) 30% 70%,var(--ambar) 70% 100%)';
    el.innerHTML = `<h2>Tendência e força</h2>
      <div class="pilha">
        <div class="card duas"><div class="esq"><span class="rot">Tendência</span><small>média de 200 dias</small></div><div class="dir" style="color:${corT}">${tem(d.mm200) ? d.tendencia : '—'}</div></div>
        <div class="card duas"><div class="esq"><span class="rot">Média de 200 dias</span><small class="num">${tem(dist) ? `preço ${sinal(dist)} da média` : INDISP}</small></div><div class="dir num">${din(d.mm200)}</div></div>
        <div class="card">
          <div class="cab"><div><strong>Força</strong><div class="nota">Últimos 14 dias</div></div><button class="link" data-folha="forca">Ver como calculamos</button></div>
          ${tem(d.forca) ? `<div class="regua" style="background:${fundo}">
            <span class="balao num" id="fbalao" style="left:${d.forca}%" hidden>${f(d.forca, 0)}</span>
            <button class="bola" id="fbola" style="left:${d.forca}%" aria-label="Mostrar o valor da força" aria-expanded="false"></button>
          </div>
          <div class="pontas tres"><span>Muita venda</span><span>Equilíbrio</span><span>Muita compra</span></div>
          <div class="destaque">${leitura}</div>` : `<div class="nota" style="margin-top:8px">${INDISP}</div>`}
        </div>
      </div>`;
    const bola = $('fbola');
    if (bola) bola.onclick = () => { const b = $('fbalao'); b.hidden = !b.hidden; bola.setAttribute('aria-expanded', !b.hidden); };
    FOLHAS.forca = () => ['Como calculamos a força', `
      <p>A força é o <b>IFR (RSI) de 14 dias</b>: compara o tamanho das altas com o das quedas nos últimos 14 pregões, numa escala de 0 a 100.</p>
      <ul><li><b>Até 30:</b> sobrevendida (muita venda).</li><li><b>De 30 a 70:</b> neutra (equilíbrio).</li><li><b>Acima de 70:</b> sobrecomprada (muita compra).</li></ul>
      <code>IFR = 100 − 100 ÷ (1 + média das altas ÷ média das quedas)</code>
      ${tem(d.forca) ? `<p>Valor de hoje: <b>${f(d.forca, 0)}</b>.</p>` : ''}
      <p><b>Tendência:</b> Alta quando a média de 200 dias sobe e o preço está acima dela; Baixa quando cai e o preço está abaixo; senão Lateral.</p>${fonte}`];
  })($('tendencia'));

  /* ---------------- mínimo, máximo e ponto médio */
  (function MinMaxMidpoint(el) {
    const bloco = (id, titulo, min, max, periodo) => {
      if (!tem(min) || !tem(max)) return `<div class="card"><strong>${titulo}</strong><div class="nota" style="margin-top:6px">${INDISP}</div></div>`;
      const meio = (min + max) / 2, dif = d.preco - meio, p = posicao(d.preco, min, max);
      FOLHAS[id] = () => [`Ponto médio · ${titulo.toLowerCase()}`, `
        <p>O ponto médio é a metade do caminho entre a mínima e a máxima reais do período.</p>
        <code>(${f(min)} + ${f(max)}) ÷ 2 = ${f(meio)}</code>
        <p>Preço agora: <b>${din(d.preco)}</b>, ou <b>${din(Math.abs(dif))} ${dif >= 0 ? 'acima' : 'abaixo'}</b> do ponto médio.</p>${fonte}`];
      return `<div class="card">
        <div class="cab"><strong>${titulo}</strong><button class="link" data-folha="${id}">Ver como calculamos</button></div>
        <div class="trio num"><div><span>Mín.</span><b>${f(min)}</b></div><div><span>Máx.</span><b>${f(max)}</b></div><div><span>Agora</span><b>${f(d.preco)}</b></div></div>
        <div class="nota num" style="margin-top:8px">Ponto médio: <b>${f(meio)}</b></div>
        <div class="regua" style="background:var(--ardosia);margin-top:18px"><span class="traco" style="left:50%"></span><span class="bola" style="left:${p}%"></span></div>
        <div class="leg"><span style="--c:var(--azul)">Preço atual</span><span style="--c:var(--texto)">Ponto médio</span></div>
        <div class="destaque num">Você está ${din(Math.abs(dif))} ${dif >= 0 ? 'acima' : 'abaixo'} do ponto médio</div>
        <div class="nota">Preço na metade mais ${dif >= 0 ? 'cara' : 'barata'} do range de ${periodo}</div>
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
    const prejuizo = tem(d.lpa) && d.lpa <= 0;
    const [cPL, tPL] = prejuizo ? ['neutro', 'Sem lucro em 12 meses'] : tem(difPL) ? selo(difPL, true) : semDado;
    const frasePL = prejuizo ? 'A empresa teve prejuízo nos últimos 12 meses, então a relação preço/lucro não se aplica.'
      : !tem(d.pl) ? 'O Yahoo Finance não traz o lucro por ação deste ativo.'
      : `Você paga ${din(d.pl)} para cada ${d.moeda} 1 de lucro que a empresa gera.` + (!tem(difPL) ? ' Sem histórico de lucros para comparar com a média.'
        : ` Na média dos últimos 12 meses, pagava ${din(d.plMedio12)}. ` + (difPL < -5 ? 'A ação está mais barata em relação ao lucro do que na média do último ano.'
          : difPL > 5 ? 'A ação está mais cara em relação ao lucro do que na média do último ano.' : 'O preço em relação ao lucro está perto da média do último ano.')
          + (d.plMetodo === 'simplificado' ? ' Média estimada pelo preço médio do ano.' : ''));

    // 2. Dividendos
    const dyDif = tem(dy) && tem(d.dyMedio12) && d.dyMedio12 > 0 ? (dy / d.dyMedio12 - 1) * 100 : null;
    const cortou = tem(d.dividendo12Atras) && d.dividendo12Atras > 0 && d.dividendo < d.dividendo12Atras * 0.95;
    let cD, tD, fraseD;
    if (!tem(dy)) { [cD, tD] = semDado; fraseD = 'Sem dados de proventos para este ativo.'; }
    else if (naoPagadora) {
      [cD, tD] = ['neutro', 'Não é pagadora de dividendos'];
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
    const rotL = trimestral ? ['Atual', '12m atrás'] : ['Ano fiscal', 'Ano anterior'];
    const fraseL = !tem(difLPA) ? 'O Yahoo Finance não traz o histórico de lucros deste ativo.'
      : `O lucro por ação ${difLPA >= 0 ? 'cresceu' : 'caiu'} de ${din(d.lpa12Atras)} para ${din(lpaAtual)} ${trimestral ? 'em relação a 12 meses atrás' : 'de um ano fiscal para o outro'}. Base: ${d.baseLpa}.`;

    const exemplo = tem(dy) ? `<div class="exemplo num">Se você investir ${d.moeda} 10.000 hoje, recebe ${din(10000 * d.dividendo / d.preco)} por ano de dividendo.</div>` : '';
    el.innerHTML = `<h2>Fundamentos</h2>
      <details class="acord" open><summary>Fundamentos: os 3 critérios, um a um</summary><div class="dentro">
        <div class="card crit">
          <div class="topo-c"><span class="nome">Preço vs Lucro (P/L)</span><span class="st ${cPL}">${tPL}</span></div>
          <div class="vals num"><div><span>Atual</span><b>${f(d.pl)}</b></div><div><span>Média 12m</span><b>${f(d.plMedio12)}</b></div><div><span>Diferença</span><b style="color:${tem(difPL) ? (difPL < 0 ? 'var(--verde)' : 'var(--vermelho)') : 'inherit'}">${sinal(difPL)}</b></div></div>
          <p>${frasePL}</p>
          <button class="link" data-folha="f-pl">Ver como calculamos</button>
        </div>
        <div class="card crit">
          <div class="topo-c"><span class="nome">Dividendos</span><span class="st ${cD}">${tD}</span></div>
          <div class="lista-v num">
            <div>Dividendo por ação / ano<b>${din(d.dividendo)}</b></div>
            <div>DY atual<b>${tem(dy) ? f(dy) + '%' : '—'}</b></div>
            <div>DY média 12m<b>${tem(d.dyMedio12) ? f(d.dyMedio12) + '%' : '—'}</b></div>
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
    FOLHAS['f-pl'] = () => ['Preço vs Lucro (P/L)', `<p>P/L = Preço ÷ Lucro por ação.</p>
      ${tem(d.pl) ? `<code>${f(d.preco)} ÷ ${f(d.lpa)} = ${f(d.pl)}</code>` : `<p>${INDISP}.</p>`}
      ${tem(difPL) ? `<p>Diferença para a média de 12 meses:</p><code>(${f(d.pl)} − ${f(d.plMedio12)}) ÷ ${f(d.plMedio12)} = ${sinal(difPL)}</code>` : ''}
      <p>${d.plMetodo === 'simplificado' ? 'Sem o lucro de cada trimestre no Yahoo, a média de 12 meses é estimada: preço médio do ano ÷ LPA atual.' : 'A média de 12 meses usa o P/L de cada pregão, com o lucro já divulgado em cada data.'}</p>${fonte}`];
    FOLHAS['f-dy'] = () => ['Dividendos (DY)', `<p>DY = Dividendo anual por ação ÷ Preço atual.</p>
      ${tem(dy) ? `<code>${f(d.dividendo)} ÷ ${f(d.preco)} = ${f(dy)}%</code>
      <p>Em ${d.moeda} 10.000 investidos:</p><code>10.000 × ${f(d.dividendo)} ÷ ${f(d.preco)} = ${din(10000 * d.dividendo / d.preco)} por ano</code>` : `<p>${INDISP}.</p>`}
      <p>O dividendo anual é a soma dos proventos pagos nos últimos 12 meses. Com DY abaixo de 0,5% a empresa é tratada como não pagadora de dividendos, e o critério não conta contra ela.</p>
      <p>Só marcamos como desfavorável quando a empresa de fato pagou menos dividendo do que nos 12 meses anteriores.</p>${fonte}`];
    FOLHAS['f-lpa'] = () => ['Crescimento de Lucro (LPA)', `<p>LPA = Lucro líquido ÷ Número de ações.</p>
      ${tem(difLPA) ? `<p>Crescimento:</p><code>(${f(lpaAtual)} − ${f(d.lpa12Atras)}) ÷ ${f(Math.abs(d.lpa12Atras))} = ${sinal(difLPA, 0)}</code><p>Base: ${d.baseLpa}.</p>` : `<p>${INDISP}.</p>`}${fonte}`];
  })($('fundamentos'));

  /* ---------------- preço justo */
  (function FairPrice(el) {
    const m = metodosJusto, t0 = v => f(Math.round(v), 0);
    const formulas = () => `
      ${tem(d.graham) ? `<p><b>Graham</b></p><code>√(22,5 × LPA ${f(d.lpa)} × VPA ${f(d.vpa)}) = ${f(d.graham)}</code>` : '<p><b>Graham:</b> não se aplica (exige lucro e patrimônio positivos).</p>'}
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
          <div class="regua" style="background:var(--ardosia);margin-top:22px">
            ${m.map(x => `<span class="traco" style="left:${pos(x[1])}%"></span>`).join('')}<span class="bola" style="left:${pos(d.preco)}%"></span>
          </div>
          <div class="leg num">${m.map(x => `<span style="--c:var(--texto)">${x[0]} ${t0(x[1])}</span>`).join('')}<span style="--c:var(--azul)">Preço ${t0(d.preco)}</span></div>
          <p class="nota" style="margin:12px 0 10px">${m.map(x => `Pelo ${x[0]}, o justo seria ${d.moeda} ${t0(x[1])}.`).join(' ')} O preço atual de ${d.moeda} ${t0(d.preco)} ${onde}.</p>
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
    const medioSub = { trimestral: 'com o LPA de cada trimestre', simplificado: 'preço médio do ano ÷ LPA atual' }[d.plMetodo] || '';
    const c = (rot, v, sub, dica) => [rot, v, sub, dica];
    const cartoes = [
      c('P/L atual', tem(d.pl) ? f(d.pl) : null, tem(difPL) ? `${sinal(difPL)} vs. média de 12m` : '', `Você paga ${din(d.pl)} para cada ${d.moeda} 1 de lucro. Conta: ${f(d.preco)} / ${f(d.lpa)} = ${f(d.pl)}`),
      c('P/L médio 12 meses', tem(d.plMedio12) ? f(d.plMedio12) : null, medioSub, d.plMetodo === 'simplificado' ? 'Estimativa: preço médio do ano dividido pelo LPA atual, porque o Yahoo não traz o lucro de cada trimestre.' : 'Média do P/L de cada pregão do último ano, com o lucro já divulgado em cada data.'),
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
    let reinveste = true, comp = d.comparadores[d.comparadorPadrao] ? d.comparadorPadrao : Object.keys(d.comparadores)[0], dicaAberta = false;
    const virou = (moeda, v) => `${moeda} ${f(Math.round(10000 * (1 + v / 100) / 10) * 10, 0)}`;
    const ult = idx[idx.length - 1], pUlt = d.retorno.periodos[ult];
    function render() {
      const c = d.comparadores[comp], padrao = d.comparadores[d.comparadorPadrao] || c;
      const vals = reinveste ? d.retorno.total : d.retorno.preco;
      const dif5 = tem(d.retorno.preco[ult]) ? d.retorno.total[ult] - d.retorno.preco[ult] : null;
      let texto;
      if (reinveste) texto = !tem(dif5) ? 'Retorno com os dividendos reinvestidos em mais ações.'
        : dif5 < 1 ? `Quase nenhuma diferença. A ${d.ticker} pagou ${din(d.dividendo)} por ação nos últimos 12 meses. Reinvestir ou não muda ${f(Math.max(dif5, 0), 1)} ponto no seu retorno em ${pUlt}.`
        : `${dif5 >= 10 ? 'Grande diferença' : 'Faz diferença'}. Reinvestir os dividendos faz seu retorno subir de ${ret(d.retorno.preco[ult])} para ${ret(d.retorno.total[ult])} em ${pUlt}, porque você compra mais ações com o dividendo.`;
      else texto = (tem(d.dividendos5Anos) ? `Você recebeu ${din(d.dividendos5Anos)} em 5 anos por ação em dividendos, em dinheiro, e não recomprou.` : 'Você recebeu o dividendo em dinheiro e não recomprou.')
        + (tem(dif5) && dif5 >= 10 ? ' Perdeu o efeito bola de neve.' : '');
      const outraMoeda = c.moeda !== d.moeda;

      // escala das barras (aceita retornos negativos)
      const todos = idx.flatMap(i => [vals[i], c.v[i]]).filter(tem);
      let hi = Math.max(0, ...todos), lo = Math.min(0, ...todos);
      const passo = passoBonito(Math.max(hi - lo, 1) / 5);
      hi = Math.max(passo, Math.ceil(hi / passo) * passo); lo = Math.floor(lo / passo) * passo;
      const alt = v => Math.abs(v) / (hi - lo) * 100, pe = v => (Math.min(0, v) - lo) / (hi - lo) * 100;
      const marcas = []; for (let v = lo; v <= hi + 1e-9; v += passo) marcas.push(v);
      const barra = (v, cls) => !tem(v) ? '' : `<div class="b ${cls} ${v < 0 ? 'neg' : ''}" style="bottom:${pe(v)}%;height:${Math.max(alt(v), 1.2)}%"><i class="num">${ret(v)}</i></div>`;

      const linhas = idx.map((i, k) => {
        const p = d.retorno.periodos[i];
        if (!tem(vals[i])) return `<div><b>Retorno acumulado: ${INDISP} em ${p}</b></div>`;
        const cab = `<b>Retorno acumulado: ${ret(vals[i])} em ${p}</b>${reinveste ? '' : ' (só preço)'}`;
        if (!tem(c.v[i])) return `<div>${cab}<br>${c.nome}: ${INDISP}</div>`;
        const dif = vals[i] - c.v[i], casas = Math.abs(dif) >= 100 ? 0 : 1;
        return `<div>${cab}<br>
          ${c.nome}: ${ret(c.v[i])} em ${p} | Diferença: <span class="dif ${dif < 0 ? 'neg' : ''}">${dif >= 0 ? '+' : '-'}${f(Math.abs(dif), casas)} pontos ${dif >= 0 ? 'acima' : 'abaixo'} ${c.artigo}</span>${k === 0 ? '<button class="q" id="qpp" aria-label="O que são pontos percentuais?">?</button>' : ''}
          ${k === 0 && dicaAberta ? `<span class="dica-q">p.p. = pontos percentuais. É só a conta: ${f(vals[i], 1)}% - ${f(c.v[i], 1)}% = ${f(Math.abs(dif), casas)} pontos. Não é ${f(Math.abs(dif), casas)}%.</span>` : ''}<br>
          Se você tivesse investido ${c.moeda} 10.000: ${d.ticker}${outraMoeda ? ` (em ${d.moeda})` : ''} virou ${virou(d.moeda, vals[i])} | ${c.curto} virou ${virou(c.moeda, c.v[i])}</div>`;
      }).join('');

      const t3 = d.retorno.total[1], t5 = d.retorno.total[2];
      const porque = tem(t3) && tem(t5) && t3 > t5
        ? `Por que 3 anos (${ret(t3)}) rendeu mais que 5 anos (${ret(t5)})? Porque entre 5 e 3 anos atrás a ação caiu ${f(Math.abs(((1 + t5 / 100) / (1 + t3 / 100) - 1) * 100), 0)}%. O ganho veio todo nos últimos 3 anos. ` : '';
      el.innerHTML = `<h2>Retorno acumulado</h2><div class="sub">com dividendos, comparado ao índice</div>
        <div class="toggle" role="group" aria-label="Reinvestimento de dividendos">
          <button data-r="1" aria-pressed="${reinveste}">Reinvestindo dividendos</button><button data-r="0" aria-pressed="${!reinveste}">Sem reinvestir</button>
        </div>
        <p class="nota" style="margin:10px 2px 0">${texto}</p>
        <div class="chips" role="group" aria-label="Comparador">${Object.entries(d.comparadores).map(([k, o]) => `<button data-c="${k}" aria-pressed="${k === comp}">${o.nome}</button>`).join('')}</div>
        <div class="barras">
          <div class="grade-y">${marcas.map(v => `<div style="bottom:${(v - lo) / (hi - lo) * 100}%"><span>${f(v, 0)}%</span></div>`).join('')}<div class="zero" style="bottom:${(0 - lo) / (hi - lo) * 100}%"></div></div>
          <div class="cols">${idx.map(i => `<div class="col">${barra(vals[i], 'acao')}${barra(c.v[i], 'idx')}<em>${d.retorno.periodos[i]}</em></div>`).join('')}</div>
        </div>
        <div class="leg" style="margin:8px 0 12px"><span style="--c:var(--verde)">${d.ticker}</span><span style="--c:var(--ardosia)">${c.nome}</span></div>
        ${outraMoeda ? `<div class="aviso" style="margin-bottom:10px">Comparação com ${c.nome} é em moedas diferentes (${d.moeda} e ${c.moeda}). Para comparar certo, converta a moeda ou use o comparador ${padrao.nome}.</div>` : ''}
        <div class="card resumo num">${linhas}</div>
        <p class="nota" style="margin:12px 2px 0">${porque}Retorno passado não garante retorno futuro.</p>
        <p class="nota" style="margin:8px 2px 0">Dados até ${d.data} · <button class="link" data-folha="retorno">Ver como calculamos</button></p>`;
      el.querySelectorAll('[data-r]').forEach(b => { b.onclick = () => { reinveste = b.dataset.r === '1'; render(); }; });
      el.querySelectorAll('[data-c]').forEach(b => { b.onclick = () => { comp = b.dataset.c; render(); const a = el.querySelector(`[data-c="${comp}"]`); a && a.scrollIntoView({ block: 'nearest', inline: 'center' }); }; });
      const q = $('qpp'); if (q) q.onclick = () => { dicaAberta = !dicaAberta; render(); };
    }
    FOLHAS.retorno = () => ['Retorno acumulado', `
      <p><b>Reinvestindo dividendos (Total Return)</b></p><code>(Preço final + Dividendos reinvestidos) ÷ Preço inicial − 1</code>
      <p><b>Sem reinvestir (Price Return)</b></p><code>Preço final ÷ Preço inicial − 1</code>
      ${tem(d.retorno.total[0]) && tem(d.retorno.preco[0]) ? `<p><b>1 ano:</b> ${ret(d.retorno.total[0])} com dividendos e ${ret(d.retorno.preco[0])} só preço. A diferença de ${f(d.retorno.total[0] - d.retorno.preco[0], 2)} ponto vem dos dividendos do período.</p>` : ''}
      <p><b>Diferença em pontos:</b> retorno da ação menos retorno do comparador.</p>
      <p>S&P 500 e Ibovespa vêm do Yahoo Finance; CDI, Selic, IPCA e Poupança vêm do Banco Central. Cada comparador fica na própria moeda, sem conversão.</p>${fonte}`];
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
      el.innerHTML = `<h2>Os sinais funcionaram no passado? <small>${sub}</small></h2>
        ${expandido ? '<div class="aviso" style="margin-bottom:10px">Backtest expandido para todo o histórico</div>' : ''}
        ${!expandido && b.insuficiente ? `<div class="aviso" style="margin-bottom:10px">Histórico insuficiente para backtest de 5 anos. Mostrando ${f(b.anos, 1)} anos disponíveis.</div>` : ''}
        <div class="pilha">
          <div class="card bt"><div class="cab"><strong>Comprar na Zona de Oportunidade</strong>${selo(o, b.compraValidada)}</div>
            ${cols(o, 'Subiu em')}<p>${compra[0]}</p><p>${compra[1]}</p></div>
          <div class="card bt"><div class="cab"><strong>Preço na Zona Cara</strong>${selo(c, b.vendaValidada)}</div>
            ${cols(c, 'Caiu em')}<p>${venda[0]}</p><p>${venda[1]}</p></div>
        </div>
        <p class="nota" style="margin:12px 2px"><b>Referência:</b> comprar em uma semana qualquer rendeu em média ${sinal(ref.retorno, 0)} em 12 meses (subiu em ${f(ref.subiu, 0)}% das vezes) ${periodo}. Teste com ${f(b.anos, 1)} anos de histórico, semana a semana, usando só os dados disponíveis em cada data. Retornos com dividendos. Resultado passado não garante resultado futuro.</p>
        <details class="acord"><summary>Como os números são calculados</summary><div class="dentro"><div class="nota">
          <p style="margin:0 0 8px"><b>Janela:</b> ${expandido ? 'todo o histórico disponível' : 'últimos 5 anos'}, semana a semana. Entram as semanas que já têm 12 meses de resultado.</p>
          <p style="margin:0 0 8px"><b>Zona de Oportunidade</b> = até ${din(zOport)} hoje (faixa inferior das 52 semanas). <b>Zona Cara</b> = acima de ${din(zCara)} hoje (faixa superior). Em cada semana do passado, as faixas são recalculadas só com os dados que existiam até aquela data, sem olhar o futuro.</p>
          <p style="margin:0 0 8px"><b>Retorno 12M</b> = (valor 12 meses depois, com dividendos reinvestidos) ÷ (valor na semana do sinal) − 1.</p>
          <p style="margin:0 0 8px"><b>Sinal validado:</b> acertou em mais de 60% das vezes, rendeu melhor do que a referência (comprar em uma semana qualquer) e teve pelo menos 8 casos.</p>
          <p style="margin:0">Um sinal invalidado nunca entra na decisão do topo da tela.</p>
        </div></div></details>`;
    }
    render(false);
    return render;
  })($('backtest'));

  return () => limpar.forEach(fn => fn());
}

export default function (component) {
  const { data, parentElement } = component;
  if (!data || !data.dados) return;
  if (parentElement.__fintaiLimpar) { try { parentElement.__fintaiLimpar(); } catch (e) { /* já desmontado */ } }
  parentElement.__fintaiLimpar = montar(parentElement, data.dados);
  return parentElement.__fintaiLimpar;
}
