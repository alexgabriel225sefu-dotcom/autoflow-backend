"""Live web dashboard — single page, zero dependencies.

Renders a static shell; all data is fetched client-side from /api/status
every 5 seconds (no full-page reloads). Shows balance, performance
metrics (win rate, profit factor, total PnL), an equity-curve chart
drawn on <canvas>, the open position, and the trade history table.
"""


def render(dash):
    return """<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Apex Forex Bot — Dashboard</title>
<style>
*{box-sizing:border-box;margin:0;padding:0;font-family:system-ui,-apple-system,sans-serif}
body{background:#0b0b0e;color:#eaecef;padding:24px}
.wrap{max-width:980px;margin:0 auto}
h1{font-size:20px;display:flex;align-items:center;gap:10px}
.badge{font-size:11px;padding:3px 10px;border-radius:99px;font-weight:600;letter-spacing:.4px}
.badge.paper{background:rgba(39,196,106,.12);color:#27c46a;border:1px solid rgba(39,196,106,.3)}
.badge.live{background:rgba(240,97,109,.12);color:#f0616d;border:1px solid rgba(240,97,109,.3)}
.muted{color:#6c6f78}.up{color:#27c46a}.down{color:#f0616d}
.sub{font-size:13px;margin-top:4px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin:18px 0}
.card{background:#15171c;border:1px solid rgba(255,255,255,.07);border-radius:12px;padding:16px}
.card b{font-size:20px;display:block;margin-bottom:2px}
.card span{font-size:11px;color:#6c6f78;text-transform:uppercase;letter-spacing:.5px}
.panel{background:#15171c;border:1px solid rgba(255,255,255,.07);border-radius:12px;padding:16px;margin-bottom:14px}
.panel h2{font-size:13px;color:#6c6f78;font-weight:500;text-transform:uppercase;letter-spacing:.5px;margin-bottom:10px}
canvas{width:100%;height:160px;display:block}
table{width:100%;border-collapse:collapse;background:#15171c;border-radius:12px;overflow:hidden}
th,td{padding:10px 12px;text-align:left;font-size:13px;border-bottom:1px solid rgba(255,255,255,.05)}
th{color:#6c6f78;font-weight:500}
.pos b{font-size:15px}
@media(max-width:640px){body{padding:12px}th,td{padding:7px 8px;font-size:12px}
 .hide-sm{display:none}}
</style></head><body><div class="wrap">
<h1>&#128177; Apex Forex Bot <span id="mode" class="badge paper">—</span> <span id="market" class="badge paper">—</span></h1>
<p class="muted sub" id="meta">connecting…</p>

<div class="cards">
  <div class="card"><b id="m-balance">—</b><span>Balance</span></div>
  <div class="card"><b id="m-pnl">—</b><span>Total PnL</span></div>
  <div class="card"><b id="m-winrate">—</b><span>Win rate</span></div>
  <div class="card"><b id="m-pf">—</b><span>Profit factor</span></div>
  <div class="card"><b id="m-symbol">—</b><span>Symbol</span></div>
  <div class="card"><b id="m-price">—</b><span>Price</span></div>
</div>

<div class="panel"><h2>Equity curve (closed trades)</h2><canvas id="equity" height="160"></canvas></div>
<div class="panel pos" id="pos"><h2>Open position</h2><p class="muted">No open position</p></div>

<table><thead><tr><th>Time</th><th>Symbol</th><th>Side</th><th>Entry</th><th>Exit</th>
<th>PnL</th><th class="hide-sm">Pips</th><th class="hide-sm">Reason</th></tr></thead>
<tbody id="rows"><tr><td colspan="8" class="muted">Loading…</td></tr></tbody></table>
</div>

<script>
const $=id=>document.getElementById(id);
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
function fmt(v,d=2){return (v<0?"-":"")+"$"+Math.abs(v).toFixed(d)}

function metrics(trades,startBal,bal){
  const wins=trades.filter(t=>t.win), losses=trades.filter(t=>!t.win);
  const gp=wins.reduce((s,t)=>s+t.pnl,0), gl=Math.abs(losses.reduce((s,t)=>s+t.pnl,0));
  return{
    total:trades.reduce((s,t)=>s+t.pnl,0),
    winrate:trades.length?Math.round(wins.length/trades.length*100):null,
    pf:gl>0?(gp/gl):(gp>0?Infinity:null),
  };
}

function drawEquity(trades,startBal){
  const cv=$("equity"),ctx=cv.getContext("2d");
  const W=cv.width=cv.clientWidth*devicePixelRatio, H=cv.height=160*devicePixelRatio;
  ctx.clearRect(0,0,W,H);
  const chron=[...trades].reverse(); // API sends newest first
  let eq=startBal||0; const pts=[eq];
  chron.forEach(t=>{eq+=t.pnl;pts.push(eq)});
  if(pts.length<2){ctx.fillStyle="#6c6f78";ctx.font=`${12*devicePixelRatio}px system-ui`;
    ctx.fillText("No closed trades yet — curve appears after the first trade.",12*devicePixelRatio,H/2);return}
  const lo=Math.min(...pts),hi=Math.max(...pts),pad=(hi-lo)||1;
  const x=i=>i/(pts.length-1)*(W-20)+10, y=v=>H-14-((v-lo)/pad)*(H-28);
  ctx.beginPath();ctx.moveTo(x(0),y(pts[0]));
  pts.forEach((v,i)=>ctx.lineTo(x(i),y(v)));
  ctx.strokeStyle=pts[pts.length-1]>=pts[0]?"#27c46a":"#f0616d";
  ctx.lineWidth=2*devicePixelRatio;ctx.stroke();
  ctx.lineTo(x(pts.length-1),H);ctx.lineTo(x(0),H);ctx.closePath();
  ctx.fillStyle=pts[pts.length-1]>=pts[0]?"rgba(39,196,106,.08)":"rgba(240,97,109,.08)";
  ctx.fill();
}

function update(d){
  const live=(d.mode||"").includes("LIVE");
  $("mode").textContent=d.mode||"—";
  $("mode").className="badge "+(live?"live":"paper");
  $("meta").textContent=`${d.exchange||""} · tick #${d.tickCount||0} · last: ${d.lastTick||"—"}`;
  $("m-balance").textContent=fmt(d.balance||0);
  const m=metrics(d.trades||[],d.startBalance,d.balance);
  const pnlEl=$("m-pnl");
  pnlEl.textContent=(m.total>=0?"+":"")+fmt(m.total);
  pnlEl.className=m.total>=0?"up":"down";
  $("m-winrate").textContent=m.winrate===null?"—":m.winrate+"%";
  $("m-pf").textContent=m.pf===null?"—":(m.pf===Infinity?"∞":m.pf.toFixed(2));
  $("m-symbol").textContent=d.currentSymbol||"—";
  $("m-price").textContent=(d.currentPrice||0).toFixed ? (+d.currentPrice).toFixed(5) : "—";
  const mk=$("market");mk.textContent=d.marketOpen===false?"MARKET CLOSED":"MARKET OPEN";
  mk.className="badge "+(d.marketOpen===false?"live":"paper");
  drawEquity(d.trades||[],d.startBalance);

  const op=d.openPosition;
  $("pos").innerHTML="<h2>Open position</h2>"+(op?
    `<b>${op.side==="BUY"?"LONG":"SHORT"} ${esc(op.symbol)}</b> @ $${op.entryPrice}
     · qty ${op.quantity} · SL $${(+op.stopLoss).toFixed(5)} · TP $${(+op.takeProfit).toFixed(5)}
     · PnL <span class="${(op.currentPnl||0)>=0?"up":"down"}">${(op.currentPnl||0)>=0?"+":""}$${(op.currentPnl||0).toFixed(4)}</span>`
    :'<p class="muted">No open position</p>');

  $("rows").innerHTML=(d.trades||[]).slice(0,30).map(t=>
    `<tr><td>${esc(t.time)}</td><td>${esc(t.symbol)}</td><td>${esc(t.side)}</td>
     <td>$${t.entry}</td><td>$${t.exit}</td>
     <td class="${t.win?"up":"down"}">${t.pnl>=0?"+":""}$${t.pnl}</td>
     <td class="hide-sm ${t.win?"up":"down"}">${(t.pips??0)>=0?"+":""}${t.pips??0}</td>
     <td class="hide-sm">${esc(t.reason)}</td></tr>`).join("")
    ||'<tr><td colspan="8" class="muted">No closed trades yet</td></tr>';
}

async function poll(){
  try{const r=await fetch("/api/status");update(await r.json())}
  catch(e){$("meta").textContent="reconnecting…"}
}
poll();setInterval(poll,5000);
</script></body></html>"""
