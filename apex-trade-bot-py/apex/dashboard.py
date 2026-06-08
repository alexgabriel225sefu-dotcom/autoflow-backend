"""Minimal live dashboard HTML (self-refreshing via /api/status)."""
import html


def render(dash):
    op = dash.get("openPosition")
    pos_html = "<p class='muted'>No open position</p>"
    if op:
        side = "LONG" if op["side"] == "BUY" else "SHORT"
        pnl = op.get("currentPnl", 0)
        cls = "up" if pnl >= 0 else "down"
        pos_html = (f"<div class='pos'><b>{side} {html.escape(str(op.get('symbol', '')))}</b> "
                    f"@ ${op['entryPrice']} · PnL <span class='{cls}'>{'+' if pnl >= 0 else ''}${pnl:.4f}</span></div>")

    rows = ""
    for t in dash.get("trades", [])[:15]:
        cls = "up" if t.get("win") else "down"
        rows += (f"<tr><td>{html.escape(str(t.get('time', '')))}</td><td>{html.escape(str(t.get('symbol', '')))}</td>"
                 f"<td>{t.get('side')}</td><td>${t.get('entry')}</td><td>${t.get('exit')}</td>"
                 f"<td class='{cls}'>{'+' if t.get('pnl', 0) >= 0 else ''}${t.get('pnl')}</td>"
                 f"<td>{html.escape(str(t.get('reason', '')))}</td></tr>")
    if not rows:
        rows = "<tr><td colspan='7' class='muted'>No closed trades yet</td></tr>"

    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Apex Trade Bot — Dashboard</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0;font-family:system-ui,sans-serif}}
body{{background:#0b0b0e;color:#eaecef;padding:24px}}
.wrap{{max-width:900px;margin:0 auto}}
h1{{font-size:20px;margin-bottom:4px}}
.muted{{color:#6c6f78}}.up{{color:#27c46a}}.down{{color:#f0616d}}
.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:18px 0}}
.card{{background:#15171c;border:1px solid rgba(255,255,255,.07);border-radius:12px;padding:16px}}
.card b{{font-size:22px;display:block}}.card span{{font-size:12px;color:#6c6f78}}
.pos{{background:#15171c;border:1px solid rgba(255,255,255,.07);border-radius:12px;padding:14px;margin-bottom:14px}}
table{{width:100%;border-collapse:collapse;background:#15171c;border-radius:12px;overflow:hidden}}
th,td{{padding:10px 12px;text-align:left;font-size:13px;border-bottom:1px solid rgba(255,255,255,.05)}}
th{{color:#6c6f78;font-weight:500}}
</style></head><body><div class="wrap">
<h1>⚡ Apex Trade Bot</h1>
<p class="muted">{html.escape(str(dash.get('mode', '')))} · {html.escape(str(dash.get('exchange', '')))} · tick #{dash.get('tickCount', 0)} · {html.escape(str(dash.get('lastTick', '—')))}</p>
<div class="cards">
  <div class="card"><b>${dash.get('balance', 0):.2f}</b><span>Balance</span></div>
  <div class="card"><b>{html.escape(str(dash.get('currentSymbol', '')))}</b><span>Symbol</span></div>
  <div class="card"><b>${dash.get('currentPrice', 0)}</b><span>Price</span></div>
  <div class="card"><b>{len(dash.get('trades', []))}</b><span>Closed trades</span></div>
</div>
{pos_html}
<table><thead><tr><th>Time</th><th>Symbol</th><th>Side</th><th>Entry</th><th>Exit</th><th>PnL</th><th>Reason</th></tr></thead>
<tbody>{rows}</tbody></table>
</div>
<script>setTimeout(()=>location.reload(),15000);</script>
</body></html>"""
