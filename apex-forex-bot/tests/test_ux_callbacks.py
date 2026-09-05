"""Every button this bot ever sent is still in somebody's chat, still pressable.

So a callback is untrusted input with no expiry. This file pins the four ways
that goes wrong and the one way it must not:

  STALE        a confirmation from an hour ago must do nothing. Not "close
               whatever is open now" — nothing.
  INVALID      data the bot never issued must not reach a handler.
  REPEATED     two taps must not become two orders. The interface answers
               once; the ledger claim inside the gate is what makes the second
               order impossible.
  AMBIGUOUS    a broker that did not answer is neither success nor failure,
               and must never be retried on the client's behalf.

And the architectural one, checked against the source because it is the kind
of rule that decays by accident: Telegram is a presentation layer. No callback
handler builds a broker or places an order — every origin converges on
`gates.authorize_order` / `gates.authorize_close`.

Scenarios covered here (of the 30): signal approve · signal reject · position
close · duplicate close · stale callback · invalid callback · duplicate
approval · unknown broker order result.

Run: python tests/test_ux_callbacks.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("PAPER_TRADING", "true")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")

from apex import callback_guard as G  # noqa: E402
from apex import telegram as tg, user_loop, user_store  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} — {detail}")
        failures.append(name)


# ── stand-ins ──
sent = []
store = {}
claims = set()

tg.send_to = lambda cid, text, extra=None, **kw: sent.append(text) or text
user_store.load = lambda cid: dict(store)
user_store.update = lambda cid, d, **kw: store.update(d)


def _claim(key, ttl_s=120):
    if key in claims:
        return False
    claims.add(key)
    return True


user_store.claim = _claim
user_loop.is_running = lambda cid: True
user_loop.get_dash = lambda cid: {"balance": 1000.0,
                                  "openPosition": {"symbol": "EUR_USD",
                                                   "side": "BUY",
                                                   "entryPrice": 1.1,
                                                   "units": 1000}}
user_loop.live_balance = lambda cid: None
user_loop.open_position_count = lambda cid: 1


def reset():
    sent.clear()
    claims.clear()
    store.clear()
    store.update({"ctrader_access_token": "t", "ctrader_account_id": 9,
                  "ctrader_accounts": [{"ctid": 9, "live": False}],
                  "paper": True, "symbol": "EUR_USD", "strategy": "auto"})


print("\n🧪 CALLBACKS — old buttons, fat fingers and silent brokers\n")

print("1. Scenario: invalid callback data never reaches a handler")
for bad in (None, 123, "", "x" * 80, "nav:../../etc/passwd", "DROP TABLE users",
            "unknownns:go", "nav:<script>", "\x00nav:menu", "nav menu"):
    check(f"rejected: {bad!r}", G.parse(bad) is None, str(G.parse(bad)))
for good in ("nav:menu", "nav:home", "am:full", "pos:goclose:AB12CD",
             "acct:use:900001", "pf:today"):
    check(f"accepted: {good}", G.parse(good) is not None)

reset()
tg._handle_cb("1", "totally-made-up")
check("an invalid callback answers the client rather than crashing",
      len(sent) == 1, str(sent))
check("and says nothing happened", "expired" in sent[0].lower(), sent[0][:120])
check("no unsafe action was taken — the record is untouched",
      store.get("paper") is True and "confirm_close" not in store, str(store))

print("\n2. Scenario: a stale close confirmation does nothing")
reset()
closes = []
user_loop.force_close = lambda cid, **kw: closes.append(cid) or {"ok": True,
                                                                 "netPnl": 1.0}
tg._screen_close_confirm("1")
token = (store.get("confirm_close") or {}).get("token")
check("a confirmation token was issued", bool(token), str(store.get("confirm_close")))
check("the confirm screen warns the close is final",
      any("cannot be reopened" in s for s in sent), sent[-1][:200])

# Expire it exactly the way time does.
store["confirm_close"]["ts"] = time.time() - (G.DEFAULT_TTL_S + 10)
sent.clear()
tg._do_close("1", token)
check("an expired confirmation closes nothing", closes == [], str(closes))
check("and the client is told it expired",
      any("expired" in s.lower() for s in sent), str(sent)[:200])

print("\n3. Scenario: a close confirmation is single-use")
reset()
closes.clear()
tg._screen_close_confirm("1")
token = store["confirm_close"]["token"]
sent.clear()
tg._do_close("1", token)
check("the first confirmation closes once", len(closes) == 1, str(closes))
tg._do_close("1", token)
check("the second does NOT close again", len(closes) == 1, str(closes))
check("and it is answered, not ignored",
      any("expired" in s.lower() for s in sent), str(sent)[-200:])

print("\n4. Scenario: a wrong token is refused")
reset()
closes.clear()
tg._screen_close_confirm("1")
tg._do_close("1", "ZZZZZZ")
check("a token that was never issued closes nothing", closes == [], str(closes))

print("\n5. Scenario: duplicate close (the same button, twice, fast)")
reset()
seen = []


def _dupe_close(cid, **kw):
    seen.append(cid)
    if len(seen) == 1:
        return {"ok": True, "netPnl": 2.0}
    return {"ok": False, "error": "DUPLICATE_CLOSE"}


user_loop.force_close = _dupe_close
tg._screen_close_confirm("1")
tok = store["confirm_close"]["token"]
tg._do_close("1", tok)
sent.clear()
tg._do_close("1", tok)
check("the repeat never reached the close path a second time",
      len(seen) == 1, str(seen))

print("\n6. Scenario: the repeated action guard, at the routing layer")
reset()
check("a first press is allowed", G.once("1", "am:full") is True)
check("an immediate repeat is not", G.once("1", "am:full") is False)
check("a different button is unaffected", G.once("1", "am:signals") is True)
check("navigation is not treated as an action",
      G.is_action("nav:menu") is False and G.is_action("pf:today") is False)
check("but money and settings are",
      all(G.is_action(d) for d in ("am:full", "pos:close", "live:go", "acct:use:1",
                                   "emg:go", "cp:y", "bot:on")))
sent.clear()
tg._handle_cb("1", "am:signals")
n_after_first = len(sent)
tg._handle_cb("1", "am:signals")
check("a repeated action is answered once and not performed twice",
      any("Already done" in s for s in sent[n_after_first:]),
      str(sent[n_after_first:])[:200])

print("\n7. Scenario: signal approve, reject, and a duplicate approval")
reset()
opened = []
sug = {"side": "BUY", "symbol": "EUR_USD"}
_pending = {"v": dict(sug)}
user_loop.pending_suggestion = lambda uid: _pending["v"]
user_loop.clear_suggestion = lambda uid: _pending.update(v=None)
user_loop.force_trade = lambda uid, side, symbol=None, lots=None: (
    opened.append((side, symbol)) or {"ok": True, "price": 1.1, "units": 1000,
                                      "sl": 1.09, "tp": 1.12})
tg._route_cb("1", "cp:y")
check("approve opens exactly one position", len(opened) == 1, str(opened))
sent.clear()
tg._route_cb("1", "cp:y")
check("a duplicate approval opens nothing more", len(opened) == 1, str(opened))
check("and the client is told the opportunity expired",
      any("expired" in s.lower() for s in sent), str(sent)[:200])

reset()
_pending["v"] = dict(sug)
opened.clear()
tg._route_cb("1", "cp:n")
check("reject opens nothing", opened == [], str(opened))
check("reject clears the suggestion", _pending["v"] is None)

print("\n8. Scenario: an unknown broker order result is never blindly retried")
check("a timeout is ambiguous", user_loop.broker_result_ambiguous("timed out") is True)
check("a dropped connection is ambiguous",
      user_loop.broker_result_ambiguous("connection reset by peer") is True)
check("an empty error is ambiguous", user_loop.broker_result_ambiguous("") is True)
check("a rejection is NOT ambiguous",
      user_loop.broker_result_ambiguous("order rejected: insufficient margin") is False)
check("'not found' is NOT ambiguous",
      user_loop.broker_result_ambiguous("position not found") is False)

reset()
sent.clear()
user_loop.force_trade = lambda uid, side, symbol=None, lots=None: {
    "ok": False, "error": "timed out waiting for the broker", "ambiguous": True,
    "side": side, "symbol": symbol}
tg._exec_trade("1", "BUY", "EUR_USD", 0.01)
blob = "\n".join(sent)
check("the client gets the ORDER STATUS UNKNOWN screen",
      "ORDER STATUS UNKNOWN" in blob, blob[:200])
check("it does NOT claim the order failed",
      "Could not open trade" not in blob, blob[:300])
check("it does NOT claim the order succeeded", "entered" not in blob, blob[:300])
check("it offers no retry button",
      "retry" not in blob.lower() and "try again" not in blob.lower(), blob[:400])
check("it sends the client to their broker to look",
      "broker" in blob.lower(), blob[:400])

sent.clear()
user_loop.force_trade = lambda uid, side, symbol=None, lots=None: {
    "ok": False, "error": "order rejected: insufficient margin",
    "ambiguous": False}
tg._exec_trade("1", "BUY", "EUR_USD", 0.01)
blob = "\n".join(sent)
check("a real rejection IS reported as a failure",
      "Could not open" in blob, blob[:200])
check("and does not use the unknown screen",
      "ORDER STATUS UNKNOWN" not in blob, blob[:200])

print("\n9. Scenario: a close whose result is unknown")
reset()
sent.clear()
user_loop.force_close = lambda cid, **kw: {"ok": False, "symbol": "EUR_USD",
                                           "error": "timed out",
                                           "ambiguous": True}
tg._handle_close("1")
blob = "\n".join(sent)
check("the client gets CLOSE STATUS UNKNOWN", "CLOSE STATUS UNKNOWN" in blob,
      blob[:200])
check("it says they may still be in the trade",
      "may still be in this trade" in blob, blob[:400])
check("and that the bot will not repeat it",
      "will not send the request again" in blob, blob[:500])

print("\n10. The architectural rule: Telegram never reaches the broker itself")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TG = open(os.path.join(ROOT, "apex", "telegram.py"), encoding="utf-8").read()
route = TG[TG.index("def _route_cb"):TG.index("def _handle_market")]
for forbidden in ("place_order", "close_position(", "CtraderBroker",
                  "_make_broker"):
    check(f"no '{forbidden}' anywhere in the callback router",
          forbidden not in route, forbidden)
check("opening goes through the audited loop entry point",
      "user_loop.force_trade(" in TG)
check("closing goes through the audited loop entry point",
      "user_loop.force_close(" in TG)
LOOP = open(os.path.join(ROOT, "apex", "user_loop.py"), encoding="utf-8").read()
ft = LOOP[LOOP.index("def force_trade"):LOOP.index("def read_candles")]
check("force_trade still enters the order gate",
      "gates.authorize_order(" in ft)
fc = LOOP[LOOP.index("def force_close("):LOOP.index("def open_position_count")]
check("force_close still enters the close gate", "gates.authorize_close(" in fc)
check("the gate is still claimed BEFORE the broker is called",
      ft.index("gates.authorize_order(") < ft.index("place_order("))
check("Telegram defines no second order path",
      "def force_trade" not in TG and "def authorize_order" not in TG)

print("\n11. Every routed callback the keyboards emit is routable")
import re  # noqa: E402
emitted = set(re.findall(r'callback_data["\']?\s*[:=]\s*f?["\']([a-z]+):', TG))
emitted |= set(re.findall(r'\(\s*"[^"]*",\s*"([a-z]+):', TG))
unknown = sorted(n for n in emitted if n not in G.NAMESPACES)
check("no keyboard emits a namespace the guard would reject",
      not unknown, str(unknown))

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed: {', '.join(failures)}")
    sys.exit(1)
print("✅ CALLBACKS ARE SAFE — stale does nothing, repeats do it once, "
      "unknown is never retried.")
