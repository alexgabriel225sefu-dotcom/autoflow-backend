"""Approval Required, answered by the platform instead of by nobody.

THE BUG THIS FILE EXISTS TO KEEP CLOSED, STATED PLAINLY BECAUSE IT SHIPPED

The engine has three automation levels. In `approval` the loop finds a setup
and calls `user_loop._suggest_trade`, which writes `pending_suggestion` onto
the account, calls `alert_fn`, and places nothing. `automation.start` started
the loop as `user_loop.start(user_id)` — with NO alert function — and the
approval itself needed a Telegram tap no platform client has. So every
platform client ran a loop that found setups, wrote a proposal nobody could
see, notified nobody, and placed nothing, while the dashboard said Running.

Commit 6f984dfe9 removed that state by refusing to run at a level the platform
could not service. This file is the other half: the level is serviceable now,
so what has to be true is the whole path — the engine's alert reaches a
notification, the proposal is readable, approving it places the trade through
the ONE order controller, and a double tap cannot open two positions.

WHAT EACH SECTION WOULD CATCH

  [1] the level is serviceable and resolves to `approval`, which is what makes
      the loop propose at all
  [2] the alert reaches the client — the exact thing that was missing
  [3] the proposal is readable, and unknown fields read as unknown
  [4] approving places it through `user_loop.force_trade` and nothing else
  [5] a double tap, an expired setup, a stopped loop and a dismissal
  [6] the API routes: authenticated, owned, and refusals carrying codes
  [7] the client can actually see and answer it on a screen

Run: python3 tests/test_platform_approvals.py
"""
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_TMP = tempfile.mkdtemp(prefix="a4t-appr-")
os.environ["DATA_DIR"] = _TMP
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"
os.environ["SUPABASE_URL"] = "https://stub.supabase.co"
os.environ["SUPABASE_ANON_KEY"] = "anon"
os.environ["CTRADER_REDIRECT_URI"] = "https://apex4traders.test/cb"
from cryptography.fernet import Fernet  # noqa: E402

