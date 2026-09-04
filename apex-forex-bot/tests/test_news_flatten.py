"""A position must not be carried into a high-impact release it can see coming.

The news guard only ever gated ENTRIES. It set `entry_ok = False` and did
nothing at all about a position that was already open, so a trade taken hours
earlier rode straight through the print.

What that cost the live account on 2026-09-04:

  * EURUSD BUY opened 00:03:12 UTC, USDCHF SELL opened 00:08:51 UTC.
  * 12:05:38 the bot itself logged NEWS_AHEAD for 'Non-Farm Employment
    Change' with 'guarded': True — 24 minutes' warning, acted on for entries
    and nothing else.
  * NFP printed 12:30:00. EURUSD closed 12:31:01, USDCHF 12:31:36.
  * EURUSD entry 1.16293, stop already trailed to 1.160768 (21.6 pips below
    entry), actual exit 1.15966 — 32.7 pips below entry. The stop was blown
    through by 11.1 pips, a 51% overshoot.
  * Combined -116.67, which is 34% of the account's recent losses.

A stop is a price you hope to be filled at. Around NFP/CPI/FOMC it is not one,
which is exactly what the entry guard's own comment already said.

Two properties are tested harder than the rest, because getting either wrong
is worse than the bug:

  FAIL-OPEN. No event, an unreadable calendar, an unknown position list, a
  symbol that parses to no currency, or any exception at all → nothing is
  closed. Flattening a client's account because a feed hiccuped is a worse
  failure than the one being fixed.

  HONEST. Every close passes gates.authorize_close, and a close the broker
  never confirmed is never journalled, never books a P&L and never tells the
  client they are flat — the same three rules test_weekend_flatten pins on the
  weekend path.

Run: python tests/test_news_flatten.py
"""
import importlib
import os
import re
import sys
import tempfile
import time
import types
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Tests are a development environment and say so explicitly: user_store now
# REFUSES to start without TOKEN_ENCRYPTION_KEY rather than falling back to
# plaintext, and that refusal is the behaviour under test elsewhere.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-newsflat-")
os.environ.pop("UPSTASH_REDIS_REST_URL", None)
os.environ.pop("UPSTASH_REDIS_REST_TOKEN", None)

from apex import alert_policy               # noqa: E402
from apex import config as appcfg           # noqa: E402
from apex import news                       # noqa: E402
from apex import telegram as tg             # noqa: E402
from apex import user_loop                  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOOP = open(os.path.join(ROOT, "apex", "user_loop.py"), encoding="utf-8").read()

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


def _evt(title, ccy, mins_ahead, impact="High"):
    """One calendar row, `mins_ahead` minutes from now (negative = released)."""
    t = datetime.now(timezone.utc) + timedelta(minutes=mins_ahead)
    return {"title": title, "currency": ccy, "impact": impact,
            "time": t.isoformat(), "forecast": None, "previous": None,
            "actual": None}


def _calendar(*rows):
    """Seed the module cache so no lookup touches the network."""
    news._cache["events"] = list(rows)
    news._cache["ts"] = time.time()


NFP = "Non-Farm Employment Change"


print("\n── the calendar question an OPEN position asks ──")
# The release the live account was carried into, seen from a tick ten minutes
# before it landed.
_calendar(_evt(NFP, "USD", 10))
hit = news.next_high_impact(["EUR", "USD"], 15)
check("a release 10 min ahead is found within a 15 min lead",
      bool(hit) and hit["title"] == NFP, str(hit))
check("and it reports how far away it is", bool(hit) and hit["mins"] <= 10,
      str(hit))
check("USDCHF is exposed to the same USD print",
      bool(news.next_high_impact(["USD", "CHF"], 15)))

_calendar(_evt(NFP, "USD", 25))
check("a release beyond the lead time is not acted on yet",
      news.next_high_impact(["EUR", "USD"], 15) is None)

