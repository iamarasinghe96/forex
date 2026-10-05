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
export const PERIODS=[['1','Last 24 hours'],['7','Last 7 days'],['14','Last 2 weeks'],['30','Last 30 days'],['90','Last 3 months'],['all','All time']];
export function periodStart(period,now=Date.now()){return period==='all'?null:now-Number(period)*86400000;}
const closedAt=e=>Date.parse(e.payload?.closed_at_utc??e.observed_at_utc);
export function simpleSummary(trades,summary,period,now=Date.now()){
  const period0=periodStart(period,now),accountStart=Date.parse(summary?.first_event_at_utc??'');
  // Trades mirrored from an earlier paper account (before this journal began) are not counted.
  const start=Number.isFinite(accountStart)?Math.max(period0??accountStart,accountStart):period0;
  const closed=trades.filter(e=>e.kind==='trade_closed'&&numeric(e.payload?.pnl_aud)!==null&&Number.isFinite(closedAt(e))&&closedAt(e)<=now&&(start===null||closedAt(e)>=start)).sort((a,b)=>closedAt(a)-closedAt(b));
  const pnl=closed.map(e=>Number(e.payload.pnl_aud)),profit=pnl.reduce((a,b)=>a+b,0);
  const balance=numeric(summary?.latest_balance),allTime=numeric(summary?.realized_pnl_aud)??0;
  // Every balance change comes from a closed trade, so the starting (invested) amount is balance minus all-time P&L.
  const invested=balance===null?null:balance-allTime;
  return {invested,balance,profit,profitPercent:invested?profit/invested*100:null,trades:closed.length,
    won:pnl.filter(v=>v>0).length,lost:pnl.filter(v=>v<0).length,from:start,to:now,recent:closed.slice(-10).reverse()};
}
export function botState(summary,now=Date.now()){
  const at=Date.parse(summary?.health_at_utc??'');
  if(!Number.isFinite(at))return {running:false,label:'No updates received yet'};
  const minutes=Math.max(0,Math.round((now-at)/60000));
  if(now-at<=180000)return {running:true,label:summary.latest_health?.status==='HALTED'?'Paused (halt switch on)':'Running'};
  return {running:false,label:`No update for ${minutes<120?minutes+' min':Math.round(minutes/60)+' h'} — normal while the market is closed at weekends, otherwise check the VPS`};
}

// ---------------------------------------------------------------- open trades and their charts
export function openTrades(summary){return Array.isArray(summary?.latest_health?.positions)?summary.latest_health.positions:[];}
export function openPnl(summary){
  // Profit or loss of all open trades if they were closed at the latest price (null if any is unknown).
  let total=0;for(const p of openTrades(summary)){const v=numeric(p.unrealized_pnl_aud);if(v===null)return null;total+=v;}return total;
}
export function priceDigits(symbol){return /JPY/i.test(String(symbol??''))?3:5;}
export function spreadLabels(items,gap,minY,maxY){
  // Keep right-edge labels at least `gap` apart without leaving the plot (input: [{y,...}]).
  const out=[...items].sort((a,b)=>a.y-b.y).map(i=>({...i,labelY:Math.max(minY,i.y)}));
  for(let i=1;i<out.length;i++)out[i].labelY=Math.max(out[i].labelY,out[i-1].labelY+gap);
  for(let i=out.length-1;i>=0;i--){const limit=i===out.length-1?maxY:out[i+1].labelY-gap;out[i].labelY=Math.min(out[i].labelY,limit);}
  return out;
}
export function chartModel(chart,live,{width=640,height=260,left=58,right=118,top=34,bottom=30}={}){
  const b=chart?.bars,n=b?.t?.length??0;
  if(!n)return null;
  const t=b.t.map(Number),h=b.h.map(Number),l=b.l.map(Number),c=b.c.map(Number);
  const entry=numeric(chart.entry),stop=numeric(chart.stop),first=numeric(chart.initial_stop),target=numeric(chart.target),now=numeric(live?.market_price);
  const must=[...h,...l,entry,stop,first,now].filter(v=>v!==null&&Number.isFinite(v));
  let lo=Math.min(...must),hi=Math.max(...must);
  // The 10R target is usually far away; only draw it when it fits without flattening the price line.
  const span=hi-lo||Math.abs(entry??1)*0.001,reach=span*0.75;let targetOff=null;
  if(target!==null){if(target>hi+reach)targetOff='above';else if(target<lo-reach)targetOff='below';else{lo=Math.min(lo,target);hi=Math.max(hi,target);}}
  const pad=(hi-lo)*0.08||span*0.08;lo-=pad;hi+=pad;
  const plotW=width-left-right,plotH=height-top-bottom,t0=t[0],tN=t.at(-1);
  const x=s=>left+(tN>t0?(s-t0)/(tN-t0):1)*plotW,y=v=>top+(hi-v)/(hi-lo)*plotH;
  const opened=Date.parse(chart.opened_at_utc??'')/1000;
  const entryX=Number.isFinite(opened)?x(Math.min(Math.max(opened,t0),tN)):null;
  const lines=[];
  if(target!==null&&!targetOff)lines.push({kind:'target',value:target,y:y(target),label:'Target'});
  if(entry!==null)lines.push({kind:'entry',value:entry,y:y(entry),label:'Entry'});
  if(stop!==null)lines.push({kind:'stop',value:stop,y:y(stop),label:first!==null&&Math.abs(first-stop)>1e-12?'Stop now':'Stop'});
  if(first!==null&&stop!==null&&Math.abs(first-stop)>1e-12)lines.push({kind:'first-stop',value:first,y:y(first),label:'First stop'});
  if(now!==null)lines.push({kind:'now',value:now,y:y(now),label:'Now'});
  const ticks=[0,1,2,3].map(i=>lo+pad+(hi-lo-2*pad)*i/3);
  return {width,height,left,right,top,bottom,plotW,plotH,
    points:t.map((s,i)=>[x(s),y(c[i])]),wicks:t.map((s,i)=>[x(s),y(h[i]),y(l[i])]),
    bars:t.map((s,i)=>({t:s,h:h[i],l:l[i],c:c[i]})),
    lines:spreadLabels(lines,15,top+6,top+plotH),entry:entryX===null||entry===null?null:{x:entryX,y:y(entry),before:opened<t0},
    now:now===null?null:{x:left+plotW,y:y(now),value:now},targetOff,target,
    ticks:ticks.map(v=>({value:v,y:y(v)})),digits:priceDigits(chart.symbol)};
}
