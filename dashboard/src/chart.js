// Price chart of one open trade: hourly price, where the bot entered, its stop-loss and target.
// Pure DOM (no chart library). Text is set with textContent only.
import {chartModel} from './model.js';

const NS = 'http://www.w3.org/2000/svg';
const svgEl = (name, attrs = {}) => {
  const el = document.createElementNS(NS, name);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v));
  return el;
};
const sydney = (seconds, full = true) => new Intl.DateTimeFormat('en-AU', {
  timeZone: 'Australia/Sydney', weekday: 'short', ...(full ? {day: 'numeric', month: 'short', minute: '2-digit'} : {}),
  hour: 'numeric'}).format(new Date(seconds * 1000));

export function renderTradeChart(container, chart, live) {
  // Draw at (about) the displayed width so the text stays readable on a phone.
  const shown = container.clientWidth || container.parentElement?.clientWidth || 640;
  const width = Math.round(Math.max(330, Math.min(760, shown)));
  const narrow = width < 480;
  const m = chartModel(chart, live, {width, height: narrow ? 240 : 270, left: narrow ? 50 : 58, right: narrow ? 112 : 124});
  container.replaceChildren();
  if (!m) {
    container.textContent = 'Price chart appears within the hour (the bot sends it once an hour).';
    return;
  }
  const fmt = v => Number(v).toFixed(m.digits);
  const side = chart.side === 'LONG' ? 'Buy' : 'Sell';
  const wrap = document.createElement('div');
  wrap.className = 'trade-chart';
  const svg = svgEl('svg', {viewBox: `0 0 ${m.width} ${m.height}`, role: 'img',
    'aria-label': `${chart.symbol} ${side}: hourly price from ${sydney(m.bars[0].t)} to ${sydney(m.bars.at(-1).t)}, ` +
      `entry ${fmt(chart.entry)}, stop ${fmt(chart.stop)}${live?.market_price ? `, now ${fmt(live.market_price)}` : ''}.`});
  // Recessive grid and price ticks.
  for (const tick of m.ticks) {
    svg.append(svgEl('line', {x1: m.left, x2: m.left + m.plotW, y1: tick.y, y2: tick.y, class: 'grid'}));
    const label = svgEl('text', {x: m.left - 6, y: tick.y + 4, class: 'axis', 'text-anchor': 'end'});
    label.textContent = fmt(tick.value);
    svg.append(label);
  }
  for (const [i, anchor] of [[0, 'start'], [m.bars.length - 1, 'end']]) {
    const label = svgEl('text', {x: m.points[i][0], y: m.height - 8, class: 'axis', 'text-anchor': anchor});
    label.textContent = sydney(m.bars[i].t, !narrow);
    svg.append(label);
  }
  // Each hour's high-low range (where a stop or target could have been touched), then the closing price.
  for (const [x, top, bottom] of m.wicks) svg.append(svgEl('line', {x1: x, x2: x, y1: top, y2: bottom, class: 'wick'}));
  svg.append(svgEl('polyline', {points: m.points.map(p => p.join(',')).join(' '), class: 'price'}));
  // Reference levels with direct labels (never colour alone: solid stop, dashed target, dotted entry).
  for (const line of m.lines.filter(l => l.kind !== 'now')) {
    svg.append(svgEl('line', {x1: m.left, x2: m.left + m.plotW, y1: line.y, y2: line.y, class: `level ${line.kind}`}));
  }
  for (const line of m.lines) {
    svg.append(svgEl('line', {x1: m.left + m.plotW + 4, x2: m.left + m.plotW + 14, y1: line.y, y2: line.labelY, class: `tick ${line.kind}`}));
    const label = svgEl('text', {x: m.left + m.plotW + 17, y: line.labelY + 4, class: 'level-label'});
    label.textContent = `${line.label} ${fmt(line.value)}`;
    svg.append(label);
  }
  if (m.targetOff) {
    const label = svgEl('text', {x: m.left + 4, y: m.targetOff === 'above' ? m.top + 12 : m.top + m.plotH - 4, class: 'level-label'});
    label.textContent = `Target ${fmt(m.target)} ${m.targetOff === 'above' ? '↑' : '↓'} (off the chart)`;
    svg.append(label);
  }
  if (m.entry) {
    svg.append(svgEl('circle', {cx: m.entry.x, cy: m.entry.y, r: 6, class: 'entry-dot'}));
    const label = svgEl('text', {x: m.entry.x, y: m.entry.y + (chart.side === 'LONG' ? 20 : -12), class: 'marker-label', 'text-anchor': 'middle'});
    label.textContent = m.entry.before ? `${side} (earlier)` : side;
    svg.append(label);
  }
  if (m.now) svg.append(svgEl('circle', {cx: m.now.x, cy: m.now.y, r: 5, class: 'now-dot'}));
  // Hover: a crosshair snaps to the nearest hour and a readout shows that hour's prices.
  const cross = svgEl('line', {y1: m.top, y2: m.top + m.plotH, class: 'cross', visibility: 'hidden'});
  const hit = svgEl('rect', {x: m.left, y: m.top, width: m.plotW, height: m.plotH, class: 'hit'});
  svg.append(cross, hit);
  const tip = document.createElement('div');
  tip.className = 'tip';
  tip.hidden = true;
  const show = event => {
    const box = svg.getBoundingClientRect(), sx = (event.clientX - box.left) / box.width * m.width;
    let i = 0;
    for (let k = 1; k < m.points.length; k++) if (Math.abs(m.points[k][0] - sx) < Math.abs(m.points[i][0] - sx)) i = k;
    const [px] = m.points[i], bar = m.bars[i];
    cross.setAttribute('x1', px); cross.setAttribute('x2', px); cross.setAttribute('visibility', 'visible');
    tip.replaceChildren();
    const value = document.createElement('strong');
    value.textContent = fmt(bar.c);
    const detail = document.createElement('span');
    detail.textContent = ` close · ${sydney(bar.t)} · high ${fmt(bar.h)} · low ${fmt(bar.l)}`;
    tip.append(value, detail);
    tip.hidden = false;
    tip.style.left = `${Math.min(Math.max(px / m.width * 100, narrow ? 30 : 22), narrow ? 70 : 78)}%`;
  };
  hit.addEventListener('pointermove', show);
  hit.addEventListener('pointerdown', show);
  hit.addEventListener('pointerleave', () => { cross.setAttribute('visibility', 'hidden'); tip.hidden = true; });
  wrap.append(svg, tip);
  // Table view of the same numbers.
  const table = document.createElement('details');
  const summary = document.createElement('summary');
  summary.textContent = 'Hourly prices as a table';
  const grid = document.createElement('table');
  const head = grid.createTHead().insertRow();
  for (const name of ['Hour (Sydney)', 'High', 'Low', 'Close']) { const th = document.createElement('th'); th.textContent = name; head.append(th); }
  const body = grid.createTBody();
  for (const bar of [...m.bars].reverse()) {
    const r = body.insertRow();
    for (const value of [sydney(bar.t), fmt(bar.h), fmt(bar.l), fmt(bar.c)]) r.insertCell().textContent = value;
  }
  table.append(summary, grid);
  const key = document.createElement('p');
  key.className = 'chart-key';
  key.textContent = `Blue line: the price at the end of each hour (thin grey bars show each hour's high and low). ` +
    `The dot marks where the bot ${chart.side === 'LONG' ? 'bought' : 'sold'}. Red solid line: the stop-loss - the trade closes there to limit the loss; ` +
    `once the trade is 1R in profit it moves to the entry price and then follows the price (trailing stop). Green dashed line: the profit target.`;
  container.append(wrap, key, table);
}
