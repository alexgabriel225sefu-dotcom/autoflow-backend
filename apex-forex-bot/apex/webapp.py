"""Telegram Mini App — the client's live trading terminal inside Telegram.

Served by the bot's own HTTP server at /app. The page authenticates itself by
sending Telegram's signed initData with every API call; validate() checks the
HMAC per https://core.telegram.org/bots/webapps#validating-data-received so a
client can only ever see THEIR OWN account."""
import hmac
import json
import hashlib
from urllib.parse import parse_qsl


def validate(init_data: str, bot_token: str):
    """Return the Telegram user dict if initData is authentic, else None."""
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
        their_hash = pairs.pop("hash", "")
        dcs = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
        secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, their_hash):
            return None
        return json.loads(pairs.get("user", "{}"))
    except Exception:
        return None


HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<title>Apex Terminal</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
<style>
:root{--bg:#0b0e16;--panel:#111827;--line:#1f2937;--t0:#e6e9ef;--t1:#94a3b8;--t2:#56565f;
  --up:#27c46a;--dn:#ff2d4f;--acc:#f59e0b}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--t0);font-family:-apple-system,system-ui,sans-serif;overflow-x:hidden}
#head{display:flex;align-items:center;justify-content:space-between;padding:12px 14px;border-bottom:1px solid var(--line)}
#sym{font-size:17px;font-weight:800}
#meta{font-size:11px;color:var(--t1);margin-top:2px}
#bal{text-align:right}
#bal b{font-size:16px}
#bal span{display:block;font-size:10px;color:var(--t1)}
#chart{height:46vh;position:relative}
#pos{margin:10px 14px;padding:10px 12px;background:var(--panel);border:1px solid var(--line);border-radius:12px;font-size:13px;display:none}
#pos .pnl-up{color:var(--up)} #pos .pnl-dn{color:var(--dn)}
.tabs{display:flex;gap:8px;margin:12px 14px 8px}
.tab{flex:1;text-align:center;padding:9px;background:var(--panel);border:1px solid var(--line);border-radius:10px;font-size:12.5px;font-weight:600;color:var(--t1)}
.tab.on{color:var(--t0);border-color:#374151}
.panel{margin:0 14px 20px;display:none}
.panel.on{display:block}
.item{padding:10px 2px;border-bottom:1px solid var(--line);font-size:13px;line-height:1.45}
.item b{font-weight:700}
.item .sub{color:var(--t1);font-size:11.5px}
.badge{display:inline-block;font-size:10px;font-weight:700;border-radius:5px;padding:2px 6px;background:#1f2937;color:var(--acc);margin-right:6px}
.up{color:var(--up)}.dn{color:var(--dn)}
#empty{color:var(--t2);font-size:12.5px;padding:14px 2px}
#err{color:var(--dn);font-size:12px;padding:10px 14px;display:none}
</style>
</head>
<body>
<div id="head">
  <div><div id="sym">—</div><div id="meta">connecting…</div></div>
  <div id="bal"><b id="balV">—</b><span id="mode"></span></div>
</div>
<div id="chart"></div>
<div id="pos"></div>
<div class="tabs">
  <div class="tab on" data-p="news">📰 News</div>
  <div class="tab" data-p="trades">📊 Trades</div>
</div>
<div class="panel on" id="p-news"><div id="empty">Loading events…</div></div>
<div class="panel" id="p-trades"><div id="empty">No trades yet.</div></div>
<div id="err"></div>
<script>
const tg = window.Telegram && Telegram.WebApp; if(tg){tg.ready();tg.expand();}
const initData = tg ? tg.initData : '';
const chartEl = document.getElementById('chart');
const chart = LightweightCharts.createChart(chartEl,{
  layout:{background:{color:'#0b0e16'},textColor:'#94a3b8',fontSize:10},
  grid:{vertLines:{color:'#151b28'},horzLines:{color:'#151b28'}},
  timeScale:{timeVisible:true,secondsVisible:false,borderColor:'#1f2937'},
  rightPriceScale:{borderColor:'#1f2937'},
  crosshair:{mode:1}});
const series = chart.addCandlestickSeries({upColor:'#27c46a',downColor:'#ff2d4f',
  borderUpColor:'#27c46a',borderDownColor:'#ff2d4f',wickUpColor:'#27c46a',wickDownColor:'#ff2d4f'});
new ResizeObserver(()=>chart.applyOptions({width:chartEl.clientWidth,height:chartEl.clientHeight})).observe(chartEl);
let lines=[];
function setLines(pos){
  lines.forEach(l=>series.removePriceLine(l)); lines=[];
  if(!pos) return;
  const mk=(price,color,title)=>{if(price)lines.push(series.createPriceLine({price,color,lineWidth:1,lineStyle:2,title}))};
  mk(pos.entryPrice,'#e6e9ef','ENTRY '+(pos.side||''));
  mk(pos.stopLoss||pos.sl,'#ff2d4f','SL');
  mk(pos.takeProfit||pos.tp,'#27c46a','TP');
}
document.querySelectorAll('.tab').forEach(t=>t.onclick=()=>{
  document.querySelectorAll('.tab').forEach(x=>x.classList.remove('on'));
  document.querySelectorAll('.panel').forEach(x=>x.classList.remove('on'));
  t.classList.add('on');document.getElementById('p-'+t.dataset.p).classList.add('on');});
function esc(s){return String(s||'').replace(/[<>&]/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;'}[c]))}
let first=true;
async function refresh(){
  try{
    const r = await fetch('/api/app/data?init='+encodeURIComponent(initData));
    if(!r.ok) throw new Error('HTTP '+r.status);
    const d = await r.json();
    document.getElementById('err').style.display='none';
    document.getElementById('sym').textContent = d.symbol.replace('_','/');
    document.getElementById('meta').textContent = d.strategy+' · '+d.mode+' · '+d.timeframe;
    document.getElementById('balV').textContent = '$'+(d.balance||0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
    document.getElementById('mode').textContent = d.broker||'';
    if(d.candles && d.candles.length){
      const data = d.candles.map(c=>({time:c.time,open:c.open,high:c.high,low:c.low,close:c.close}));
      series.setData(data); if(first){chart.timeScale().fitContent();first=false;}
    }
    setLines(d.position);
    const pos = document.getElementById('pos');
    if(d.position){
      const p=d.position, dir=p.side==='BUY'?'🟢 LONG':'🔴 SHORT';
      pos.style.display='block';
      pos.innerHTML = dir+' <b>'+esc(d.symbol)+'</b> @ '+p.entryPrice+
        (p.pnlPips!=null?' · <span class="'+(p.pnlPips>=0?'pnl-up':'pnl-dn')+'">'+(p.pnlPips>=0?'+':'')+p.pnlPips+' pips</span>':'');
    } else pos.style.display='none';
    const nv=document.getElementById('p-news');
    if(d.events && d.events.length){
      nv.innerHTML=d.events.map(e=>{
        const h=Math.floor(e.in_min/60),m=e.in_min%60;
        return '<div class="item"><span class="badge">'+esc(e.currency)+'</span><b>'+esc(e.title)+'</b>'+
               '<div class="sub">in '+(h?h+'h ':'')+m+'m — high impact · bot stands aside around it</div></div>';}).join('');
    } else nv.innerHTML='<div id="empty">No high-impact events in the next 24h — clear runway for trading.</div>';
    const tv=document.getElementById('p-trades');
    if(d.trades && d.trades.length){
      tv.innerHTML=d.trades.map(t=>{
        const pnl=t.netPnl, cls=pnl>=0?'up':'dn';
        return '<div class="item"><b>'+esc(t.action||'')+'</b> '+esc(t.symbol||'')+
          (t.price?' @ '+t.price:'')+(pnl!=null?' · <span class="'+cls+'">'+(pnl>=0?'+':'')+'$'+pnl.toFixed(2)+'</span>':'')+
          '<div class="sub">'+esc(t.time||'')+(t.reasoning?' — '+esc(t.reasoning):'')+'</div></div>';}).join('');
    }
  }catch(e){
    const el=document.getElementById('err');
    el.style.display='block'; el.textContent='Reconnecting… ('+e.message+')';
  }
}
refresh(); setInterval(refresh, 6000);
</script>
</body>
</html>"""