os.environ["TOKEN_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
os.environ.pop("A4T_EMERGENCY_HALT", None)

import requests  # noqa: E402

from apex import automation as _eng_auto                   # noqa: E402
from apex import user_store                                # noqa: E402
from apex.platform import api as A                         # noqa: E402
from apex.platform import approvals as AP                  # noqa: E402
from apex.platform import automation as AU                 # noqa: E402
from apex.platform import engine_config as ECFG            # noqa: E402
from apex.platform import identity as I                    # noqa: E402
from apex.platform import notifications as NOTIFY          # noqa: E402
from apex.platform import ruledoc as RD                    # noqa: E402

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


USER = "aaaa1111-2222-4333-8444-aaaa55556666"
NOW = 1_800_000_000.0


def set_pending(side="BUY", symbol="EURUSD", ts=NOW, *, active=True,
                extra=None):
    """The account record exactly as the loop leaves it in approval mode."""
    rec = {"active": active, "symbol": symbol, "risk": 0.01, "sl_pips": 25,
           "automation": "approval",
           "pending_suggestion": dict({"side": side, "symbol": symbol,
                                       "ts": ts}, **(extra or {}))}
    user_store.save(USER, rec)


def clear_all():
    user_store.save(USER, {"active": True})
    from apex.platform import store as _store
    _store._write(AP._k_detail(USER), None)


# ── [1] the level the loop runs at ──────────────────────────────────────────
# `_automation_level` refuses any level the platform cannot service, and
# `approval` was deliberately off that list until there was an approve action.
# These assert both halves: it is on the list NOW, and a rule that does not
# ask for it still gets `full` rather than inheriting a default nobody chose.
print("\n[1] the platform can service the approval level")
check("approval is a serviceable level",
      ECFG.LEVEL_APPROVAL in ECFG.SERVICEABLE_LEVELS,
      "a level the platform cannot answer is how the loop went silent")
_doc = RD.blank(user_id=USER, account_id="901", symbols=["EURUSD"],
                timeframe="1h")
_doc["automationLevel"] = ECFG.LEVEL_APPROVAL
_applied, _ = ECFG.translate(_doc)
check("a rule that asks for approval is given approval",
      _applied.get("automation") == ECFG.LEVEL_APPROVAL,
      f"translate wrote {_applied.get('automation')!r}")
# The question commit 6f984dfe9 added, asked for this level: what the ENGINE
# resolves once the record is written. A level that translate writes and
# `automation.mode` disagrees with would run at something nobody chose.
_resolved = _eng_auto.mode(dict(_applied, active=True))
check("and the engine resolves the record to that same level",
      _resolved == ECFG.LEVEL_APPROVAL,
      f"wrote {_applied.get('automation')!r}, engine read {_resolved!r}")
check("which means the loop proposes instead of executing",
      _eng_auto.EXECUTES[_resolved] is False,
      "approval that executes is not approval")
_plain = RD.blank(user_id=USER, account_id="901", symbols=["EURUSD"],
                  timeframe="1h")
check("a rule that asks for nothing still gets full, not approval",
      ECFG.translate(_plain)[0].get("automation") == ECFG.LEVEL_FULL,
      "pressing Start on a rule is the instruction to trade it; approval "
      "must be chosen, never inherited")
_junk = dict(_plain, automationLevel="supervised")
check("and a level that does not exist is refused, not passed through",
      ECFG.translate(_junk)[0].get("automation") == ECFG.LEVEL_FULL,
      "an unknown level would reach the engine and resolve to something "
      "nobody picked")

print("\n[1b] and the level survives the whole way to the running loop")
# Measured rather than reasoned about, because the reasoning was wrong once:
# `automationLevel` is not in `ruledoc.blank` and `api._create` does not copy
# it, which looked like "no client can choose a level". The PUT route carries
# it — `store.save_draft` merges whatever the patch holds — and the question
# that matters is whether it survives ACTIVATION, since the loop is started
# from the frozen version. If it did not, everything in this file would be
# unreachable in production while passing here.
from apex.platform import conditions as _cond                # noqa: E402
from apex.platform import store as _pstore                   # noqa: E402

_chain = RD.blank(user_id=USER, account_id="901", symbols=["EURUSD"],
                  timeframe="1h")
_chain["name"] = "chain"
_chain["sides"] = "BUY"
_chain["entry"]["conditions"] = [{"id": "rsi", "period": 14, "op": "below",
                                  "value": 30}]
_rid = _chain["ruleDocId"]
_pstore.create(USER, _chain)
_saved = _pstore.save_draft(USER, {"ruleDocId": _rid,
                                   "automationLevel": ECFG.LEVEL_APPROVAL})
check("a PUT can set the level on a draft",
      _saved.get("automationLevel") == ECFG.LEVEL_APPROVAL,
      str(_saved.get("automationLevel")))
_live = _pstore.activate(USER, _rid,
                         known_condition_ids=_cond.available())
check("and activation freezes it rather than dropping it",
      _live.get("automationLevel") == ECFG.LEVEL_APPROVAL,
      "the loop is started from the activated version, so a level lost here "
      "is a level the client chose and the engine never sees")
_chain_applied, _ = ECFG.translate(_pstore.get(USER, _rid))
check("and the engine resolves the activated rule to approval",
      _eng_auto.mode(dict(_chain_applied, active=True))
      == ECFG.LEVEL_APPROVAL,
      str(_chain_applied.get("automation")))

# ── [2] the alert reaches the client ────────────────────────────────────────
# THE MISSING PIECE. `_suggest_trade` calls alert_fn; the platform passed
# None. These assert that the default starter supplies one, and that the one
# it supplies turns a SUGGEST into something a client can see.
print("\n[2] the engine's suggestion reaches a platform client")
_started = {}


def _fake_loop_start(user_id, alert_fn=None):
    _started["user_id"] = user_id
    _started["alert_fn"] = alert_fn
    return True


import apex.user_loop as _ul                               # noqa: E402

_real_start = _ul.start
_ul.start = _fake_loop_start
try:
    AU._engine_starter(USER)
finally:
    _ul.start = _real_start
check("the default starter hands the engine an alert function",
      callable(_started.get("alert_fn")),
      f"alert_fn={_started.get('alert_fn')!r} — None is the defect: the loop "
      f"proposes, calls it, and nobody is told")

# Asserted by BEHAVIOUR, not by identity. The engine takes one alert
# function and more than one level needs to be heard through it, so what
# matters is that whatever is wired there delivers a SUGGEST to this module —
# an identity check would pass a wrapper that dropped it, and fail a wrapper
# that does not.
clear_all()
set_pending(side="SELL", symbol="GBPUSD", ts=NOW)
_before = NOTIFY.unread_count(USER)
_alert = _started.get("alert_fn")
if callable(_alert):
    _alert(USER, {"action": "SUGGEST", "symbol": "GBPUSD", "side": "SELL",
                  "price": 1.2345, "confidence": 60,
                  "reasoning": "RSI(14) 72.4 above 70",
                  "keyFactors": ["rsi"]})
check("and what is wired there reaches THIS module's approval sink",
      NOTIFY.unread_count(USER) == _before + 1
      and AP.pending(USER, now=NOW + 1)["approval"]["price"] == 1.2345,
      "the engine's SUGGEST did not arrive — whatever is wired as the alert "
      "function is not delivering it, which is the silence this file exists "
      "to keep closed")

clear_all()
set_pending(side="SELL", symbol="GBPUSD", ts=NOW)
_before = NOTIFY.unread_count(USER)
AP.engine_alert(USER, {"action": "SUGGEST", "symbol": "GBPUSD",
                       "side": "SELL", "price": 1.2345, "confidence": 60,
                       "reasoning": "RSI(14) 72.4 above 70",
                       "keyFactors": ["rsi"]})
_rows = NOTIFY.query(USER, limit=5)["notifications"]
check("a suggestion becomes a notification the client can read",
      NOTIFY.unread_count(USER) == _before + 1, str(NOTIFY.unread_count(USER)))
check("and it names the side and the instrument in the title",
      _rows and "SELL" in _rows[0]["title"] and "GBPUSD" in _rows[0]["title"],
      str(_rows[:1]))
check("and says that nothing opens until the client approves",
      _rows and "until you approve" in _rows[0]["body"],
      str(_rows[:1]))
check("and is loud enough to be noticed before it expires",
      _rows and _rows[0]["level"] == NOTIFY.WARNING,
      f"level={_rows[0]['level'] if _rows else None} — this one expires in "
      f"five minutes, so an unnoticed notification is no notification")

print("\n[2b] and the alert sink refuses to do anything else")
_n = NOTIFY.unread_count(USER)
for action in ("SIGNAL", "STOP", "CLOSE", "BROKER_HEALTH", "", None):
    AP.engine_alert(USER, {"action": action, "symbol": "GBPUSD",
                           "side": "SELL", "price": 1.2})
check("every other alert the loop emits is ignored",
      NOTIFY.unread_count(USER) == _n,
      "notifying on the whole firehose buries the one that needs an answer")
# The resurrection hazard. The alert is called AFTER the record is written, so
# a client who approved in that gap has no pending suggestion — and an alert
# that wrote one back would be a position waiting to open after a yes.
clear_all()
_n = NOTIFY.unread_count(USER)
AP.engine_alert(USER, {"action": "SUGGEST", "symbol": "GBPUSD", "side": "SELL",
                       "price": 1.2345, "reasoning": "x"})
check("an alert for a suggestion that is no longer there writes nothing",
      user_store.load(USER).get("pending_suggestion") in (None, {}, ""),
      str(user_store.load(USER).get("pending_suggestion")))
check("and tells nobody about a setup that no longer exists",
      NOTIFY.unread_count(USER) == _n, "a notification for an answered setup")
# It runs on the trading thread. An exception here would propagate into the
# loop's tick, so it must swallow whatever happens underneath it.
set_pending()
_real_notify = NOTIFY.notify
NOTIFY.notify = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("down"))
try:
    _raised = None
    try:
        AP.engine_alert(USER, {"action": "SUGGEST", "symbol": "EURUSD",
                               "side": "BUY", "price": 1.1})
    except Exception as e:                                  # noqa: BLE001
        _raised = e
