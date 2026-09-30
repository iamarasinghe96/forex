export function matches(event, filters) {
  const p = event.payload ?? {};
  return (!filters.pair || String(p.symbol ?? p.candidate?.symbol ?? '').toUpperCase() === filters.pair.toUpperCase())
    && (!filters.timeframe || String(p.timeframe ?? '').toUpperCase() === filters.timeframe.toUpperCase())
    && (!filters.style || String(p.trade_style ?? p.style ?? '').toLowerCase() === filters.style)
    && (!filters.from || event.observed_at_utc.slice(0, 10) >= filters.from)
    && (!filters.through || event.observed_at_utc.slice(0, 10) <= filters.through);
}
export function numeric(value) { return value == null || value === '' || !Number.isFinite(Number(value)) ? null : Number(value); }
export function performance(events) {
  const trades = events.filter(e => e.kind === 'trade_closed').sort((a,b) => a.observed_at_utc.localeCompare(b.observed_at_utc));
  const pnl = trades.map(e => numeric(e.payload.pnl_aud)).filter(v => v !== null);
  const wins = pnl.filter(v => v > 0), losses = pnl.filter(v => v < 0);
  const sum = a => a.reduce((x,y) => x+y,0);
  let streak = 0;
  for (const v of pnl) streak = v === 0 ? 0 : Math.sign(v) === Math.sign(streak) ? streak + Math.sign(v) : Math.sign(v);
  const balances = events.filter(e => e.kind === 'balance' && numeric(e.payload.equity) !== null).sort((a,b) => a.observed_at_utc.localeCompare(b.observed_at_utc));
  let peak = null, drawdown = null;
  for (const e of balances) { const equity = Number(e.payload.equity); peak = Math.max(peak ?? equity,equity); if (peak > 0) drawdown = Math.max(drawdown ?? 0,(peak-equity)/peak*100); }
  return {count:pnl.length,pnl:pnl.length ? sum(pnl) : null,winRate:pnl.length ? wins.length/pnl.length*100 : null,
    profitFactor:losses.length ? sum(wins)/-sum(losses) : null,averageWin:wins.length ? sum(wins)/wins.length : null,
    averageLoss:losses.length ? sum(losses)/losses.length : null,drawdown,streak:pnl.length ? streak : null,balances};
}
export function financialYear(utc) {
  const parts = new Intl.DateTimeFormat('en-AU',{timeZone:'Australia/Sydney',year:'numeric',month:'numeric'}).formatToParts(new Date(utc));
  const year = Number(parts.find(p=>p.type==='year').value), month = Number(parts.find(p=>p.type==='month').value);
  return month >= 7 ? `${year}–${year+1}` : `${year-1}–${year}`;
}
export function reserveYears(events) {
  const years = {};
  for (const e of events.filter(e=>e.kind==='trade_closed')) {
    const year=financialYear(e.observed_at_utc); years[year] ??= {pnl:0,reserve:0,count:0};
    years[year].pnl += numeric(e.payload.pnl_aud) ?? 0; years[year].reserve += numeric(e.payload.reserve_aud) ?? 0; years[year].count++;
  } return years;
}
export function evidenceCSV(events) {
  const cell = v => { let s=String(v??''); if (/^\s*[=+@-]/.test(s)) s="'"+s; return '"'+s.replaceAll('"','""')+'"'; };
  return '\uFEFF'+[['event_id','mode','kind','utc','entity_id','payload_json'],...events.map(e=>[e.event_id,e.mode,e.kind,e.observed_at_utc,e.entity_id,JSON.stringify(e.payload)])].map(row=>row.map(cell).join(',')).join('\r\n');
}
export function stale(timestamp, now=Date.now()) { const age=now-Date.parse(timestamp??''); return !Number.isFinite(age) || age<0 || age>120000; }
