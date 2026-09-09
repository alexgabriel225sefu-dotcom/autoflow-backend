"""A trade detail screen must show measurements, not calculations dressed as them.

R multiple and duration are the two numbers a trader reads hardest, and both
are derivable — which is exactly why they are dangerous. An R computed from a
stop distance the platform never recorded, sitting beside a real P&L, is
indistinguishable from a second measurement. So both are derived on the server
from the trade's OWN recorded fields and returned null when those are absent,
and the screen renders "Not recorded" rather than a number.

The timeline has the same shape of failure in a different place: an empty event
list means the decision log holds nothing for that window — the trade predates
the log, or nothing was written. It never means the decision had no reason.

Run: python tests/test_trade_detail.py
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

failures = []


def check(name, cond, detail=""):
    print(f"  OK   {name}" if cond else f"  FAIL {name} {detail}")
    if not cond:
        failures.append(name)


BOT = open(os.path.join(ROOT, "apex", "bot.py"), encoding="utf-8").read()
HTML = open(os.path.join(ROOT, "apex", "static", "terminal.html"), encoding="utf-8").read()
ROUTE = BOT[BOT.index('if self.path.startswith("/api/app/trade")'):]
ROUTE = ROUTE[:ROUTE.index('if self.path.startswith("/api/app/symbol")')]
CODE = "\n".join(l for l in ROUTE.splitlines() if not l.strip().startswith("#"))

print("\n1. The trade id resolves only inside the asker's own journal")
check("find_trade is the lookup", "_t_api.find_trade(_t_chat, _t_id)" in CODE)
check("...and it is passed the chat from the signature",
      '_t_chat = str(_t_user["id"])' in CODE)
check("identity is checked before the lookup",
      CODE.index("_telegram_identity") < CODE.index("find_trade"))
check("a denied caller is refused", "_telegram_denied" in CODE)
check("the id is length-clamped", "[:64]" in CODE)
check("a missing id is refused, not defaulted", "NO_TRADE_ID" in CODE)
check("an unknown id is a 404, not an empty trade", "TRADE_NOT_FOUND" in CODE)

print("\n2. R multiple is derived from the trade's own record, or omitted")
check("R needs entry, exit AND the recorded stop distance",
      "_t_entry is not None and _t_exit is not None and _t_slp" in CODE,
      "without the stop distance there is no R to compute")
check("R starts as None", "_t_r = None" in CODE)
check("a failed derivation leaves it None",
      re.search(r"except Exception:\s*\n\s*_t_r = None", CODE) is not None)
check("the pip distance comes from the forex helper, not arithmetic here",
      "_t_fx.to_pips(" in CODE)
check("the sign follows the recorded P&L", "_t_sign" in CODE)
check("the screen renders an absent R as absent",
      "t.rMultiple==null" in HTML and "Not recorded" in HTML)

print("\n3. Duration is measured, not assumed")
check("it needs both timestamps", "_t_a and _t_b and _t_b >= _t_a" in CODE)
check("it is None otherwise", "_t_dur = None" in CODE)
check("the screen renders an absent duration as absent",
      "dur==null" in HTML)

print("\n4. An empty timeline is stated, never filled in")
check("the payload says whether events were recorded",
      '"eventsRecorded": bool(_t_events)' in CODE)
check("the window is anchored to the trade's own timestamps",
      "start_ts=_t_from - 900" in CODE)
check("...and to its position id", "position_id=_t_row.get(\"positionId\")" in CODE)
check("...and its symbol", 'symbol=_t_row.get("symbol")' in CODE)
check("the screen words an empty log as unrecorded",
      "No recorded decision events for this trade" in HTML)
check("...and says nothing is reconstructed",
      "nothing is reconstructed" in HTML)
check("each event shows the strategy version that produced it",
      "ev.strategy_version" in HTML)

print("\n5. Nothing financial happens here")
check("no order path is reachable",
      not any(x in CODE for x in ("place_order", "force_close", "authorize_order",
                                  "authorize_close", "_make_broker")))
check("no settings are written", "user_store.update" not in CODE)

print("\n6. Filters reuse the rows the server already sent")
check("drawing is separate from fetching", "function drawHistory(rows)" in HTML)
check("the filter draws from the cache", "let rows=(histCache||[]).slice()" in HTML)
check("no filter re-queries the server",
      "applyHistFilter" in HTML
      and "/api/app/history" not in HTML.split("function applyHistFilter")[1].split("}")[0],
      "filtering must never become a reason to re-query")
for f in ("all", "wins", "losses", "best", "open", "closed"):
    check(f"the {f!r} filter exists", f'data-hf="{f}"' in HTML)
check("a symbol filter exists", 'id="histSearch"' in HTML)
check("a date filter exists", 'id="histDate"' in HTML)
check("the Open filter says where open positions actually live",
      "Open positions live in Portfolio" in HTML,
      "this journal holds closed trades; a filter returning the same list "
      "silently would be worse than one that explains itself")
check("an empty filter result is worded, not blank",
      "No trades match this filter" in HTML)
check("an empty library is worded differently from an empty filter",
      "Your completed trades will appear here" in HTML)

print("\n7. History is paged, not downloaded whole")
check("the first request is bounded", "'/api/app/history?limit='+HIST_PAGE" in HTML)
check("...and asks for an offset", "&offset=0" in HTML)
check("more pages are fetched from where the last one ended",
      "'&offset='+histCache.length" in HTML)
check("the server's total is what decides whether there are more",
      "histCache.length >= histTotal" in HTML)
check("a second request cannot start while one is running",
      "if(histLoading" in HTML,
      "two overlapping pages would append the same rows twice")
check("load-more is hidden under every filter",
      "histFilter==='all' && !histSearch && !histDate && histCache.length < histTotal"
      in HTML,
      "a button under a filtered list suggests the FILTER is incomplete")
check("the server caps the page size itself",
      "min(int(limit or 25), HISTORY_PAGE_MAX)" in
      open(os.path.join(ROOT, "apex", "miniapp_api.py"), encoding="utf-8").read(),
      "a client asking for ten thousand must not get them")

print("\n8. A history row opens the trade, and the trade offers the replay")
check("a row opens trade detail", "openTrade(r.dataset.t)" in HTML)
check("trade detail exists", 'id="s-trade"' in HTML and 'id="tradeBody"' in HTML)
check("replay is reachable from it", "openReplay(id)" in HTML)

print("\n9. No route local can shadow the enclosing scope")
_locals = {m.group(1) for m in re.finditer(r'^\s+([a-z][\w]*) = (?!=)', CODE, re.M)}
check(f"every local is prefixed ({sorted(_locals)})", not _locals,
      "do_GET shares a scope; a bare name here breaks a branch elsewhere")

print("\n" + "=" * 50)
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:8])}")
    sys.exit(1)
print("ALL TRADE-DETAIL CHECKS PASSED - derived numbers admit when they are not there.")