finally:
    NOTIFY.notify = _real_notify
check("a notification store that is down never reaches the trading loop",
      _raised is None, f"raised {_raised!r} into the engine's tick")

# ── [3] the proposal is readable, and what is unknown reads as unknown ──────
print("\n[3] the client's view of the proposal")
clear_all()
check("no suggestion reads as none, not as a failure",
      AP.pending(USER, now=NOW) == {"status": AP.OK, "approval": None},
      str(AP.pending(USER, now=NOW)))

set_pending(side="BUY", symbol="EURUSD", ts=NOW)
AP.engine_alert(USER, {"action": "SUGGEST", "symbol": "EURUSD", "side": "BUY",
                       "price": 1.0987, "confidence": 60,
                       "reasoning": "RSI(14) 24.3 below 30",
                       "keyFactors": ["rsi"]})
_p = AP.pending(USER, now=NOW + 30)["approval"]
check("the setup is reported with its side and instrument",
      _p["symbol"] == "EURUSD" and _p["side"] == "BUY", str(_p))
check("and the price it was found at",
      _p["price"] == 1.0987, str(_p.get("price")))
check("and the rule's own reason, not a generic sentence",
      _p["reasoning"] == "RSI(14) 24.3 below 30", str(_p.get("reasoning")))
check("and how long is left before it expires",
      _p["expiresInSec"] == 270.0 and _p["expired"] is False,
      str({k: _p[k] for k in ("ageSec", "expiresInSec", "expired")}))