# THE asymmetry. high_impact_window() is symmetric ±window and is right for an
# entry: the minutes after a print are as untradeable as the ones before. For a
# position already open it is wrong — closing after the print books the move
# instead of avoiding it.
_calendar(_evt(NFP, "USD", -5))
check("a release that already happened is NOT a reason to close",
      news.next_high_impact(["EUR", "USD"], 15) is None,
      "closing after the print books the move it was meant to avoid")
check("while the entry guard still stands aside in the aftermath",
      bool(news.high_impact_window(["EUR", "USD"], 15)),
      "the entry guard must stay symmetric — this is a different question")

_calendar(_evt("BOJ Policy Rate", "JPY", 10))
check("a release on another currency is ignored",
      news.next_high_impact(["EUR", "USD"], 15) is None)

_calendar(_evt("Flash Manufacturing PMI", "USD", 10, impact="Medium"))
check("a medium-impact release is not worth closing for",
      news.next_high_impact(["EUR", "USD"], 15) is None)

print("\n── fail-open: nothing is closed on absent or broken data ──")
_calendar()
check("an empty calendar closes nothing",
      news.next_high_impact(["EUR", "USD"], 15) is None)

_calendar(_evt(NFP, "USD", 10))
_orig_load = news._load
news._load = lambda: (_ for _ in ()).throw(RuntimeError("feed down"))
try:
    check("a calendar that raises closes nothing",
          news.next_high_impact(["EUR", "USD"], 15) is None)
finally:
    news._load = _orig_load

os.environ["NEWS_GUARD"] = "false"
try:
    check("NEWS_GUARD=false closes nothing",
          news.next_high_impact(["EUR", "USD"], 15) is None)
finally:
    os.environ.pop("NEWS_GUARD", None)

check("a zero lead time closes nothing",
      news.next_high_impact(["EUR", "USD"], 0) is None)


print("\n── the loop's per-position decision ──")
ON = types.SimpleNamespace(NEWS_FILTER=True, NEWS_EXIT_MIN=15)

_calendar(_evt(NFP, "USD", 10))
check("EURUSD, open into NFP → close it",
      (user_loop._news_exit_due(ON, "EURUSD") or {}).get("title") == NFP)
check("USDCHF, the second position that day → close it too",
      (user_loop._news_exit_due(ON, "USDCHF") or {}).get("title") == NFP)
check("AUDNZD, exposed to neither leg → left alone",
      user_loop._news_exit_due(ON, "AUDNZD") is None)
check("a symbol that parses to no currency is left alone",
      user_loop._news_exit_due(ON, "US30") is None
      and user_loop._news_exit_due(ON, "") is None
      and user_loop._news_exit_due(ON, None) is None)

OFF_USER = types.SimpleNamespace(NEWS_FILTER=False, NEWS_EXIT_MIN=15)
check("a client who turned the news guard off is not flattened",
      user_loop._news_exit_due(OFF_USER, "EURUSD") is None,
      "news_filter is the client saying what they want")

OFF_OPERATOR = types.SimpleNamespace(NEWS_FILTER=True, NEWS_EXIT_MIN=0)
check("the operator can switch it off without a deploy",
      user_loop._news_exit_due(OFF_OPERATOR, "EURUSD") is None)

_orig_next = user_loop.news.next_high_impact
user_loop.news.next_high_impact = lambda *a, **k: (_ for _ in ()).throw(
    RuntimeError("calendar exploded"))
try:
    check("any exception leaves the position running",
          user_loop._news_exit_due(ON, "EURUSD") is None)
finally:
    user_loop.news.next_high_impact = _orig_next

check("a config with no lead time at all is off, not defaulted on",
      user_loop._news_exit_due(types.SimpleNamespace(), "EURUSD") is None,
      "an absent setting must never be read as 'flatten'")


print("\n── the close goes through the one gate every close passes ──")
_NB_START = LOOP.index("_news_closed, _news_failed, _news_event = [], [], None")
_nb = LOOP[_NB_START:LOOP.index("stop_check = strategies.should_stop(", _NB_START)]

check("the block exists at all", len(_nb) > 400, f"{len(_nb)} chars")
check("the gate is asked before the broker is touched",
      "gates.authorize_close(" in _nb and "broker.close_position(" in _nb
      and _nb.index("gates.authorize_close(") < _nb.index("broker.close_position("))
