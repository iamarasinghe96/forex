import {initializeApp} from 'firebase/app';
import {getAuth,GoogleAuthProvider,signInWithPopup,signOut,onAuthStateChanged,setPersistence,browserLocalPersistence} from 'firebase/auth';
import {getFirestore,doc,collection,getDocs,query,orderBy,limit,startAfter,onSnapshot,where} from 'firebase/firestore';
import {matches,numeric,performance,reserveYears,evidenceCSV,stale,simpleSummary,botState,PERIODS} from './model.js';
import './style.css';

const $=id=>document.getElementById(id), money=v=>numeric(v)===null?'Unavailable':new Intl.NumberFormat('en-AU',{style:'currency',currency:'AUD'}).format(Number(v));
const number=v=>v===null?'Unavailable':Number(v).toFixed(2);
let auth,db,events=[],summary={},trades=[],tradeUnsub=null,cursor=null,unsub=null,generation=0,loading=false,exhausted=false;
const signed=v=>numeric(v)===null?'–':(Number(v)>0?'+':'')+money(v);
const when=ms=>new Intl.DateTimeFormat('en-AU',{timeZone:'Australia/Sydney',weekday:'short',day:'numeric',month:'short',hour:'numeric',minute:'2-digit'}).format(new Date(ms));
const pair=s=>String(s??'').replace(/\.[a-z]+$/i,'');
for(const [value,label] of PERIODS){const option=document.createElement('option');option.value=value;option.textContent=label;$('period').append(option);}
try{$('period').value=localStorage.getItem('forex-period')??'7';}catch{$('period').value='7';}
if(!$('period').value)$('period').value='7';
function row(target,left,right,tone){const item=document.createElement('div');item.className='row'+(tone?' '+tone:'');const a=document.createElement('span'),b=document.createElement('strong');a.textContent=left;b.textContent=right;item.append(a,b);target.append(item);}
function renderSimple(){
  const state=botState(summary),s=simpleSummary(trades,summary,$('period').value);
  $('bot-state').textContent=(state.running?'● ':'○ ')+'Bot: '+state.label;$('bot-state').className='bot '+(state.running?'on':'off');
  $('range').textContent=s.from===null?`All time, up to ${when(s.to)} (Sydney time)`:`${when(s.from)} → ${when(s.to)} (Sydney time)`;
  $('invested').textContent=s.invested===null?'–':money(s.invested);$('balance').textContent=s.balance===null?'–':money(s.balance);
  $('profit').textContent=s.trades?`${signed(s.profit)}${s.profitPercent===null?'':` (${s.profitPercent>0?'+':''}${s.profitPercent.toFixed(1)}%)`}`:money(0);
  $('profit').className=s.profit>0?'up':s.profit<0?'down':'';
  $('trades').textContent=String(s.trades);$('won').textContent=String(s.won);$('lost').textContent=String(s.lost);
  $('open').replaceChildren();const open=Array.isArray(summary.latest_health?.positions)?summary.latest_health.positions:[];
  if(!open.length)$('open').textContent='No open trades.';
  for(const p of open)row($('open'),`${pair(p.symbol)} · ${p.side==='LONG'?'Buy':'Sell'}`,signed(p.unrealized_pnl_aud)+' so far',numeric(p.unrealized_pnl_aud)>0?'good':numeric(p.unrealized_pnl_aud)<0?'bad':'');
  $('recent').replaceChildren();if(!s.recent.length)$('recent').textContent='No finished trades in this period yet. Days without trades are normal: the bot only trades when its rules line up.';
  const why={TARGET:'target reached',STOP:'stop-loss',FLATTEN:'closed by halt'};
  for(const e of s.recent){const v=Number(e.payload.pnl_aud);row($('recent'),`${when(Date.parse(e.payload.closed_at_utc??e.observed_at_utc))} · ${pair(e.payload.symbol)} ${e.payload.direction==='LONG'?'Buy':'Sell'} · ${why[e.payload.reason]??'closed'}`,signed(v),v>0?'good':v<0?'bad':'');}
}
const status=text=>{$('status').textContent=text;};
function card(target,label,value){const box=document.createElement('div');box.className='card';const title=document.createElement('span'),body=document.createElement('strong');title.textContent=label;body.textContent=value;box.append(title,body);target.append(box);}
function details(target,records){target.replaceChildren();if(!records.length){target.textContent='No records in this selection.';return;}for(const e of records){const item=document.createElement('details'),title=document.createElement('summary'),body=document.createElement('pre');title.textContent=`${e.observed_at_utc} · ${e.kind} · ${e.payload.symbol??e.payload.candidate?.symbol??e.entity_id}`;body.textContent=JSON.stringify(e.payload,null,2);item.append(title,body);target.append(item);}}
function clear(){generation++;unsub?.();unsub=null;tradeUnsub?.();tradeUnsub=null;trades=[];events=[];summary={};cursor=null;loading=false;exhausted=false;$('desk').hidden=true;for(const id of ['cards','positions','totals','metrics','rejections','events','reserves','health-events','curve'])$(id).replaceChildren();$('costs').textContent='';}
function filters(){return Object.fromEntries(['pair','timeframe','style','from','through'].map(id=>[id,$(id).value.trim()]));}
function render(){
  renderSimple();
  const selected=events.filter(e=>matches(e,filters())),p=performance(selected);
  $('cards').replaceChildren();card($('cards'),'Balance',money(summary.latest_balance));card($('cards'),'Equity',money(summary.latest_equity));
  const health=summary.latest_health;
  card($('cards'),'Bot',stale(summary.health_at_utc)?'Unknown / stale':health?.status??'Unavailable');card($('cards'),'MT5',stale(summary.health_at_utc)?'Unknown / stale':health?.connection??'Unavailable');
  $('freshness').textContent=stale(summary.health_at_utc)?'No recent heartbeat — do not assume the bot is running.':`Heartbeat ${summary.health_at_utc}`;
  $('positions').replaceChildren();$('positions').className='cards';
  if(Array.isArray(health?.positions)){
    if(!health.positions.length)$('positions').textContent='No open positions in the latest snapshot.';
    for(const position of health.positions){const box=document.createElement('div');box.className='card';const title=document.createElement('strong'),value=document.createElement('p'),levels=document.createElement('p');title.textContent=`${position.symbol} · ${position.side}`;value.textContent=`${position.volume} lots · unrealized ${money(position.unrealized_pnl_aud)}`;levels.textContent=`Entry ${position.entry} · stop ${position.stop} · target ${position.target}. ${stale(summary.health_at_utc)?'Snapshot stale. ':''}Simulated costs incomplete.`;box.append(title,value,levels);$('positions').append(box);}
  }else $('positions').textContent='No current position snapshot available.';
  $('totals').replaceChildren();card($('totals'),'All-time recorded P&L',money(summary.realized_pnl_aud));card($('totals'),'All-time reserve',money(summary.reserve_aud));card($('totals'),'Cost evidence',summary.costs_complete?'Recorded as complete':'Incomplete / unavailable');
  $('scope').textContent=`${selected.length} matching records out of ${events.length} loaded. ${exhausted?'End of available history reached.':'Older records may be missing; load more for a wider view.'} Filtered metrics and exports cover this subset. Currency metrics reflect recorded P&L, not validated profitability.`;
  $('metrics').replaceChildren();for(const [label,value] of [['Closed trades',String(p.count)],['Recorded P&L',money(p.pnl)],['Win rate',p.winRate===null?'Unavailable':number(p.winRate)+'%'],['Profit factor',number(p.profitFactor)],['Average win',money(p.averageWin)],['Average loss',money(p.averageLoss)],['Observed equity drawdown',p.drawdown===null?'Unavailable':number(p.drawdown)+'%'],['Outcome streak',p.streak===null?'Unavailable':String(p.streak)]])card($('metrics'),label,value);
  $('curve').replaceChildren();if(p.balances.length>1){const values=p.balances.map(e=>Number(e.payload.equity)),low=Math.min(...values),high=Math.max(...values),line=document.createElementNS('http://www.w3.org/2000/svg','polyline');line.setAttribute('points',values.map((v,i)=>`${20+i/(values.length-1)*760},${160-(v-low)/(high-low||1)*140}`).join(' '));line.setAttribute('fill','none');line.setAttribute('stroke','#8fdcb7');line.setAttribute('stroke-width','3');$('curve').append(line);$('curve-label').textContent=`${p.balances[0].observed_at_utc} to ${p.balances.at(-1).observed_at_utc} · ${money(low)}–${money(high)} · observation spacing, no interpolation of missing evidence.`;}else $('curve-label').textContent='At least two recorded balance observations are required. Pair/style filters may exclude account-level balances.';
  const ordered=[...selected].sort((a,b)=>a.observed_at_utc.localeCompare(b.observed_at_utc)*($('sort').value==='old'?1:-1));
  details($('rejections'),ordered.filter(e=>['no_trade','hard_risk_block','context_rejection','analysis_no_candidate'].includes(e.kind)));
  const search=$('search').value.toLowerCase();details($('events'),ordered.filter(e=>JSON.stringify(e).toLowerCase().includes(search)));
  $('reserves').replaceChildren();for(const [year,v] of Object.entries(reserveYears(selected)).sort().reverse()){const paragraph=document.createElement('p');paragraph.textContent=`FY ${year}: recorded P&L ${money(v.pnl)} · reserve ${money(v.reserve)} · ${v.count} loaded closed trades`;$('reserves').append(paragraph);}if(!$('reserves').childNodes.length)$('reserves').textContent='No closed-trade reserve records in the loaded selection.';
  const calls=selected.filter(e=>e.kind==='context_call');let known=0,unknown=0;for(const e of calls){const cost=numeric(e.payload.cost_usd);if(cost===null)unknown++;else known+=cost;}$('costs').textContent=`Loaded context calls: ${calls.length}. Known cost: USD ${known.toFixed(4)}; ${unknown} calls have unknown cost. This is not a complete billing total.`;
  details($('health-events'),ordered.filter(e=>['health','error','alert','context_call'].includes(e.kind)));$('more').disabled=loading||exhausted;
}
async function page(reset=false){if(loading||!auth?.currentUser)return;loading=true;const token=generation;try{const root=collection(db,'modes',$('mode').value,'events');const constraints=[orderBy('sequence','desc'),limit(100)];if(!reset&&cursor)constraints.push(startAfter(cursor));const snapshot=await getDocs(query(root,...constraints));if(token!==generation)return;if(reset)events=[];const known=new Set(events.map(e=>e.event_id));for(const item of snapshot.docs){const value=item.data();if(!known.has(value.event_id))events.push(value);}cursor=snapshot.docs.at(-1)??cursor;exhausted=snapshot.size<100;status(snapshot.metadata.fromCache?'Offline cached history — freshness unverified.':'Cloud history loaded.');render();}catch{if(token===generation){clear();status('Data access failed. Check operator authorization, network and deployed rules. Sign out and back in to retry.');}}finally{if(token===generation){loading=false;$('more').disabled=exhausted;}}}
function subscribe(){clear();$('desk').hidden=false;const token=generation;unsub=onSnapshot(doc(db,'modes',$('mode').value,'aggregates','all'),{includeMetadataChanges:true},snapshot=>{if(token!==generation)return;summary=snapshot.exists()?snapshot.data():{};status(snapshot.metadata.fromCache?'Waiting for server confirmation; cloud data may be stale.':'Connected to the cloud mirror.');render();},()=>{if(token===generation){clear();status('Access denied or cloud unavailable. No account data is displayed.');}});tradeUnsub=onSnapshot(query(collection(db,'modes',$('mode').value,'events'),where('kind','==','trade_closed')),snapshot=>{if(token!==generation)return;trades=snapshot.docs.map(d=>d.data());render();},()=>{});void page(true);}
$('mode').addEventListener('change',subscribe);$('period').addEventListener('change',()=>{try{localStorage.setItem('forex-period',$('period').value);}catch{}render();});$('refresh').addEventListener('click',()=>{if(auth?.currentUser)subscribe();});$('more').addEventListener('click',()=>void page());
for(const id of ['pair','timeframe','style','from','through','search','sort'])$(id).addEventListener('input',render);
$('export').addEventListener('click',()=>{const blob=new Blob([evidenceCSV(events.filter(e=>matches(e,filters())))],{type:'text/csv;charset=utf-8'}),url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=`forex-${$('mode').value}-loaded-evidence.csv`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
setInterval(()=>{if(!$('desk').hidden)render();},30000);
const config={apiKey:import.meta.env.VITE_FIREBASE_API_KEY,authDomain:import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,projectId:import.meta.env.VITE_FIREBASE_PROJECT_ID,appId:import.meta.env.VITE_FIREBASE_APP_ID};
if(Object.values(config).some(v=>!v))status('Setup pending: add public Firebase web configuration and deploy operator-only access rules. No account is connected.');
else{try{const app=initializeApp(config);auth=getAuth(app);db=getFirestore(app);await setPersistence(auth,browserLocalPersistence);$('auth').disabled=false;$('auth').addEventListener('click',async()=>{try{if(auth.currentUser){clear();await signOut(auth);}else await signInWithPopup(auth,new GoogleAuthProvider());}catch{status('Sign-in could not finish. Check your account and Firebase authorized domains.');}});onAuthStateChanged(auth,user=>{clear();$('auth').textContent=user?'Sign out':'Sign in';if(user)subscribe();else status('Sign in with the operator account to view records.');});}catch{clear();status('Firebase setup could not initialize. Check the public web configuration.');}}