check("and that it can be acted on",
      _p["actionable"] is True and _p["refusal"] is None, str(_p))

# THE JOIN, which is the whole reason the detail is stamped. A detail record
# left behind by one suggestion must never be rendered as the price and
# reasoning of the next.
set_pending(side="SELL", symbol="USDJPY", ts=NOW + 400)
_p = AP.pending(USER, now=NOW + 420)["approval"]
check("a NEW setup does not inherit the previous one's price",
      _p["price"] is None and _p["reasoning"] is None,
      f"showed {_p.get('price')!r} / {_p.get('reasoning')!r} from the setup "
      f"the client already answered")
check("and says the detail is not known rather than implying it is empty",
      _p["detailKnown"] is False, str(_p))
check("while still reporting what IS known",
      _p["symbol"] == "USDJPY" and _p["side"] == "SELL", str(_p))

print("\n[3b] expiry, and a loop that is not running")
set_pending(ts=NOW)
_p = AP.pending(USER, now=NOW + AP.EXPIRY_S)["approval"]
check("a setup past the engine's own window is reported expired",
      _p["expired"] is True and _p["actionable"] is False
      and _p["refusal"] == AP.EXPIRED, str(_p))
check("and its countdown does not go negative",
      _p["expiresInSec"] == 0.0, str(_p.get("expiresInSec")))
set_pending(ts=NOW, active=False)
_p = AP.pending(USER, now=NOW + 10)["approval"]
check("a stopped loop makes a setup unactionable, with the reason",
      _p["actionable"] is False and _p["refusal"] == AP.NOT_RUNNING, str(_p))
check("an account with no engine state at all is UNKNOWN, never 'none'",
      AP.pending("cccc1111-2222-4333-8444-cccc55556666",
                 now=NOW)["status"] == AP.UNKNOWN,
      "user_store.load returns {} both for a client who never started and "
      "for a store that did not answer — reporting that as 'no setup is "
      "waiting' states a fact neither case supports")