check("the decision is audited, refused or not", "gates.audit(" in _nb)
check("it names its own origin, so the audit says which control fired",
      'origin="news_exit"' in _nb)
check("a refused gate is checked before the broker and before the journal",
      "if not _nd:" in _nb
      and _nb.index("if not _nd:") < _nb.index("broker.close_position(")
      and _nb.index("if not _nd:") < _nb.index("_log_trade("))
check("the broker's confirmation is recorded against the intent",
      "ledger.record(" in _nb)

print("\n── a close the broker never confirmed is not an exit ──")
check("the broker error is not swallowed by a bare pass",
      not re.search(r"except Exception[^\n]*:\s*\n\s*pass", _nb),
      "bare pass in the news exit")
check("the failure is logged", "FAILED" in _nb)
_fail_sites = [m.start() for m in re.finditer(r"_news_failed\.append\(_nsym\)", _nb)]
check("both ways a close can fail — refused by the gate, refused by the "
      "broker — skip the accounting entirely",
      len(_fail_sites) == 2
      and all("continue" in _nb[i:i + 160] for i in _fail_sites),
      f"{len(_fail_sites)} failure site(s)")
check("an already-flat position is not journalled either",
      '(_nclose or {}).get("status") == "FLAT"' in _nb)
check("only a real close is journalled",
      _nb.index("_log_trade(") > _nb.index("broker.close_position("))

print("\n── every exposed position, not just the focused one ──")
# The weekend flatten shipped closing only the FOCUSED symbol while telling the
# client they were flat. Both positions that day were exposed to the same USD
# print, and only one of them was the loop's focus.
check("it walks the account's positions", "for _np, _nev in _news_due:" in _nb)
check("it closes each position's own symbol",
      "broker.close_position(_nsym)" in _nb)
check("and files the close under that symbol", '"symbol": _nsym' in _nb)
check("the stats are credited to it too", "symbol=_nsym" in _nb)
check("the focus price is not used to value another instrument",
      "_nrm(_nsym) == _nrm(symbol)" in _nb)
check("an unknown position list closes nothing",
      "elif all_positions:" in _nb,
      "all_positions is None when the read failed — that is not 'flat'")

print("\n── it is position management, not an entry gate ──")
check("the exit never consults entry_ok", "entry_ok" not in _nb,
      "an open position is closed whether or not a setup exists this tick")
check("the whole block is fail-open around any exception",
      "except Exception as _ne:" in _nb)
check("and says so in the log rather than dying quietly",
      "news exit check failed" in _nb)


print("\n── the block RUN, not just read ──")
# The weekend flatten could only ever be checked by reading its source: it is
# inline in a two-thousand-line loop. This one is a single self-contained
# `try:` statement, so it can be lifted out and EXECUTED against stubs — which
# is the difference between "the gate call is written above the broker call"
# and "a refused gate really does leave the position open".
import textwrap  # noqa: E402

_BLOCK = compile(textwrap.dedent(LOOP[LOOP.rindex("\n", 0, _NB_START) + 1:
                                      LOOP.index("            # Check risk limits "
                                                 "(per-user, from the Strategy "
                                                 "Builder)")]),
                 "<news-exit-block>", "exec")


class _Decision:
    def __init__(self, ok, reason="AUTHORIZED"):
        self.ok, self.reason, self.detail = ok, reason, ""

    def __bool__(self):
        return self.ok


