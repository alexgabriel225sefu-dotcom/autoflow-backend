/**
 * APEX TRADE BOT — Premium Dashboard HTML + HTTP server
 */
const http = require('http');

function buildDashboard(dash) {
  const sym      = dash.currentSymbol || 'SOLUSDT';
  const exch     = (dash.exchange || 'BINANCE').toUpperCase();
  const tvSym    = `${exch === 'BYBIT' ? 'BYBIT' : 'BINANCE'}:${sym}`;
  const bal      = (dash.balance || 0).toFixed(2);
  const price    = dash.currentPrice > 0 ? '$' + dash.currentPrice.toFixed(4) : '—';
  const pnlNum   = dash.startBalance > 0
    ? ((dash.balance - dash.startBalance) / dash.startBalance * 100) : 0;
  const pnlPct   = pnlNum.toFixed(2);
  const pnlSign  = pnlNum >= 0 ? '+' : '';
  const pnlClass = pnlNum >= 0 ? 'green' : 'red';
  const wins     = (dash.trades || []).filter(t => t.win).length;
  const total    = (dash.trades || []).length;
  const losses   = total - wins;
  const winRate  = total > 0 ? ((wins / total) * 100).toFixed(0) + '%' : '—';
  const mode     = dash.mode || 'PAPER';
  const tick     = dash.tickCount || 0;
  const lastTick = dash.lastTick || '—';

  // ── Active Position ──────────────────────────────────────
  let posHtml = `<div class="pos-empty">⏳ No open position — waiting for signal...</div>`;
  if (dash.openPosition) {
    const p      = dash.openPosition;
    const isLong = p.side === 'BUY';
    const dir    = isLong ? '▲ LONG' : '▼ SHORT';
    const pnl    = p.currentPnl || 0;
    const ps     = pnl >= 0 ? '+' : '';
    const pc     = pnl >= 0 ? 'green' : 'red';
    // SL/TP progress (how close price is between entry and TP)
    const range  = Math.abs((p.takeProfit || p.entryPrice) - (p.stopLoss || p.entryPrice));
    const dist   = range > 0 ? Math.abs((dash.currentPrice || p.entryPrice) - (p.stopLoss || p.entryPrice)) : 0;
    const prog   = Math.min(100, Math.max(0, (dist / range) * 100)).toFixed(0);
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

  // ── Trade history rows ───────────────────────────────────
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
:root{--bg:#050814;--card:#0b1120;--border:#1a2540;--text:#e5e7eb;--muted:#6b7280;--amber:#f59e0b;--green:#00e87a;--red:#ff4d6d;--blue:#60a5fa}
body{background:var(--bg);color:var(--text);font-family:'Inter','Segoe UI',system-ui,sans-serif;min-height:100vh}
/* Header */
.hdr{display:flex;align-items:center;justify-content:space-between;padding:12px 18px;border-bottom:1px solid var(--border);background:linear-gradient(135deg,#0b1120,#050814);position:sticky;top:0;z-index:99;backdrop-filter:blur(10px)}
.logo{display:flex;align-items:center;gap:8px}
.logo-icon{width:22px;height:22px;fill:none;stroke:var(--amber);stroke-width:2.5;stroke-linecap:round;stroke-linejoin:round}
.logo-text{font-weight:800;font-size:.95rem;letter-spacing:-.01em;color:#fff}
.status-badge{display:flex;align-items:center;gap:6px;background:rgba(0,232,122,.08);border:1px solid rgba(0,232,122,.2);border-radius:20px;padding:4px 10px;font-size:.68rem;font-weight:700;color:var(--green);letter-spacing:.04em}
.dot{width:6px;height:6px;border-radius:50%;background:var(--green);animation:blink 2s infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.3}}
/* Metrics */
.metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:var(--border)}
.m{background:var(--card);padding:12px 10px;text-align:center}
.m-l{font-size:.6rem;color:var(--muted);text-transform:uppercase;letter-spacing:.07em;margin-bottom:4px}
.m-v{font-size:1.05rem;font-weight:800;line-height:1}
/* Colors */
.green{color:var(--green)}.red{color:var(--red)}.amber{color:var(--amber)}.blue{color:var(--blue)}.muted{color:var(--muted)}.white{color:#fff}
/* Chart */
.chart-wrap{background:#000;border-bottom:1px solid var(--border)}
.chart-wrap iframe{display:block;width:100%;height:430px;border:0}
/* Section */
.sec{padding:14px 16px;border-bottom:1px solid var(--border)}
.sec-title{font-size:.65rem;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);margin-bottom:10px}
/* Position */
.pos-empty{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:18px;text-align:center;color:var(--muted);font-size:.82rem}
.pos-card{border-radius:10px;padding:14px}
.pos-card.long{background:rgba(0,232,122,.05);border:1px solid rgba(0,232,122,.18)}
.pos-card.short{background:rgba(255,77,109,.05);border:1px solid rgba(255,77,109,.18)}
.pos-row{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}
.pos-dir{font-weight:800;font-size:.9rem}
.pos-pnl{font-weight:800;font-size:1.05rem}
.pos-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px}
.pi{display:flex;flex-direction:column;gap:2px}
.pi-l{font-size:.6rem;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
.pi-v{font-weight:700;font-size:.83rem;color:#fff}
.prog-wrap{margin-top:2px}
.prog-bar{height:3px;background:var(--border);border-radius:2px;overflow:hidden;margin-bottom:4px}
.prog-fill{height:100%;background:linear-gradient(90deg,var(--red),var(--amber),var(--green));border-radius:2px;transition:width .5s}
.prog-labels{display:flex;justify-content:space-between;font-size:.6rem;font-weight:700}
/* Table */
.tbl-wrap{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:.74rem}
th{color:var(--muted);font-size:.6rem;font-weight:600;padding:7px 6px;border-bottom:1px solid var(--border);text-align:left;text-transform:uppercase;letter-spacing:.06em}
td{padding:7px 6px;border-bottom:1px solid rgba(255,255,255,.03)}
tr.win td{color:#d1fae5}tr.loss td{color:#fee2e2}
.empty-row td{color:var(--muted);text-align:center;padding:20px;font-size:.8rem}
/* Stats row */
.stats-row{display:flex;gap:16px;padding:10px 16px;border-bottom:1px solid var(--border);font-size:.75rem}
.stat{display:flex;flex-direction:column;gap:2px}
.stat-l{font-size:.6rem;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}
.stat-v{font-weight:700}
/* Footer */
.footer{padding:10px 16px;font-size:.65rem;color:var(--muted);text-align:center}
@media(max-width:480px){.metrics{grid-template-columns:repeat(2,1fr)}.chart-wrap iframe{height:340px}}
</style>
<script>setTimeout(()=>location.reload(),30000)</script>
</head>
<body>

<header class="hdr">
  <div class="logo">
    <svg class="logo-icon" viewBox="0 0 24 24"><polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/></svg>
    <span class="logo-text">Apex Trade Bot</span>
  </div>
  <div class="status-badge"><span class="dot"></span>LIVE · ${mode}</div>
</header>

<div class="metrics">
  <div class="m"><div class="m-l">Balance</div><div class="m-v green">$${bal}</div></div>
  <div class="m"><div class="m-l">Total PnL</div><div class="m-v ${pnlClass}">${pnlSign}${pnlPct}%</div></div>
  <div class="m"><div class="m-l">Win Rate</div><div class="m-v amber">${winRate}</div></div>
  <div class="m"><div class="m-l">Trades</div><div class="m-v blue">${total}</div></div>
  <div class="m"><div class="m-l">W / L</div><div class="m-v white">${wins} / ${losses}</div></div>
  <div class="m"><div class="m-l">${sym}</div><div class="m-v white">${price}</div></div>
</div>

<div class="chart-wrap">
  <iframe src="https://www.tradingview.com/widgetembed/?frameElementId=tv&symbol=${tvSym}&interval=5&theme=dark&style=1&timezone=Etc%2FUTC&withdateranges=1&hide_side_toolbar=0&allow_symbol_change=0&save_image=0&studies=RSI%401%2CMASimple%401%2CMACD%40tv-basicstudies&calendar=0&support_host=https%3A%2F%2Fwww.tradingview.com" allowtransparency="true" scrolling="no"></iframe>
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

<div class="footer">Auto-refresh 30s · Tick #${tick} · Last: ${lastTick} · ${exch}</div>
</body>
</html>`;
}

// ─── HTTP server cu auth opțional prin token ──────────────
// DASHBOARD_TOKEN setat → balanța/istoricul nu mai sunt publice pe internet.
function serve(getData, logger) {
  const PORT  = parseInt(process.env.PORT || process.env.DASHBOARD_PORT || '3000');
  const TOKEN = process.env.DASHBOARD_TOKEN || '';
  if (!TOKEN) {
    console.warn('⚠️  DASHBOARD_TOKEN not set — dashboard (balance + history) is PUBLIC on the Railway URL.');
  }
  http.createServer((req, res) => {
    // Railway healthcheck — fără auth, nu expune date
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
    const data = getData();
    if (req.url.startsWith('/api/status')) {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(data));
      return;
    }
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
    res.end(buildDashboard(data));
  }).listen(PORT, () => logger.info(`📊 Dashboard: http://localhost:${PORT}${TOKEN ? ' (protejat cu token)' : ''}`));
}

module.exports = buildDashboard;
module.exports.serve = serve;