set_pending(extra={"side": "SIDEWAYS"})
_r = AP.pending(USER, now=NOW)
check("a suggestion whose side is not BUY or SELL is never described",
      _r.get("approval") is None and _r.get("unreadable") is True,
      str(_r))

# ── [4] approving places it through the one controller ──────────────────────
print("\n[4] approving places the trade, through force_trade and nothing else")
_sent = []


def _ok_executor(user_id, side, symbol=None, lots=None, **kw):
    _sent.append({"user_id": user_id, "side": side, "symbol": symbol,
                  "lots": lots, **kw})
    return {"ok": True, "side": side, "symbol": symbol, "price": 1.0988,
            "units": 1000, "sl": 1.0963, "tp": 1.1013}


clear_all()
set_pending(side="BUY", symbol="EURUSD", ts=NOW)
_out = AP.approve(USER, now=NOW + 5, executor=_ok_executor)
check("the controller is called once, with the suggested side and instrument",
      len(_sent) == 1 and _sent[0]["side"] == "BUY"
      and _sent[0]["symbol"] == "EURUSD", str(_sent))
check("and told the order came from an approval, not from a manual trade",
      _sent[0].get("origin") == AP.ORIGIN, str(_sent[0].get("origin")))
check("and given NO size, stop or target of its own",
      _sent[0].get("lots") is None and _sent[0].get("sl_override") is None
      and _sent[0].get("tp_override") is None
      and _sent[0].get("risk_override") is None,
      f"{_sent[0]} — the rule's terms are already on the account; a second "
      f"sizing implementation here would eventually disagree with the first")
check("the outcome is reported as placed, with the order",
      _out["outcome"] == "placed" and _out["order"]["symbol"] == "EURUSD"
      and _out["order"]["units"] == 1000, json.dumps(_out, default=str))
check("and the suggestion is gone",
      AP.pending(USER, now=NOW + 6)["approval"] is None,
      str(AP.pending(USER, now=NOW + 6)))
check("and the client is told the position opened",
      any("EURUSD" in n["title"] and n["type"] == NOTIFY.ORDER
          for n in NOTIFY.query(USER, limit=5)["notifications"]),
      str(NOTIFY.query(USER, limit=3)["notifications"]))

print("\n[4b] a double tap cannot open two positions")
clear_all()
set_pending(side="BUY", symbol="EURUSD", ts=NOW)
_sent.clear()
AP.approve(USER, now=NOW + 1, executor=_ok_executor)
_second = None
try:
    AP.approve(USER, now=NOW + 2, executor=_ok_executor)
except AP.ApprovalRefused as e:
    _second = e
check("the second approve is refused", _second is not None,
      "a second approve placed a second order")
check("and names the state rather than inventing a failure",
      _second and _second.code == AP.NO_SUGGESTION, str(_second))
check("and tells the client to look at their positions instead of retrying",
      _second and "positions" in _second.detail, str(_second))
check("exactly one order was sent", len(_sent) == 1, str(_sent))

print("\n[4b2] and the cross-process half of that guard")
# The clear above is an in-process guard: it stops the second request only
# because the first one already finished. Two containers can both READ a
# pending suggestion before either clears it, and the SET NX claim is what
# makes one of them lose.
#
# There is no shared backend in this environment — `claim_value` returns
# None, which means "could not ask", and every other case here runs down that
# path. So the only way to exercise the branch that matters is to answer it,
# which is what this does. Found by mutation: removing the claim check broke
# nothing, because nothing was reaching it.
_real_claim = user_store.claim_value
user_store.claim_value = lambda *a, **kw: False
try:
    clear_all()
    set_pending(ts=NOW)
    _sent.clear()
    _held = None
    try:
        AP.approve(USER, now=NOW + 1, executor=_ok_executor)
    except AP.ApprovalRefused as e:
        _held = e
    check("an approve that loses the claim places nothing",
          _held is not None and _held.code == AP.ALREADY_HANDLED
          and _sent == [], f"{_held!r} {_sent}")
    check("and the suggestion is left for the holder to finish with",
          user_store.load(USER).get("pending_suggestion") is not None,
          "the loser cleared the winner's suggestion")
    _held = None
    try:
        AP.reject(USER, now=NOW + 1)
    except AP.ApprovalRefused as e:
        _held = e
    check("and a dismissal racing an approve loses the same way",
          _held is not None and _held.code == AP.ALREADY_HANDLED,
          f"{_held!r} — dismissing out from under an approve that is already "
          f"placing an order would clear the record of what is being opened")
