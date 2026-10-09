import test from 'node:test';
import assert from 'node:assert/strict';
import {performance,matches,financialYear,evidenceCSV,stale,numeric} from '../src/model.js';
const event=(pnl,date='2026-01-01T00:00:00+00:00')=>({kind:'trade_closed',observed_at_utc:date,payload:{pnl_aud:pnl,symbol:'EURUSD',trade_style:'day',timeframe:'H1'}});
test('missing records do not invent performance',()=>{assert.equal(performance([]).pnl,null);assert.equal(performance([event('2')]).profitFactor,null);assert.equal(numeric(''),null);});
test('performance uses signed outcomes and observed equity',()=>{const p=performance([event('100'),event('-50'),event('0'),event('-25'),{kind:'balance',observed_at_utc:'2026-01-01',payload:{equity:'1000'}},{kind:'balance',observed_at_utc:'2026-01-02',payload:{equity:'800'}}]);assert.equal(p.pnl,25);assert.equal(p.winRate,25);assert.equal(p.profitFactor,100/75);assert.equal(p.drawdown,20);assert.equal(p.streak,-1);});
test('all filter dimensions apply together',()=>{const e=event('1');assert.equal(matches(e,{pair:'eurusd',timeframe:'h1',style:'day',from:'2026-01-01',through:'2026-01-01'}),true);assert.equal(matches(e,{style:'swing'}),false);assert.equal(matches(e,{from:'2026-01-02'}),false);});
test('Australian financial year rolls over at Sydney midnight',()=>{assert.equal(financialYear('2026-06-30T13:59:00Z'),'2025–2026');assert.equal(financialYear('2026-06-30T14:00:00Z'),'2026–2027');});
test('CSV includes payload and neutralizes spreadsheet formulas',()=>{const csv=evidenceCSV([{...event('1'),entity_id:'=HYPERLINK("bad")'}]);assert.ok(csv.includes("'=HYPERLINK"));assert.ok(csv.includes('pnl_aud'));});
test('unknown future and old heartbeat are not healthy',()=>{const now=Date.parse('2026-01-01T00:00:00Z');assert.equal(stale(null,now),true);assert.equal(stale('2025-12-31T23:57:00Z',now),true);assert.equal(stale('2026-01-01T00:00:01Z',now),true);assert.equal(stale('2025-12-31T23:59:00Z',now),false);});
import {simpleSummary,botState,periodStart,openPnl,chartModel,spreadLabels,priceDigits} from '../src/model.js';
const closed=(pnl,at)=>({kind:'trade_closed',observed_at_utc:at,payload:{pnl_aud:pnl,closed_at_utc:at,symbol:'USDJPY.a',direction:'LONG'}});
test('simple summary counts wins, losses and profit inside the chosen period',()=>{
  const now=Date.parse('2026-10-10T00:00:00Z');
  const trades=[closed('5','2026-10-09T00:00:00+00:00'),closed('-2','2026-10-05T00:00:00+00:00'),closed('0','2026-10-04T00:00:00+00:00'),closed('3','2026-09-01T00:00:00+00:00')];
  const s=simpleSummary(trades,{latest_balance:'106',realized_pnl_aud:'6'},'7',now);
  assert.equal(s.invested,100);assert.equal(s.balance,106);assert.equal(s.trades,3);assert.equal(s.won,1);assert.equal(s.lost,1);assert.equal(s.profit,3);assert.equal(s.profitPercent,3);
  assert.equal(s.recent[0].payload.pnl_aud,'5');
  assert.equal(simpleSummary(trades,{latest_balance:'106',realized_pnl_aud:'6'},'all',now).trades,4);
  assert.equal(periodStart('all',now),null);
});
test('simple summary never invents money when nothing is recorded',()=>{
  const s=simpleSummary([],{},'7');assert.equal(s.invested,null);assert.equal(s.profitPercent,null);assert.equal(s.trades,0);
});
test('bot state is running only with a recent heartbeat',()=>{
  const now=Date.parse('2026-10-10T00:10:00Z');
  assert.equal(botState({health_at_utc:'2026-10-10T00:09:30+00:00',latest_health:{status:'RUNNING'}},now).running,true);
  assert.equal(botState({health_at_utc:'2026-10-10T00:00:00+00:00'},now).running,false);
  assert.equal(botState({},now).running,false);
});
test('trades from an earlier paper account are not counted after a fresh start',()=>{
  const now=Date.parse('2026-10-10T00:00:00Z');
  const trades=[closed('-3.3','2026-09-30T03:00:00+00:00'),closed('12','2026-10-05T00:00:00+00:00')];
  const s=simpleSummary(trades,{latest_balance:'1012',realized_pnl_aud:'12',first_event_at_utc:'2026-10-01T10:00:00+00:00'},'all',now);
  assert.equal(s.invested,1000);assert.equal(s.trades,1);assert.equal(s.profit,12);assert.equal(s.lost,0);
  assert.equal(simpleSummary(trades,{latest_balance:'1012',realized_pnl_aud:'12',first_event_at_utc:'2026-10-01T10:00:00+00:00'},'7',now).trades,1);
});

