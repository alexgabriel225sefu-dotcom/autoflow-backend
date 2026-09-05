"""Closing from the Mini App must be the same close, not a second one.

This is the only financial action the Mini App can start, so it is the one
place a pretty UI could quietly become a second execution path. Three things
have to hold, and none of them are visible by reading the screen:

  1. It creates no new route to the broker. It calls user_loop.force_close,
     which routes through gates.authorize_close — entitlement, ownership,
     idempotency and the audit line all happen there, unchanged.

  2. It never takes a position id from the client. Whatever is on screen, the
     position closed is the one the SERVER holds for that chat. An id from a
     frontend is a request to close something, not proof of the right to.

  3. An unknown outcome is reported as unknown. A request that reached the
     broker path and did not come back is neither "closed" nor "failed", and
     inviting a retry there is how one position gets closed twice.

Run: python tests/test_miniapp_close.py
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
LOOP = open(os.path.join(ROOT, "apex", "user_loop.py"), encoding="utf-8").read()

ROUTE = BOT[BOT.index('if self.path == "/api/app/close"'):]
ROUTE = ROUTE[:ROUTE.index('if self.path == "/api/stripe/webhook"')]
CODE = "\n".join(l for l in ROUTE.splitlines() if not l.strip().startswith("#"))

print("\n1. It is the same close, not a new one")
check("it calls the shared close", "force_close(" in CODE)
check("...with its own origin, so the audit can tell it apart",
      'origin="miniapp"' in CODE)
check("it never reaches a broker directly",
      not any(x in CODE for x in ("close_position(", "place_order", "_make_broker",
                                  "get_broker", "amend_sltp")))
check("it never calls the gate itself — force_close owns that",
      "authorize_close" not in CODE)
check("force_close still routes through the gate",
      "gates.authorize_close(" in LOOP[LOOP.index("def force_close"):
                                       LOOP.index("def force_close") + 2000],
      "if this ever stops being true, this route stops being safe")

print("\n2. The client names nothing")
check("no position id is read from the request",
      "position_id" not in CODE and "positionId" not in CODE)
check("no symbol is read from the request", "symbol=" not in CODE)
check("no body is parsed at all", "Content-Length" not in CODE and "json.loads" not in CODE)
check("the chat id is the one the signature proved",
      '_c_chat = str(_c_user["id"])' in CODE)
check("identity is checked before anything else",
      CODE.index("_telegram_identity") < CODE.index("force_close"))
check("a denied caller is refused", "_telegram_denied" in CODE)

print("\n3. Unknown is not failure")
check("an exception answers CLOSE_STATUS_UNKNOWN", "CLOSE_STATUS_UNKNOWN" in CODE)
check("...with 502, not 200", "self._reply(502" in CODE)
check("...and tells the client not to retry", "Do not retry yet" in CODE)
check("a refusal is 200 with a reason, not an error",
      'self._reply(200, {"ok": False, "error": _c_res.get("error")' in CODE)
check("the screen shows unknown as its own outcome",
      "Close status unknown" in HTML)
# Counting the phrase was a proxy for the real property, and it stopped being
# one when both paths started sharing a renderer. What must hold is that BOTH
# failure paths land on the unknown outcome, and that the unknown outcome is
# what carries the instruction — one occurrence reached from two places is
# stronger than two copies that can drift apart.
_CLOSE = HTML[HTML.index("async function doClose"):]
_CLOSE = _CLOSE[:_CLOSE.index("\n}")]
check("the 502 path routes to the unknown outcome",
      _CLOSE.count("showOrder('close_unknown'") == 2,
      "both the broker's own CLOSE_STATUS_UNKNOWN and a thrown request")
check("...and the unknown outcome carries the do-not-retry instruction",
      "Do not retry yet" in HTML
      and "close_unknown" in HTML[:HTML.index("Do not retry yet") + 400])
check("...and says why retrying is the wrong move",
      "close the position\n                   +'twice" in HTML
      or "twice" in HTML)
check("a refusal says nothing was closed", "Nothing was closed" in HTML)
check("the UI never retries on its own",
      "doClose()" not in HTML.replace("onGo || null", "").replace("askClose(pos)", "")
      or HTML.count("doClose") <= 2,
      "a retry loop here is how a position gets closed twice")

print("\n4. It is bounded and confirmed")
check("the endpoint is rate limited", "http_security.MINIAPP.check" in CODE)
check("a rate-limited caller gets 429", "self._reply(429" in CODE)
check("the client must confirm first", "askClose" in HTML and "Confirm close" in HTML)
check("...and the confirm button is disabled while it runs",
      "go.disabled=true" in HTML)
check("the sheet says where the request goes",
      "close request to your connected cTrader account" in HTML)
check("...and that it is the same authorization",
      "same authorization every other close does" in HTML)

print("\n5. No route local can shadow the enclosing scope")
_locals = set(re.findall(r'^\s+([a-z][\w]*)\s*=(?!=)', CODE, re.M))
check(f"every local is prefixed ({sorted(_locals)})", not _locals,
      "do_POST shares a scope; a bare name here breaks a branch elsewhere")

print("\n" + "=" * 50)
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:8])}")
    sys.exit(1)
print("ALL MINI-APP CLOSE CHECKS PASSED - one close path, and unknown stays unknown.")