finally:
    user_store.claim_value = _real_claim

print("\n[4c] the three broker outcomes stay three")
# A refusal, an ambiguous answer and a fill are different facts. Collapsing
# ambiguous into refused is how one uncertain order becomes two certain ones.
clear_all()
set_pending(ts=NOW)
_ref = None
try:
    AP.approve(USER, now=NOW + 1,
               executor=lambda *a, **kw: {"ok": False, "error":
                                          "minimum lot would risk more than "
                                          "your configured risk per trade"})
except AP.ApprovalRefused as e:
    _ref = e
check("a refused order is a refusal carrying the controller's own words",
      _ref is not None and _ref.code == AP.ORDER_REFUSED
      and "minimum lot" in _ref.detail, str(_ref))
clear_all()
set_pending(ts=NOW)
# Caught rather than allowed to propagate, so that a version which DOES
# collapse the ambiguous case into a refusal fails this assertion by name
# instead of ending the run with a traceback. A test that crashes reports a
# line number; this one reports the fact.
_amb, _amb_raised = None, None
try:
    _amb = AP.approve(USER, now=NOW + 1,
                      executor=lambda *a, **kw: {"ok": False,
                                                 "ambiguous": True,
                                                 "error": "timed out"})
except AP.ApprovalRefused as e:
    _amb_raised = e
check("an unanswered broker is NOT reported as refused",
      _amb_raised is None and (_amb or {}).get("outcome") == "unknown",
      f"raised {_amb_raised!r}, returned {json.dumps(_amb, default=str)} — "
      f"collapsing 'the broker did not answer' into 'the broker said no' is "
      f"how one uncertain order becomes two certain ones")
check("and the client is told the position may be open",
      "may be open" in ((_amb or {}).get("detail") or ""),
      str((_amb or {}).get("detail")))
clear_all()
set_pending(ts=NOW)
_boom, _boom_raised = None, None
try:
    _boom = AP.approve(USER, now=NOW + 1,
                       executor=lambda *a, **kw: (_ for _ in ()).throw(
                           RuntimeError("broker construction failed")))
except Exception as e:                                      # noqa: BLE001
    _boom_raised = e
check("a controller that RAISES is the unknown outcome, not an exception",
      _boom_raised is None and (_boom or {}).get("outcome") == "unknown",
      f"raised {_boom_raised!r} — a traceback reaching the API leaves the "
      f"client with no answer at all about a suggestion already cleared, and "
      f"calling it 'refused' would claim nothing was sent")

clear_all()
set_pending(ts=NOW)
AP.approve(USER, now=NOW + 1,
           executor=lambda *a, **kw: {"ok": False, "ambiguous": True,
                                      "error": "timed out"})
check("loudly, because this is the one they have to go and look at",
      any(n["level"] == NOTIFY.CRITICAL
          for n in NOTIFY.query(USER, limit=3)["notifications"]),
      str(NOTIFY.query(USER, limit=3)["notifications"]))

# ── [5] what approving refuses, and dismissing ──────────────────────────────
print("\n[5] an expired setup, a stopped loop, and a dismissal")
clear_all()
set_pending(ts=NOW)
_sent.clear()
_exp = None
try:
    AP.approve(USER, now=NOW + AP.EXPIRY_S, executor=_ok_executor)
except AP.ApprovalRefused as e:
    _exp = e
