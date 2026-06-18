/**
 * APEX TRADE BOT — Premium Dashboard HTML + HTTP server
 */
const http = require('http');

function buildDashboard(dash) {
  const s      = dash.settings || {};
  const sym    = dash.currentSymbol || s.SYMBOL || 'SOLUSDT';
  const exch   = (dash.exchange || 'BINANCE').toUpperCase();
  const tvSym  = `${exch === 'BYBIT' ? 'BYBIT' : 'BINANCE'}:${sym}`;
  const bal    = (dash.balance || 0).toFixed(2);
  const price  = dash.currentPrice > 0 ? '$' + dash.currentPrice.toFixed(4) : '—';
  const pnlNum = dash.startBalance > 0 ? ((dash.balance - dash.startBalance) / dash.startBalance * 100) : 0;
  const pnlPct = pnlNum.toFixed(2);
  const pnlSign  = pnlNum >= 0 ? '+' : '';
  const pnlClass = pnlNum >= 0 ? 'green' : 'red';
  const wins   = (dash.trades || []).filter(t => t.win).length;
  const total  = (dash.trades || []).length;
  const losses = total - wins;
  const winRate = total > 0 ? ((wins / total) * 100).toFixed(0) + '%' : '—';
  const mode   = dash.mode || 'PAPER';
  const tick   = dash.tickCount || 0;
  const lastTick = dash.lastTick || '—';

  // ── Settings panel vars ───────────────────────────────────
  const paused    = !!s.PAUSED;
  const stratMode = s.STRATEGY_MODE || 'auto';
  const SYMS = ['BTCUSDT','ETHUSDT','SOLUSDT','BNBUSDT','XRPUSDT','DOGEUSDT','ADAUSDT','MATICUSDT','AVAXUSDT','DOTUSDT'];
  const symOpts = SYMS.map(o => `<option${o === (s.SYMBOL||sym) ? ' selected' : ''}>${o}</option>`).join('');
  const STRATS = [['auto','Auto (AI selects)'],['turtle','Turtle Breakout'],['livermore','Livermore Trend'],['soros','Soros Momentum'],['ptj','PTJ High-Conviction'],['druckenmiller','Druckenmiller Full-Size']];
  const stratOpts = STRATS.map(([v, l]) => `<option value="${v}"${v === stratMode ? ' selected' : ''}>${l}</option>`).join('');
  const riskDisp = ((s.RISK_PER_TRADE || 0.02) * 100).toFixed(1);
  const slDisp   = ((s.STOP_LOSS_PCT  || 0.015) * 100).toFixed(1);
  const tpDisp   = ((s.TAKE_PROFIT_PCT|| 0.03)  * 100).toFixed(1);
  const confDisp  = s.MIN_CONFIDENCE || 70;
  const critDisp  = s.MIN_CRITERIA !== undefined ? s.MIN_CRITERIA : 3;

  // ── Last Signal ───────────────────────────────────────────
  const ls = dash.lastSignal;
  let sigHtml = `<div class="pos-empty">⏳ Waiting for first AI analysis...</div>`;
  if (ls) {
    const ac = ls.action;
    const acColor = ac === 'BUY' ? 'green' : ac === 'SELL' ? 'red' : 'muted';
    const acIcon  = ac === 'BUY' ? '▲' : ac === 'SELL' ? '▼' : '⏸';
    const conf    = ls.confidence ?? 0;
    const crit    = ls.criteriaScore ?? 0;
    const confColor = conf >= 70 ? 'green' : conf >= 55 ? 'amber' : 'red';
    sigHtml = `
<div class="sig-card">
  <div class="sig-row">
    <span class="sig-action ${acColor}">${acIcon} ${ac}</span>
    <span class="muted" style="font-size:.65rem">${ls.time || ''}</span>
  </div>
  <div class="sig-meta">
    <span>Confidence: <b class="${confColor}">${conf}%</b></span>
    <span>Criteria: <b>${crit}/5</b></span>
    <span>Volume: <b>${dash.lastVolume ? dash.lastVolume + '×' : '—'}</b></span>
  </div>
  <div class="sig-reason">"${ls.reasoning || '—'}"</div>
</div>`;
  }

  // ── Active Position ───────────────────────────────────────
  let posHtml = `<div class="pos-empty">⏳ No open position — waiting for signal...</div>`;
  if (dash.openPosition) {
    const p = dash.openPosition;
    const isLong = p.side === 'BUY';
    const dir = isLong ? '▲ LONG' : '▼ SHORT';
    const pnl = p.currentPnl || 0;
    const ps = pnl >= 0 ? '+' : '';
    const pc = pnl >= 0 ? 'green' : 'red';
    const range = Math.abs((p.takeProfit || p.entryPrice) - (p.stopLoss || p.entryPrice));
    const dist  = range > 0 ? Math.abs((dash.currentPrice || p.entryPrice) - (p.stopLoss || p.entryPrice)) : 0;
    const prog  = Math.min(100, Math.max(0, (dist / range) * 100)).toFixed(0);
    posHtml = `
<div class="pos-card ${isLong ? 'long' : 'short'}">
  <div class="pos-row">
    <span class="pos-dir ${isLong ? 'green' : 'red'}">${dir} ${p.symbol || sym}</span>
    <span class="pos-pnl ${pc}">${ps}$${pnl.toFixed(4)}</span>
  </div>
  <div class="pos-grid">
    <div class="pi"><span class="pi-l">Entry</span><span class="pi-v">$${p.entryPrice}</span></div>
    <div class="pi"><span class="pi-l">Qty</span><span class="pi-v">${p.quantity}</span></div>
    <div class="pi"><span class="pi-l">Stop Loss</span><span class="pi-v red">$${(p.stopLoss||0).toFixed(5)}</span></div>
    <div class="pi"><span class="pi-l">Take Profit</span><span class="pi-v green">$${(p.takeProfit||0).toFixed(5)}</span></div>
  </div>
  <div class="prog-wrap"><div class="prog-bar"><div class="prog-fill" style="width:${prog}%"></div></div>
    <div class="prog-labels"><span class="red">SL</span><span class="muted">Progress</span><span class="green">TP</span></div>
  </div>
</div>`;
  }

  // ── Trade history rows ────────────────────────────────────
  const rows = (dash.trades || []).length === 0
    ? `<tr class="empty-row"><td colspan="6">No trades yet — bot is analyzing...</td></tr>`
    : (dash.trades || []).slice(0, 20).map(t => `
<tr class="${t.win ? 'win' : 'loss'}">
  <td>${(t.time||'').split(',')[1]?.trim() || t.time}</td>
  <td>${t.symbol}</td>
  <td><span class="${t.side==='BUY'?'green':'red'}">${t.side==='BUY'?'▲ L':'▼ S'}</span></td>
  <td>$${t.entry?.toFixed(4)}</td>
  <td class="${t.pnl>=0?'green':'red'}">${t.pnl>=0?'+':''}$${t.pnl}</td>
  <td class="muted">${t.reason}</td>
</tr>`).join('');

  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Apex Trade Bot</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#060608;--card:#0b0b0e;--border:#1e1e26;--text:#e5e7eb;--muted:#6b7280;--acc:#ff2d4f;--green:#27c46a;--red:#ff2d4f;--blue:#60a5fa}
body{background:var(--bg);color:var(--text);font-family:'Inter','Segoe UI',system-ui,sans-serif;min-height:100vh}
.hdr{display:flex;align-items:center;justify-content:space-between;padding:12px 18px;border-bottom:1px solid var(--border);background:linear-gradient(135deg,#0b1120,#050814);position:sticky;top:0;z-index:99;backdrop-filter:blur(10px)}
.logo{display:flex;align-items:center;gap:10px}
.logo-text{font-weight:700;font-size:.95rem;letter-spacing:-.01em;color:#fff;font-family:'Clash Display',system-ui,sans-serif}
.hdr-right{display:flex;align-items:center;gap:8px}
.status-badge{display:flex;align-items:center;gap:6px;background:rgba(255,45,79,.08);border:1px solid rgba(255,45,79,.2);border-radius:20px;padding:4px 10px;font-size:.68rem;font-weight:700;color:var(--acc);letter-spacing:.04em}
.dot{width:6px;height:6px;border-radius:50%;background:var(--acc);animation:blink 2s infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.3}}
.metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:var(--border)}
.m{background:var(--card);padding:12px 10px;text-align:center}
.m-l{font-size:.6rem;color:var(--muted);text-transform:uppercase;letter-spacing:.07em;margin-bottom:4px}
.m-v{font-size:1.05rem;font-weight:800;line-height:1}
.green{color:var(--green)}.red{color:var(--red)}.amber{color:var(--amber)}.blue{color:var(--blue)}.muted{color:var(--muted)}.white{color:#fff}
.chart-wrap{background:#000;border-bottom:1px solid var(--border)}
.chart-wrap iframe{display:block;width:100%;height:430px;border:0}
.sec{padding:14px 16px;border-bottom:1px solid var(--border)}
.sec-title{font-size:.65rem;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);margin-bottom:10px}
.pos-empty{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:18px;text-align:center;color:var(--muted);font-size:.82rem}
.pos-card{border-radius:10px;padding:14px}
.pos-card.long{background:rgba(0,232,122,.05);border:1px solid rgba(0,232,122,.18)}
.pos-card.short{background:rgba(255,77,109,.05);border:1px solid rgba(255,77,109,.18)}
.pos-row{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}
.pos-dir{font-weight:800;font-size:.9rem}.pos-pnl{font-weight:800;font-size:1.05rem}
.pos-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px}
.pi{display:flex;flex-direction:column;gap:2px}
.pi-l{font-size:.6rem;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
.pi-v{font-weight:700;font-size:.83rem;color:#fff}
.prog-wrap{margin-top:2px}
.prog-bar{height:3px;background:var(--border);border-radius:2px;overflow:hidden;margin-bottom:4px}
.prog-fill{height:100%;background:linear-gradient(90deg,var(--red),#ff7c45,var(--green));border-radius:2px;transition:width .5s}
.prog-labels{display:flex;justify-content:space-between;font-size:.6rem;font-weight:700}
.tbl-wrap{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:.74rem}
th{color:var(--muted);font-size:.6rem;font-weight:600;padding:7px 6px;border-bottom:1px solid var(--border);text-align:left;text-transform:uppercase;letter-spacing:.06em}
td{padding:7px 6px;border-bottom:1px solid rgba(255,255,255,.03)}
tr.win td{color:#d1fae5}tr.loss td{color:#fee2e2}
.empty-row td{color:var(--muted);text-align:center;padding:20px;font-size:.8rem}
/* Settings panel */
.ctrl-grid{display:grid;gap:10px}
.ctrl-label{font-size:.6rem;color:var(--muted);text-transform:uppercase;letter-spacing:.07em;display:block;margin-bottom:4px}
.ctrl-row{display:flex;align-items:center;gap:8px}
.ctrl-inp,.ctrl-sel{flex:1;background:var(--card);border:1px solid var(--border);color:var(--text);padding:7px 10px;border-radius:8px;font-size:.82rem;font-family:inherit;outline:none;min-width:0}
.ctrl-inp:focus,.ctrl-sel:focus{border-color:var(--acc)}
.apply-btn{background:rgba(255,45,79,.12);border:1px solid rgba(255,45,79,.3);color:var(--acc);padding:6px 14px;border-radius:8px;cursor:pointer;font-size:.75rem;font-weight:700;white-space:nowrap}
.apply-btn:hover{background:rgba(255,45,79,.25)}
.fb{font-size:.67rem;min-width:54px;height:16px}
.fb.ok{color:var(--green)}.fb.err{color:var(--red)}
.ctrl-hint{font-size:.6rem;color:var(--muted);margin-top:2px}
.pause-row{display:flex;gap:10px;margin-top:14px}
.ctrl-btn{flex:1;padding:11px;border-radius:10px;cursor:pointer;font-weight:700;font-size:.85rem;border:1px solid;transition:.15s}
.btn-pause{background:rgba(255,77,109,.08);border-color:rgba(255,77,109,.25);color:var(--red)}
.btn-pause:hover{background:rgba(255,77,109,.2)}
.btn-resume{background:rgba(0,232,122,.08);border-color:rgba(0,232,122,.2);color:var(--green)}
.btn-resume:hover{background:rgba(0,232,122,.2)}
/* Last signal */
.sig-card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:12px 14px}
.sig-row{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}
.sig-action{font-weight:800;font-size:.95rem}
.sig-meta{display:flex;gap:14px;font-size:.72rem;color:var(--muted);margin-bottom:8px}
.sig-meta b{color:var(--text)}
.sig-reason{font-size:.72rem;color:var(--muted);font-style:italic;line-height:1.4;border-top:1px solid var(--border);padding-top:8px;margin-top:2px}
.amber{color:#f59e0b}
.footer{padding:10px 16px;font-size:.65rem;color:var(--muted);text-align:center}
@media(max-width:480px){.metrics{grid-template-columns:repeat(2,1fr)}.chart-wrap iframe{height:340px}}
</style>
<script>setTimeout(()=>location.reload(),30000)</script>
</head>
<body>

<header class="hdr">
  <div class="logo">
    <svg width="26" height="26" viewBox="0 0 32 32" fill="none">
      <defs><linearGradient id="lg" x1="3" y1="29" x2="29" y2="3" gradientUnits="userSpaceOnUse">
        <stop stop-color="#7a1020"/><stop offset="1" stop-color="#ff5c74"/></linearGradient></defs>
      <rect x="3" y="19" width="5" height="10" rx="2.5" fill="url(#lg)" opacity=".45"/>
      <rect x="11.5" y="12" width="5" height="17" rx="2.5" fill="url(#lg)" opacity=".72"/>
      <rect x="20" y="6" width="5" height="23" rx="2.5" fill="url(#lg)"/>
      <circle cx="22.5" cy="5" r="3.1" fill="#ff5c74"/>
    </svg>
    <span class="logo-text">Apex&nbsp;Bot</span>
  </div>
  <div class="hdr-right">
    <div class="status-badge"><span class="dot"></span>${paused ? '<span style="color:#ff7c45">PAUSED</span>' : 'LIVE'} · ${mode}</div>
  </div>
</header>

<div class="metrics">
  <div class="m"><div class="m-l">Balance</div><div class="m-v green">$${bal}</div></div>
  <div class="m"><div class="m-l">Total PnL</div><div class="m-v ${pnlClass}">${pnlSign}${pnlPct}%</div></div>
  <div class="m"><div class="m-l">Win Rate</div><div class="m-v" style="color:var(--acc)">${winRate}</div></div>
  <div class="m"><div class="m-l">Trades</div><div class="m-v blue">${total}</div></div>
  <div class="m"><div class="m-l">W / L</div><div class="m-v white">${wins} / ${losses}</div></div>
  <div class="m"><div class="m-l">${sym}</div><div class="m-v white">${price}</div></div>
</div>

<div class="chart-wrap">
  <iframe src="https://www.tradingview.com/widgetembed/?frameElementId=tv&symbol=${tvSym}&interval=5&theme=dark&style=1&timezone=Etc%2FUTC&withdateranges=1&hide_side_toolbar=0&allow_symbol_change=0&save_image=0&studies=RSI%401%2CMASimple%401%2CMACD%40tv-basicstudies&calendar=0&support_host=https%3A%2F%2Fwww.tradingview.com" allowtransparency="true" scrolling="no"></iframe>
</div>

<div class="sec">
  <div class="sec-title">◈ Last AI Signal</div>
  ${sigHtml}
</div>

<div class="sec">
  <div class="sec-title">◈ Active Position</div>
  ${posHtml}
</div>

<div class="sec">
  <div class="sec-title">◈ Trade History</div>
  <div class="tbl-wrap">
    <table>
      <thead><tr><th>Time</th><th>Symbol</th><th>Side</th><th>Entry</th><th>PnL</th><th>Reason</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  </div>
</div>

<div class="sec">
  <div class="sec-title">⚙ Bot Controls</div>
  <div class="ctrl-grid">
    <div>
      <label class="ctrl-label">Symbol</label>
      <div class="ctrl-row">
        <select id="inp-SYMBOL" class="ctrl-sel">${symOpts}</select>
        <button class="apply-btn" onclick="applyStr('SYMBOL','inp-SYMBOL','fb-SYMBOL')">Apply</button>
        <span id="fb-SYMBOL" class="fb"></span>
      </div>
      <div class="ctrl-hint">Takes effect on the next tick (symbol locked while a position is open)</div>
    </div>
    <div>
      <label class="ctrl-label">Strategy</label>
      <div class="ctrl-row">
        <select id="inp-STRAT" class="ctrl-sel">${stratOpts}</select>
        <button class="apply-btn" onclick="applyStr('STRATEGY_MODE','inp-STRAT','fb-STRAT')">Apply</button>
        <span id="fb-STRAT" class="fb"></span>
      </div>
    </div>
    <div>
      <label class="ctrl-label">Risk per trade (%)</label>
      <div class="ctrl-row">
        <input id="inp-RISK" type="number" step="0.1" min="0.1" max="50" value="${riskDisp}" class="ctrl-inp">
        <button class="apply-btn" onclick="applyPct('RISK_PER_TRADE','inp-RISK','fb-RISK')">Apply</button>
        <span id="fb-RISK" class="fb"></span>
      </div>
      <div class="ctrl-hint">e.g. 2 = 2% of balance per trade (recommended: 1–5)</div>
    </div>
    <div>
      <label class="ctrl-label">Stop Loss (%)</label>
      <div class="ctrl-row">
        <input id="inp-SL" type="number" step="0.1" min="0.1" max="50" value="${slDisp}" class="ctrl-inp">
        <button class="apply-btn" onclick="applyPct('STOP_LOSS_PCT','inp-SL','fb-SL')">Apply</button>
        <span id="fb-SL" class="fb"></span>
      </div>
    </div>
    <div>
      <label class="ctrl-label">Take Profit (%)</label>
      <div class="ctrl-row">
        <input id="inp-TP" type="number" step="0.1" min="0.1" max="100" value="${tpDisp}" class="ctrl-inp">
        <button class="apply-btn" onclick="applyPct('TAKE_PROFIT_PCT','inp-TP','fb-TP')">Apply</button>
        <span id="fb-TP" class="fb"></span>
      </div>
    </div>
    <div>
      <label class="ctrl-label">Min AI Confidence (50–99)</label>
      <div class="ctrl-row">
        <input id="inp-CONF" type="number" step="1" min="50" max="99" value="${confDisp}" class="ctrl-inp">
        <button class="apply-btn" onclick="applyNum('MIN_CONFIDENCE','inp-CONF','fb-CONF')">Apply</button>
        <span id="fb-CONF" class="fb"></span>
      </div>
    </div>
    <div>
      <label class="ctrl-label">Min Criteria Score (1–5)</label>
      <div class="ctrl-row">
        <input id="inp-CRIT" type="number" step="1" min="1" max="5" value="${critDisp}" class="ctrl-inp">
        <button class="apply-btn" onclick="applyNum('MIN_CRITERIA','inp-CRIT','fb-CRIT')">Apply</button>
        <span id="fb-CRIT" class="fb"></span>
      </div>
      <div class="ctrl-hint">3 = relaxed (mai multe trade-uri) | 5 = strict (calitate maximă)</div>
    </div>
  </div>
  <div class="pause-row">
    <button id="pauseBtn" class="ctrl-btn ${paused ? 'btn-resume' : 'btn-pause'}"
      onclick="applyControl('${paused ? 'resume' : 'pause'}')">
      ${paused ? '▶ Resume Bot' : '⏸ Pause Bot'}
    </button>
  </div>
</div>

<div class="footer">Auto-refresh 30s · Tick #${tick} · Last: ${lastTick} · ${exch}</div>

<script>
(function(){
  var TOKEN = new URLSearchParams(location.search).get('token') || '';
  var AUTH = TOKEN ? {'Authorization':'Bearer '+TOKEN} : {};

  function fb(id, ok, msg) {
    var el = document.getElementById(id);
    el.textContent = ok ? '✓ Saved' : '✗ ' + msg;
    el.className = 'fb ' + (ok ? 'ok' : 'err');
    setTimeout(function(){ el.textContent=''; el.className='fb'; }, 3000);
  }

  async function post(url, body) {
    var r = await fetch(url, {
      method:'POST',
      headers: Object.assign({'Content-Type':'application/json'}, AUTH),
      body: JSON.stringify(body)
    });
    return r.json();
  }

  window.applyStr = async function(key, inputId, feedId) {
    try {
      var val = document.getElementById(inputId).value;
      var d = await post('/api/settings', {key, value: val});
      fb(feedId, !!d.ok, d.error || 'Error');
    } catch(e) { fb(feedId, false, 'Network'); }
  };

  window.applyPct = async function(key, inputId, feedId) {
    try {
      var pct = parseFloat(document.getElementById(inputId).value);
      if (isNaN(pct) || pct <= 0) { fb(feedId, false, 'Invalid'); return; }
      var d = await post('/api/settings', {key, value: pct / 100});
      fb(feedId, !!d.ok, d.error || 'Error');
    } catch(e) { fb(feedId, false, 'Network'); }
  };

  window.applyNum = async function(key, inputId, feedId) {
    try {
      var num = parseFloat(document.getElementById(inputId).value);
      if (isNaN(num)) { fb(feedId, false, 'Invalid'); return; }
      var d = await post('/api/settings', {key, value: num});
      fb(feedId, !!d.ok, d.error || 'Error');
    } catch(e) { fb(feedId, false, 'Network'); }
  };

  window.applyControl = async function(action) {
    try {
      await post('/api/control', {action});
      var btn = document.getElementById('pauseBtn');
      if (action === 'pause') {
        btn.textContent = '▶ Resume Bot';
        btn.className = 'ctrl-btn btn-resume';
        btn.onclick = function(){ applyControl('resume'); };
      } else {
        btn.textContent = '⏸ Pause Bot';
        btn.className = 'ctrl-btn btn-pause';
        btn.onclick = function(){ applyControl('pause'); };
      }
    } catch(e) {}
  };
})();
</script>
</body>
</html>`;
}

// ── Validare setări (server-side) ─────────────────────────
const CTRL_VALIDATORS = {
  SYMBOL:          v => typeof v === 'string' && /^[A-Z]{3,12}$/.test(v.trim()),
  STRATEGY_MODE:   v => ['auto','turtle','livermore','soros','ptj','druckenmiller'].includes(v),
  RISK_PER_TRADE:  v => typeof v === 'number' && v > 0 && v <= 0.5,
  STOP_LOSS_PCT:   v => typeof v === 'number' && v > 0 && v <= 0.5,
  TAKE_PROFIT_PCT: v => typeof v === 'number' && v > 0 && v <= 1.0,
  MIN_CONFIDENCE:  v => typeof v === 'number' && v >= 50 && v <= 99,
  MIN_CRITERIA:    v => typeof v === 'number' && v >= 1 && v <= 5,
};

function readBody(req) {
  return new Promise((resolve, reject) => {
    let raw = '';
    req.on('data', c => { raw += c; if (raw.length > 4096) reject(new Error('too large')); });
    req.on('end', () => { try { resolve(JSON.parse(raw)); } catch { reject(new Error('invalid JSON')); } });
    req.on('error', reject);
  });
}

// ─── HTTP server ──────────────────────────────────────────
function serve(getData, logger, controls) {
  controls = controls || {};
  const PORT  = parseInt(process.env.PORT || process.env.DASHBOARD_PORT || '3000');
  const TOKEN = process.env.DASHBOARD_TOKEN || '';
  if (!TOKEN) {
    console.warn('⚠️  DASHBOARD_TOKEN not set — dashboard is PUBLIC on the Railway URL.');
  }

  http.createServer(async (req, res) => {
    if (req.url.startsWith('/health')) {
      res.writeHead(200, { 'Content-Type': 'text/plain' });
      res.end('ok');
      return;
    }

    if (TOKEN) {
      const url    = new URL(req.url, 'http://localhost');
      const bearer = (req.headers.authorization || '').replace(/^Bearer\s+/i, '');
      if (url.searchParams.get('token') !== TOKEN && bearer !== TOKEN) {
        res.writeHead(401, { 'Content-Type': 'text/plain' });
        res.end('Unauthorized — open with ?token=YOUR_DASHBOARD_TOKEN');
        return;
      }
    }

    const json = ct => res.writeHead(200, { 'Content-Type': 'application/json' });

    // POST /api/settings — change a live setting
    if (req.method === 'POST' && req.url.startsWith('/api/settings')) {
      try {
        const { key, value } = await readBody(req);
        const validate = CTRL_VALIDATORS[key];
        if (!validate) { json(); res.end(JSON.stringify({ ok: false, error: 'Unknown key' })); return; }
        const coerced = (key === 'SYMBOL' || key === 'STRATEGY_MODE') ? String(value).trim() : Number(value);
        if (!validate(coerced)) { json(); res.end(JSON.stringify({ ok: false, error: 'Value out of range' })); return; }
        if (controls.set) controls.set(key, coerced);
        logger.info(`⚙️  Dashboard: ${key} → ${coerced}`);
        json(); res.end(JSON.stringify({ ok: true }));
      } catch (e) {
        json(); res.end(JSON.stringify({ ok: false, error: e.message }));
      }
      return;
    }

    // POST /api/control — pause or resume
    if (req.method === 'POST' && req.url.startsWith('/api/control')) {
      try {
        const { action } = await readBody(req);
        if (action === 'pause' && controls.pause)        { controls.pause();  logger.info('⏸️  Dashboard: bot paused.'); }
        else if (action === 'resume' && controls.resume) { controls.resume(); logger.info('▶️  Dashboard: bot resumed.'); }
        else { json(); res.end(JSON.stringify({ ok: false, error: 'Unknown action' })); return; }
        json(); res.end(JSON.stringify({ ok: true }));
      } catch (e) {
        json(); res.end(JSON.stringify({ ok: false, error: e.message }));
      }
      return;
    }

    const data = getData();
    if (req.url.startsWith('/api/status')) {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(data));
      return;
    }

    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
    res.end(buildDashboard(data));
  }).listen(PORT, () => logger.info(`📊 Dashboard: http://localhost:${PORT}${TOKEN ? ' (token protected)' : ''}`));
}

module.exports = buildDashboard;
module.exports.serve = serve;
