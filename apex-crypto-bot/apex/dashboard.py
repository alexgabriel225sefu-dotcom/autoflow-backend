"""Live web dashboard — MT5-style with candlestick chart.

Renders a static shell; data fetched client-side from /api/status and
/api/candles every 5 seconds. Uses TradingView Lightweight Charts for
the candlestick chart with BUY/SELL markers and SL/TP lines.
"""


def render(dash):
    return """<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Apex Forex Bot — Live Trading</title>
<script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#131722;color:#d1d4dc;font-family:'Trebuchet MS',system-ui,sans-serif;font-size:13px}
.topbar{background:#1e222d;border-bottom:1px solid #2a2e39;padding:10px 16px;display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.logo{font-size:15px;font-weight:700;color:#fff;letter-spacing:.5px}
.logo span{color:#2962ff}
.sym{font-size:18px;font-weight:700;color:#fff}
.price{font-size:22px;font-weight:700;color:#26a69a}
.price.down{color:#ef5350}
.badge{font-size:10px;padding:3px 8px;border-radius:4px;font-weight:600;text-transform:uppercase;letter-spacing:.5px}
.badge.paper{background:#1a3a2a;color:#26a69a;border:1px solid #26a69a40}
.badge.live{background:#3a1a1a;color:#ef5350;border:1px solid #ef535040}
.badge.sell{background:#3a1a1a;color:#ef5350}
.badge.buy{background:#1a3a2a;color:#26a69a}
.spacer{flex:1}
.ticker{color:#787b86;font-size:11px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:1px;background:#2a2e39;border-top:1px solid #2a2e39}
.card{background:#1e222d;padding:10px 14px}
.card .lbl{font-size:10px;color:#787b86;text-transform:uppercase;letter-spacing:.5px;margin-bottom:3px}
.card .val{font-size:16px;font-weight:700;color:#d1d4dc}
.card .val.up{color:#26a69a}
.card .val.dn{color:#ef5350}
#chart-wrap{position:relative;width:100%;height:calc(100vh - 210px);min-height:300px;background:#131722}
#chart{width:100%;height:100%}
.chart-overlay{position:absolute;top:10px;left:10px;background:#1e222d99;border:1px solid #2a2e39;border-radius:6px;padding:8px 12px;font-size:11px;color:#787b86;pointer-events:none;backdrop-filter:blur(4px)}
.chart-overlay b{color:#d1d4dc;display:block;font-size:13px;margin-bottom:2px}
.bottom{display:grid;grid-template-columns:1fr 1fr;gap:1px;background:#2a2e39;border-top:1px solid #2a2e39;max-height:220px}
.panel{background:#131722;overflow:auto}
.panel-hd{background:#1e222d;padding:8px 14px;font-size:10px;color:#787b86;text-transform:uppercase;letter-spacing:.5px;font-weight:600;border-bottom:1px solid #2a2e39;position:sticky;top:0}
.pos-row{padding:10px 14px;border-bottom:1px solid #2a2e3960}
.pos-side{font-size:12px;font-weight:700}
.pos-side.BUY{color:#26a69a}
.pos-side.SELL{color:#ef5350}
table{width:100%;border-collapse:collapse}
th{padding:7px 10px;text-align:left;font-size:10px;color:#787b86;text-transform:uppercase;letter-spacing:.4px;font-weight:600;background:#1e222d;position:sticky;top:0;border-bottom:1px solid #2a2e39}
td{padding:7px 10px;border-bottom:1px solid #2a2e3940;font-size:12px}
.up{color:#26a69a}.dn{color:#ef5350}.muted{color:#787b86}
@media(max-width:640px){.bottom{grid-template-columns:1fr}.hide-sm{display:none}#chart-wrap{height:50vh}}
</style></head><body>

<div class="topbar">
  <div class="logo">APEX <span>FOREX</span></div>
  <div class="sym" id="sym">—</div>
  <div class="price" id="price">—</div>
  <div id="modebadge" class="badge paper">PAPER</div>
  <div class="spacer"></div>
  <div class="ticker muted" id="lasttick">connecting…</div>
</div>

<div class="cards">
  <div class="card"><div class="lbl">Balance</div><div class="val" id="c-bal">—</div></div>
  <div class="card"><div class="lbl">Total PnL</div><div class="val" id="c-pnl">—</div></div>
  <div class="card"><div class="lbl">Win Rate</div><div class="val" id="c-wr">—</div></div>
  <div class="card"><div class="lbl">Profit Factor</div><div class="val" id="c-pf">—</div></div>
  <div class="card"><div class="lbl">Trades</div><div class="val" id="c-tr">—</div></div>
  <div class="card"><div class="lbl">Open PnL</div><div class="val" id="c-opnl">—</div></div>
</div>

<div id="chart-wrap">
  <div id="chart"></div>
  <div class="chart-overlay">
    <b id="ov-sym">EUR/USD · 5m</b>
    <span id="ov-ind">Loading chart…</span>
  </div>
</div>

<div class="bottom">
  <div class="panel">
    <div class="panel-hd">Open Position</div>
    <div id="pos-body"><div class="pos-row muted">No open position</div></div>
  </div>
  <div class="panel">
    <div class="panel-hd">Trade History</div>
    <table>
      <thead><tr>
        <th>Time</th><th>Symbol</th><th>Side</th>
        <th>Entry</th><th>Exit</th><th>PnL</th><th class="hide-sm">Pips</th>
      </tr></thead>
      <tbody id="rows"><tr><td colspan="7" class="muted" style="padding:12px">Loading…</td></tr></tbody>
    </table>
  </div>
</div>

<script>
const $=id=>document.getElementById(id);
const fmt=(v,d=2)=>(v<0?'-':'')+'$'+Math.abs(v).toFixed(d);
const fmtN=(v,d=5)=>Number(v).toFixed(d);

// ── Lightweight Charts setup ──
const chart = LightweightCharts.createChart($('chart'), {
  layout:{background:{color:'#131722'},textColor:'#d1d4dc'},
  grid:{vertLines:{color:'#2a2e39'},horzLines:{color:'#2a2e39'}},
  crosshair:{mode:LightweightCharts.CrosshairMode.Normal},
  rightPriceScale:{borderColor:'#2a2e39'},
  timeScale:{borderColor:'#2a2e39',timeVisible:true,secondsVisible:false},
  width:$('chart').clientWidth,
  height:$('chart').clientHeight||400,
});

const candleSeries = chart.addCandlestickSeries({
  upColor:'#26a69a',downColor:'#ef5350',
  borderUpColor:'#26a69a',borderDownColor:'#ef5350',
  wickUpColor:'#26a69a',wickDownColor:'#ef5350',
});

const slLine = chart.addLineSeries({color:'#ef535080',lineWidth:1,lineStyle:LightweightCharts.LineStyle.Dashed,priceLineVisible:false,lastValueVisible:false});
const tpLine = chart.addLineSeries({color:'#26a69a80',lineWidth:1,lineStyle:LightweightCharts.LineStyle.Dashed,priceLineVisible:false,lastValueVisible:false});

window.addEventListener('resize',()=>{
  chart.applyOptions({width:$('chart').clientWidth,height:$('chart-wrap').clientHeight});
});

let lastCandleTime = 0;

function parseTime(t){
  if(!t) return Math.floor(Date.now()/1000);
  if(typeof t === 'number') return t > 1e10 ? Math.floor(t/1000) : t;
  return Math.floor(new Date(t).getTime()/1000);
}

function loadCandles(){
  fetch('/api/candles').then(r=>r.json()).then(d=>{
    if(!d.candles||!d.candles.length) return;
    const data = d.candles.map(c=>({
      time: parseTime(c.time),
      open: parseFloat(c.open), high: parseFloat(c.high),
      low: parseFloat(c.low), close: parseFloat(c.close),
    })).filter(c=>c.time>0).sort((a,b)=>a.time-b.time);
    if(data.length) {
      candleSeries.setData(data);
      lastCandleTime = data[data.length-1].time;
      $('ov-sym').textContent = (d.symbol||'—').replace('_','/') + ' · ' + (d.timeframe||'5m');
    }
  }).catch(()=>{});
}

function addTradeMarkers(trades, pos){
  const markers = [];
  (trades||[]).slice().reverse().forEach(t=>{
    if(t.entryTime) markers.push({
      time: parseTime(t.entryTime),
      position: t.side==='BUY'?'belowBar':'aboveBar',
      color: t.side==='BUY'?'#26a69a':'#ef5350',
      shape: t.side==='BUY'?'arrowUp':'arrowDown',
      text: t.side==='BUY'?'BUY':'SELL',
    });
    if(t.exitTime) markers.push({
      time: parseTime(t.exitTime),
      position: t.side==='BUY'?'aboveBar':'belowBar',
      color: '#787b86',
      shape: 'circle',
      text: 'CLOSE',
    });
  });
  if(pos && pos.entryTime) markers.push({
    time: parseTime(pos.entryTime),
    position: pos.side==='BUY'?'belowBar':'aboveBar',
    color: pos.side==='BUY'?'#26a69a':'#ef5350',
    shape: pos.side==='BUY'?'arrowUp':'arrowDown',
    text: pos.side,
  });
  markers.sort((a,b)=>a.time-b.time);
  candleSeries.setMarkers(markers);
}

function updateSLTP(pos){
  if(!pos||!lastCandleTime){slLine.setData([]);tpLine.setData([]);return;}
  const t0=lastCandleTime-200*300, t1=lastCandleTime+50*300;
  if(pos.stopLoss) slLine.setData([{time:t0,value:pos.stopLoss},{time:t1,value:pos.stopLoss}]);
  else slLine.setData([]);
  if(pos.takeProfit) tpLine.setData([{time:t0,value:pos.takeProfit},{time:t1,value:pos.takeProfit}]);
  else tpLine.setData([]);
}

function poll(){
  fetch('/api/status').then(r=>r.json()).then(d=>{
    const bal=d.balance||0, trades=d.trades||[], pos=d.openPosition;
    const start=d.startBalance||bal;
    const wins=trades.filter(t=>t.win), losses=trades.filter(t=>!t.win);
    const totalPnl=trades.reduce((s,t)=>s+(t.pnl||0),0);
    const gp=wins.reduce((s,t)=>s+(t.pnl||0),0);
    const gl=Math.abs(losses.reduce((s,t)=>s+(t.pnl||0),0));
    const pf=gl>0?(gp/gl).toFixed(2):(gp>0?'∞':'—');
    const wr=trades.length?Math.round(wins.length/trades.length*100):null;
    const openPnl=pos?pos.currentPnl||0:0;

    $('sym').textContent=(d.currentSymbol||'—').replace('_','/');
    const priceEl=$('price');
    priceEl.textContent=fmtN(d.currentPrice||0);
    priceEl.className='price '+(pos&&pos.side==='SELL'?'down':'');

    $('c-bal').textContent=fmt(bal);
    const pnlEl=$('c-pnl');
    pnlEl.textContent=(totalPnl>=0?'+':'')+fmt(totalPnl);
    pnlEl.className='val '+(totalPnl>=0?'up':'dn');
    $('c-wr').textContent=wr!=null?wr+'%':'—';
    $('c-pf').textContent=pf;
    $('c-tr').textContent=trades.length+' (✅'+wins.length+' ❌'+losses.length+')';
    const opnlEl=$('c-opnl');
    opnlEl.textContent=pos?(openPnl>=0?'+':'')+fmt(openPnl):'—';
    opnlEl.className='val '+(openPnl>0?'up':openPnl<0?'dn':'');
    $('modebadge').textContent=d.mode||'PAPER';
    $('lasttick').textContent='Last update: '+(d.lastTick||'—');

    // Open position
    if(pos){
      $('pos-body').innerHTML=`<div class="pos-row">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
          <span class="pos-side ${pos.side}">${pos.side}</span>
          <span style="font-weight:700;color:#fff">${(pos.symbol||d.currentSymbol||'').replace('_','/')}</span>
          <span class="badge ${pos.side.toLowerCase()}">${pos.side}</span>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;font-size:11px">
          <div><div class="muted">Entry</div><b>${fmtN(pos.entryPrice)}</b></div>
          <div><div class="muted">SL</div><b style="color:#ef5350">${fmtN(pos.stopLoss||0)}</b></div>
          <div><div class="muted">TP</div><b style="color:#26a69a">${fmtN(pos.takeProfit||0)}</b></div>
          <div><div class="muted">Qty</div><b>${(pos.quantity||0).toLocaleString()}</b></div>
          <div><div class="muted">Open PnL</div><b class="${openPnl>=0?'up':'dn'}">${openPnl>=0?'+':''}${fmt(openPnl)}</b></div>
          <div><div class="muted">Price</div><b>${fmtN(d.currentPrice||0)}</b></div>
        </div>
      </div>`;
    } else {
      $('pos-body').innerHTML='<div class="pos-row muted">No open position</div>';
    }

    // Trade history
    const rows=$('rows');
    if(!trades.length){ rows.innerHTML='<tr><td colspan="7" class="muted" style="padding:12px">No trades yet</td></tr>'; }
    else {
      rows.innerHTML=trades.slice(0,50).map(t=>`<tr>
        <td class="muted">${(t.entryTime||'').slice(11,16)||'—'}</td>
        <td>${(t.symbol||d.currentSymbol||'').replace('_','/')}</td>
        <td><span class="pos-side ${t.side}">${t.side}</span></td>
        <td>${fmtN(t.entryPrice||0)}</td>
        <td>${t.exitPrice?fmtN(t.exitPrice):'<span class="muted">open</span>'}</td>
        <td class="${(t.pnl||0)>=0?'up':'dn'}">${(t.pnl||0)>=0?'+':''}${fmt(t.pnl||0)}</td>
        <td class="hide-sm ${(t.pips||0)>=0?'up':'dn'}">${t.pips!=null?(t.pips>=0?'+':'')+Number(t.pips).toFixed(1)+'p':'—'}</td>
      </tr>`).join('');
    }

    // Chart markers + SL/TP lines
    addTradeMarkers(trades, pos);
    updateSLTP(pos);
    $('ov-ind').textContent = pos ? `${pos.side} @ ${fmtN(pos.entryPrice)} | PnL: ${openPnl>=0?'+':''}${fmt(openPnl)}` : 'No open position';

  }).catch(()=>{ $('lasttick').textContent='Connection lost — retrying…'; });
}

// Init
loadCandles();
poll();
setInterval(poll, 5000);
setInterval(loadCandles, 30000);
</script>
</body></html>"""