check("an expired setup is refused",
      _exp is not None and _exp.code == AP.EXPIRED, str(_exp))
check("and nothing was sent to the controller", _sent == [], str(_sent))
check("and it is NOT cleared on the way out",
      user_store.load(USER).get("pending_suggestion") is not None,
      "clearing on a read that may have raced the loop writing a fresh "
      "suggestion would delete the new one")

clear_all()
set_pending(ts=NOW, active=False)
_sent.clear()
_ns = None
try:
    AP.approve(USER, now=NOW + 1, executor=_ok_executor)
except AP.ApprovalRefused as e:
    _ns = e
check("a setup is not placed while the loop is stopped",
      _ns is not None and _ns.code == AP.NOT_RUNNING, str(_ns))
check("and the reason says what would otherwise be wrong with it",
      _ns and "sized by those" in _ns.detail,
      "stop() restores the account's own risk, stop and target, so a trade "
      "opened after a stop is sized by terms the rule never chose")
check("and nothing was sent", _sent == [], str(_sent))

clear_all()
set_pending(ts=NOW)
_r = AP.reject(USER, now=NOW + 1)
check("dismissing clears the setup",
      _r["rejected"] is True
      and AP.pending(USER, now=NOW + 2)["approval"] is None, str(_r))
_r2 = AP.reject(USER, now=NOW + 3)
check("and dismissing nothing is not a failure",
      _r2["rejected"] is False and _r2["alreadyGone"] is True, str(_r2))
clear_all()
set_pending(ts=NOW)
_sent.clear()
AP.reject(USER, now=NOW + 1)
_after = None
try:
    AP.approve(USER, now=NOW + 2, executor=_ok_executor)
except AP.ApprovalRefused as e:
    _after = e
check("a setup that was dismissed can never then be approved",
      _after is not None and _sent == [], f"{_after!r} {_sent}")
clear_all()
set_pending(extra={"side": "SIDEWAYS"})
AP.reject(USER, now=NOW + 1)
check("an unreadable suggestion can still be dismissed",
      not user_store.load(USER).get("pending_suggestion"),
      "it blocks the loop from proposing for five minutes and cannot be "
      "approved, so the client has to be able to get rid of it")

# ── [6] the API ─────────────────────────────────────────────────────────────
print("\n[6] the routes: authenticated, owned, and refusals with codes")
_USERS = {
    "owner": {"id": USER, "email": "owner@example.com",
              "email_confirmed_at": "2026-01-01T00:00:00Z"},
    "unverified": {"id": USER, "email": "owner@example.com"},
}
_MODE = {"who": "owner"}


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._b = status, body

    def json(self):
        return self._b


requests.get = lambda url, **kw: _Resp(200, _USERS[_MODE["who"]])


def as_user(who="owner"):
    _MODE["who"] = who
    I.forget_all()
    return {"Authorization": f"Bearer token-{who}"}


def call(method, path, who="owner", body=None, headers=None):
    h = headers if headers is not None else as_user(who)
    return A.handle(method, path, h,
                    json.dumps(body) if body is not None else None)


for _m, _p in (("GET", "approvals"), ("POST", "approvals/approve"),
               ("POST", "approvals/reject")):
    _st, _ = A.handle(_m, f"/api/v1/{_p}", {}, None)
    check(f"{_m} {_p} without a session is 401", _st == 401, str(_st))
_st, _ = call("POST", "/api/v1/approvals")
check("POST to the read route is 405", _st == 405, str(_st))
_st, _ = call("GET", "/api/v1/approvals/approve")
check("GET on approve is 405", _st == 405, str(_st))

clear_all()
set_pending(side="BUY", symbol="EURUSD", ts=NOW)
AP.engine_alert(USER, {"action": "SUGGEST", "symbol": "EURUSD", "side": "BUY",
                       "price": 1.0987, "reasoning": "RSI(14) 24.3 below 30",
                       "keyFactors": []})