test('open trades: total live P&L, unknown values, and chart geometry', () => {
  const summary = {latest_health: {positions: [{unrealized_pnl_aud: '12.40'}, {unrealized_pnl_aud: '-3.10'}]}};
  assert.ok(Math.abs(openPnl(summary) - 9.3) < 1e-9);
  assert.equal(openPnl({}), 0);
  assert.equal(openPnl({latest_health: {positions: [{unrealized_pnl_aud: null}]}}), null);
  const t0 = Date.parse('2026-10-05T00:00:00Z') / 1000;
  const bars = {t: [0, 1, 2, 3].map(i => t0 + i * 3600), h: [1.101, 1.103, 1.104, 1.106], l: [1.099, 1.1, 1.102, 1.103], c: [1.1, 1.102, 1.103, 1.105]};
  const chart = {symbol: 'EURUSD.a', side: 'LONG', entry: 1.1, stop: 1.098, initial_stop: 1.098, target: 1.12, opened_at_utc: '2026-10-05T01:00:00+00:00', bars};
  const m = chartModel(chart, {market_price: '1.1052'});
  assert.equal(m.targetOff, 'above');                  // The 10R target is far away: labelled, not drawn.
  assert.ok(m.entry.x > m.points[0][0] && m.entry.x < m.points.at(-1)[0]);
  const stop = m.lines.find(l => l.kind === 'stop'), entry = m.lines.find(l => l.kind === 'entry');
  assert.ok(stop.y > entry.y);                         // Below the entry on screen for a buy.
  assert.equal(m.digits, 5);
  assert.equal(chartModel({...chart, bars: {t: []}}, null), null);
  const spread = spreadLabels([{y: 50}, {y: 52}, {y: 53}], 15, 10, 200).map(i => i.labelY);
  assert.deepEqual(spread, [50, 65, 80]);
  assert.equal(priceDigits('USDJPY.a'), 3);
});
import {lossReviews} from '../src/model.js';
test('loss reviews are newest first, from this account only, and need a prompt',()=>{
  const prompt=(id,at,extra={})=>({kind:'loss_prompt',entity_id:id,observed_at_utc:at,payload:{symbol:'USDJPY',side:'LONG',r:-1.04,pnl_aud:'-53.70',closed_at_utc:at,prompt:'# Losing trade review',file_name:`${id}.txt`,...extra}});
  const list=lossReviews([prompt('old','2026-09-20T00:00:00+00:00'),prompt('a','2026-10-07T08:15:01+00:00'),
    prompt('b','2026-10-08T10:00:00+00:00',{symbol:'EURUSD.a',side:'SHORT'}),prompt('empty','2026-10-09T00:00:00+00:00',{prompt:''}),
    {kind:'trade_closed',payload:{}}],'2026-10-01T00:00:00+00:00');
  assert.deepEqual(list.map(x=>x.id),['b','a']);
  assert.equal(list[0].symbol,'EURUSD');assert.equal(list[0].side,'Sell');assert.equal(list[1].pnl,-53.7);assert.equal(list[1].r,-1.04);
  assert.equal(lossReviews([prompt('old','2026-09-20T00:00:00+00:00')]).length,1);
  assert.deepEqual(lossReviews(undefined),[]);
});