class _Recorder:
    """Every side effect the block can have, counted."""

    def __init__(self, *, gate=True, close_raises=(), load_raises=False,
                 journal_raises=False):
        self.gate_ok, self.close_raises = gate, set(close_raises)
        self.load_raises, self.journal_raises = load_raises, journal_raises
        self.gated, self.closed, self.recorded = [], [], []
        self.journalled, self.alerts, self.snapshots = [], [], []

    # gates
    def authorize_close(self, uid, position_id=None, symbol=None, origin=None,
                        user=None, emergency=False):
        self.gated.append((symbol, origin))
        return (_Decision(self.gate_ok, "AUTHORIZED" if self.gate_ok
                          else "DUPLICATE_CLOSE"), f"rid-{symbol}")

    def audit(self, *a, **k):
        pass

    # broker
    def close_position(self, sym):
        if sym in self.close_raises:
            raise RuntimeError("broker said no")
        self.closed.append(sym)
        return {"status": "FILLED", "fillPrice": 1.15966}

    def get_balance(self):
        return 883.33

    # ledger / journal / store
    def record(self, rid, res):
        self.recorded.append(rid)

    def log_trade(self, uid, result, pos=None):
        if self.journal_raises:
            raise RuntimeError("journal unwritable")
        self.journalled.append(result)
        return True

    def load(self, uid):
        if self.load_raises:
            raise RuntimeError("store unreachable")
        return {}

    def update(self, *a, **k):
        pass

    def record_trade(self, *a, **k):
        pass


def _run_block(rec, *, positions, tracked=None, paper=False,
               news_filter=True, lead=15):
    """Execute the loop's news-exit block against stubs. Returns its namespace."""
    _pos = None if positions is None else list(positions)
    ns = {
        "cfg": types.SimpleNamespace(PAPER_TRADING=paper,
                                     NEWS_FILTER=news_filter,
                                     NEWS_EXIT_MIN=lead),
        "all_positions": _pos,
        "open_pos": tracked if tracked is not None else (_pos or [None])[0],
        "symbol": "EURUSD", "price": 1.15966, "user_id": "1",
        "now_str": "2026-09-04 12:20:00",
        "paper_balance": 1000.0, "last_loss_at": 0.0, "last_close_at": 0.0,
        "loss_streak": 0,
        "prev_open_syms": {user_loop._nrm(p["symbol"]) for p in (_pos or [])},
        "dash": {"trades": [], "startBalance": 1000.0, "openPosition": None},
        "alert_fn": lambda uid, payload: rec.alerts.append(payload),
        "gates": types.SimpleNamespace(authorize_close=rec.authorize_close,
                                       audit=rec.audit),
        "ledger": types.SimpleNamespace(record=rec.record),
        "broker": types.SimpleNamespace(close_position=rec.close_position,
                                        get_balance=rec.get_balance),
        "user_store": types.SimpleNamespace(load=rec.load, update=rec.update),
        "strategies": types.SimpleNamespace(record_trade=rec.record_trade),
        "_log_trade": rec.log_trade,
        "_persist_risk_state": lambda: None,
        "_persist_open_snapshot": rec.snapshots.append,
        "_news_exit_due": user_loop._news_exit_due,
        "_nrm": user_loop._nrm,
        "forex": user_loop.forex,
        "realized_cost_usd": user_loop.realized_cost_usd,
        "time": time,
    }
    exec(_BLOCK, ns)
    return ns


EURUSD = {"symbol": "EURUSD", "side": "BUY", "entryPrice": 1.16293,
          "units": 1000, "positionId": "P1"}
USDCHF = {"symbol": "USDCHF", "side": "SELL", "entryPrice": 0.79800,
          "units": 1000, "positionId": "P2"}

# The live tick as it should have gone: 12:20 UTC, NFP ten minutes out, the two
# positions from just after midnight still open.
_calendar(_evt(NFP, "USD", 10))
r = _Recorder()
ns = _run_block(r, positions=[EURUSD, USDCHF])
check("both exposed positions are closed", r.closed == ["EURUSD", "USDCHF"],
      str(r.closed))
check("each one through the gate, under its own origin",
      r.gated == [("EURUSD", "news_exit"), ("USDCHF", "news_exit")], str(r.gated))
check("each confirmed close is recorded against its intent",
      len(r.recorded) == 2, str(r.recorded))
check("and journalled once each", len(r.journalled) == 2,
      [j.get("symbol") for j in r.journalled])
check("the journal says WHY, naming the release",
      all(NFP in (j.get("reasoning") or "") for j in r.journalled),
      str([j.get("reasoning") for j in r.journalled])[:160])