_st, _b = call("GET", "/api/v1/approvals")
check("the read answers 200 with the pending setup",
      _st == 200 and _b["approval"]["symbol"] == "EURUSD",
      json.dumps(_b, default=str))
check("and carries no account record with it",
      "pending_suggestion" not in json.dumps(_b)
      and "token" not in json.dumps(_b).lower(), json.dumps(_b))

# An expired setup through the API: the refusal must arrive as a CODE the UI
# branches on, not as prose it has to match.
#
# The routes read the real clock — there is no `now` to inject through HTTP,
# which is the point of testing them this way — so these timestamps are real
# ones rather than the fixed NOW above.
import time as _time                                       # noqa: E402

set_pending(ts=_time.time() - AP.EXPIRY_S - 1)
_st, _b = call("POST", "/api/v1/approvals/approve")
check("approving an expired setup is a 409, not a 500 and not a silent 200",
      _st == 409, str(_st))
check("and carries the code",
      _b["error"]["code"] == AP.EXPIRED, json.dumps(_b))
_st, _b = call("POST", "/api/v1/approvals/reject")
check("dismissing it answers 200", _st == 200 and _b["rejected"] is True,
      json.dumps(_b))

# The email gate, which runs BEFORE anything is placed. An unconfirmed address
# is an authentication refusal (401), not a state one, and the thing that
# matters is that the suggestion is still there afterwards: the gate refused
# instead of placing and then complaining.
set_pending(ts=_time.time())
_st, _b = call("POST", "/api/v1/approvals/approve", who="unverified")
check("an unconfirmed address cannot approve a trade",
      _st == 401 and _b["error"]["code"] == "AUTH_REQUIRED", json.dumps(_b))
check("and the setup is left untouched by the refusal",
      user_store.load(USER).get("pending_suggestion") is not None,
      "the gate ran after the order rather than before it")
# Ownership: another client's session must not see this client's setup. The
# key is the user id, so this asserts the scoping rather than a comparison.
clear_all()
set_pending(ts=NOW)
_OTHER = "bbbb1111-2222-4333-8444-bbbb55556666"
_USERS["other"] = {"id": _OTHER, "email": "other@example.com",
                   "email_confirmed_at": "2026-01-01T00:00:00Z"}
_st, _b = call("GET", "/api/v1/approvals", who="other")
check("another client sees nothing of this one's setup",
      _st == 200 and _b.get("approval") is None, json.dumps(_b, default=str))

# ── [7] the client can see it and answer it ─────────────────────────────────
print("\n[7] the screen that shows it")
_card = os.path.join(ROOT, "..", "web", "src", "components", "app",
                     "pending-approval.tsx")
_page = os.path.join(ROOT, "..", "web", "src", "app", "(app)", "dashboard",
                     "page.tsx")
check("the card component exists", os.path.exists(_card), _card)
check("the dashboard exists", os.path.exists(_page), _page)
if os.path.exists(_card) and os.path.exists(_page):
    _src = open(_card, encoding="utf-8").read()
    for _needle, _why in (
        ('"approvals"', "the card never asks the server whether a setup is "
                        "waiting"),
        ("approvals/approve", "the card cannot approve anything"),
        ("approvals/reject", "the card cannot dismiss anything"),
        ("expiresInSec", "nothing counts down, so a client cannot tell "
                         "whether the setup is still live"),
        ("reasoning", "the card does not show WHY the rule proposed it"),
        ("detailKnown", "an unknown price would render as empty rather than "
                        "as unknown"),
    ):
        check(f"the card reads {_needle!r}", _needle in _src, _why)
    _pg = open(_page, encoding="utf-8").read()
    check("and the dashboard renders it",
          "<PendingApproval" in _pg,
          "the component exists and no screen shows it — which is the same "
          "silence as having no component at all")
    check("and imports it from the shared component directory",
          "components/app/pending-approval" in _pg, str(_page))

print()
shutil.rmtree(_TMP, ignore_errors=True)
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("Approval Required is answerable by the platform.")