check("the tracked position is cleared", ns["open_pos"] is None)
_flat = [a for a in r.alerts if a["action"] == "NEWS_FLATTEN"]
check("one NEWS_FLATTEN message, after the attempts", len(_flat) == 1)
check("and it claims exactly what happened",
      _flat and _flat[0]["closed"] == ["EURUSD", "USDCHF"]
      and _flat[0]["failed"] == [], str(_flat))

# The 51% overshoot is what this exists to avoid, so the exit has to be priced
# off the broker's fill and booked against the right pair.
_e = [j for j in r.journalled if j["symbol"] == "EURUSD"][0]
check("the EURUSD exit is priced off the broker's own fill",
      _e["price"] == 1.15966, str(_e["price"]))
check("and its loss is booked, not invented", _e["netPnl"] < 0, str(_e["netPnl"]))

print("\n  · a broker that refuses one of them")
r = _Recorder(close_raises=["USDCHF"])
ns = _run_block(r, positions=[EURUSD, USDCHF])
check("the one that closed is journalled",
      [j["symbol"] for j in r.journalled] == ["EURUSD"],
      str([j["symbol"] for j in r.journalled]))
check("the one that did NOT close is journalled by nobody",
      not any(j["symbol"] == "USDCHF" for j in r.journalled))
check("its intent is not recorded as a close", len(r.recorded) == 1)
check("and the client is told it is still open",
      [a for a in r.alerts if a["action"] == "NEWS_FLATTEN"][0]["failed"]
      == ["USDCHF"])

print("\n  · a gate that refuses")
r = _Recorder(gate=False)
ns = _run_block(r, positions=[EURUSD, USDCHF])
check("the broker is never touched", r.closed == [], str(r.closed))
check("nothing is journalled", r.journalled == [])
check("and both are reported as still open",
      [a for a in r.alerts if a["action"] == "NEWS_FLATTEN"][0]["failed"]
      == ["EURUSD", "USDCHF"])

print("\n  · and every reason to do nothing")
_calendar(_evt(NFP, "USD", 90))          # release far away
r = _Recorder()
_run_block(r, positions=[EURUSD, USDCHF])
check("no release near → no gate, no close, no message",
      not r.gated and not r.closed and not r.alerts)

_calendar(_evt(NFP, "USD", 10))
r = _Recorder()
# The realistic shape of this: the loop still tracks a position and the
# broker's position read failed this tick. "Unknown" must not be resolved
# downwards into "just close the one I remember".
_run_block(r, positions=None, tracked=EURUSD)
check("an unknown position list → nothing is closed",
      not r.gated and not r.closed and not r.alerts,
      "None means the read failed, which is not 'flat'")

r = _Recorder()
_run_block(r, positions=[EURUSD], news_filter=False)
check("news_filter off → nothing is closed", not r.closed and not r.alerts)

r = _Recorder()
_run_block(r, positions=[EURUSD], lead=0)
check("NEWS_EXIT_MIN=0 → nothing is closed", not r.closed and not r.alerts)

r = _Recorder(load_raises=True)
_run_block(r, positions=[EURUSD, USDCHF])       # must not raise out of the tick
check("an exception before any close leaves everything alone, silently",
      not r.closed and not r.journalled and not r.alerts)

# The other half of that: the close DID reach the broker and the bookkeeping
# after it blew up. The money moved, so the client is told even though the
# journal row was lost — the alternative is a position closed in silence.
r = _Recorder(journal_raises=True)
_run_block(r, positions=[EURUSD, USDCHF])
check("a close that happened is still reported when the accounting raises",
      r.closed == ["EURUSD"]
      and [a for a in r.alerts if a["action"] == "NEWS_FLATTEN"]
      and [a for a in r.alerts
           if a["action"] == "NEWS_FLATTEN"][0]["closed"] == ["EURUSD"],
      f"closed={r.closed} alerts={[a['action'] for a in r.alerts]}")

_calendar(_evt(NFP, "USD", 10))
r = _Recorder()
ns = _run_block(r, positions=[EURUSD], paper=True)
check("paper accounts get the same protection",
      [j["symbol"] for j in r.journalled] == ["EURUSD"])
check("and their simulated balance moves with it",
      ns["paper_balance"] != 1000.0, str(ns["paper_balance"]))


print("\n── what the client is told ──")
check("NEWS_FLATTEN is ESSENTIAL — money moved",
      "NEWS_FLATTEN" in alert_policy.ESSENTIAL)
check("so /verbose off cannot hide it",
      alert_policy.allowed("NEWS_FLATTEN", {"verbose_alerts": False}))

sent = []
_orig_send = tg.send_to
tg.send_to = lambda cid, text, extra=None: sent.append(text)
try:
    del sent[:]
    tg._user_alert("1", {"action": "NEWS_FLATTEN", "symbol": "EURUSD",
                         "event": {"title": NFP, "currency": "USD", "mins": 9},
                         "closed": ["EURUSD", "USDCHF"], "failed": []})
    txt = " ".join(sent)
    check("it names the release that caused the close", NFP in txt, txt[:120])
    check("and which positions it closed",
          "EURUSD" in txt and "USDCHF" in txt, txt[:120])
    check("it does not claim anything is still open",
          "Still open" not in txt, txt[:120])

    del sent[:]
    tg._user_alert("1", {"action": "NEWS_FLATTEN", "symbol": "EURUSD",
                         "event": {"title": NFP, "currency": "USD", "mins": 9},
                         "closed": ["EURUSD"], "failed": ["USDCHF"]})
    txt = " ".join(sent)
    check("a position it could not close is the headline",
          "Still open" in txt and "USDCHF" in txt, txt[:160])
    check("and the client is told to handle it themselves",
          "cTrader" in txt, txt[:160])
finally:
    tg.send_to = _orig_send


print("\n── the setting reaches a live account ──")
check("the product config carries it", hasattr(appcfg, "NEWS_EXIT_MIN"))
check("it defaults to a 15 min lead", appcfg.NEWS_EXIT_MIN == 15.0,
      f"{getattr(appcfg, 'NEWS_EXIT_MIN', None)!r}")
check("which the 24 min of warning that day comfortably covers",
      appcfg.NEWS_EXIT_MIN <= 24)
check("and which spans several ticks at the live loop interval",
      appcfg.NEWS_EXIT_MIN * 60 >= 2 * user_loop._LOOP_INTERVAL,
      f"{appcfg.NEWS_EXIT_MIN}min vs {user_loop._LOOP_INTERVAL}s tick")

_, _cfg = user_loop._make_broker({"ctrader_access_token": "x",
                                  "ctrader_account_id": "1"})
check("the per-user config the loop reads carries it too",
      hasattr(_cfg, "NEWS_EXIT_MIN"),
      "missing → getattr() default wins and the env var does nothing")
check("and it tracks the product config",
      _cfg.NEWS_EXIT_MIN == appcfg.NEWS_EXIT_MIN,
      f"{getattr(_cfg, 'NEWS_EXIT_MIN', None)!r} vs {appcfg.NEWS_EXIT_MIN!r}")

_, _cfg_off = user_loop._make_broker({"ctrader_access_token": "x",
                                      "ctrader_account_id": "1",
                                      "news_filter": False})
check("a client's news_filter toggle still reaches it",
      _cfg_off.NEWS_FILTER is False)

os.environ["NEWS_EXIT_MIN"] = "0"
try:
    importlib.reload(appcfg)
    check("NEWS_EXIT_MIN=0 in the environment switches it off",
          appcfg.NEWS_EXIT_MIN == 0.0, repr(appcfg.NEWS_EXIT_MIN))
    _, _cfg_env = user_loop._make_broker({"ctrader_access_token": "x",
                                          "ctrader_account_id": "1"})
    check("and that reaches the loop without a code change",
          _cfg_env.NEWS_EXIT_MIN == 0.0, repr(_cfg_env.NEWS_EXIT_MIN))
finally:
    os.environ.pop("NEWS_EXIT_MIN", None)
    importlib.reload(appcfg)

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — no position is carried into a release it can see.")
