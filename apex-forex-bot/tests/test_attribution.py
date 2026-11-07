"""An ad click has to survive the trip into Telegram, or the ads cannot be paid for.

Telegram's deep-link payload is the constraint the whole design bends around:

    "start — 1-64 characters. Only A-Z, a-z, 0-9, _ and - are allowed."

A Meta click identifier is longer than that and uses characters the payload
rejects, so it cannot ride in a t.me link. Without a bridge, every sale from a
paid ad is unattributed, Meta's optimiser is blind, and the cost per purchase
never falls.

These checks prove the bridge holds at each seam, and — just as important —
that it never becomes the reason a click or a sale is lost.

Run: python tests/test_attribution.py
"""
import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

failures = []


def check(name, cond, detail=""):
    print(f"  OK   {name}" if cond else f"  FAIL {name} {detail}")
    if not cond:
        failures.append(name)


# Click records live in the shared store, which is Redis in every environment
# this ships to — user_store refuses to start in production without one. So
# these run against a real Redis or they do not run at all. A local JSON
# fallback would pass while proving nothing about the code path that ships.
if not shutil.which("redis-server"):
    print("\n  SKIP  redis-server not on PATH — these checks CANNOT run here.")
    print("        They are not passing; they are unrun.")
    sys.exit(0)


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


PORT = _free_port()
_redis = subprocess.Popen(
    ["redis-server", "--port", str(PORT), "--save", "", "--appendonly", "no"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1.5)

os.environ["REDIS_URL"] = f"redis://127.0.0.1:{PORT}/0"
os.environ["APP_ENV"] = "production"          # exercise the production path
os.environ["PRODUCT"] = "forex"
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-only-oauth-signing-secret")
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="apex-attr-"))
os.environ.setdefault("TOKEN_ENCRYPTION_KEY",
                      base64.urlsafe_b64encode(os.urandom(32)).decode())
# Reporting must be off unless it is switched on deliberately; the checks that
# care set it themselves.
for _v in ("META_CAPI_ENABLED", "META_DATASET_ID", "META_PIXEL_ID", "META_CAPI_TOKEN"):
    os.environ.pop(_v, None)

from apex import attribution as at, user_store  # noqa: E402


print("\n1. The token fits where it has to fit")
tok = at.mint_token()
check(f"length is inside Telegram's 64 ({len(tok)})", 1 <= len(tok) <= 64, tok)
check("every character is one the payload allows",
      all(c.isalnum() or c in "_-" for c in tok), tok)
check("it is recognised as ours", at.looks_like_token(tok))
check("two tokens differ", at.mint_token() != at.mint_token())

print("\n2. A licence key is never mistaken for a token")
# This is the collision that matters: both arrive after /start, and treating a
# buyer's key as an ad click would swallow their activation.
for key in ("FORX-A3K9-P2M7-X4RT",
            "FORX-A3K9P-2M7X4-RT8QW-L5NVB-C7DHG",
            "forx-a3k9-p2m7-x4rt", "", "   ", None,
            "ax", "axSHORT", "ax" + "!" * 22, "zz" + "A" * 22):
    check(f"refused: {str(key)[:34]!r}", not at.looks_like_token(key))

print("\n3. A click is stored and can be read back")
token = at.record_click(
    fbclid="IwAR0TESTCLICKID",
    utm={"utm_source": "meta", "utm_campaign": "oct-launch", "ref": ""},
    ip="203.0.113.9", user_agent="Mozilla/5.0", url="https://x.test/go?fbclid=IwAR0TESTCLICKID")
check("record_click returns a usable token", at.looks_like_token(token), token)
raw = json.loads(user_store.get_blob(f"attr:click:{token}"))
check("the click id is kept", raw["fbclid"] == "IwAR0TESTCLICKID", raw.get("fbclid"))
check("fbc is built in Meta's fb.1.<ms>.<id> form",
      raw["fbc"].startswith("fb.1.") and raw["fbc"].endswith(".IwAR0TESTCLICKID"), raw.get("fbc"))
check("utm values survive", raw["utm"]["utm_campaign"] == "oct-launch", raw.get("utm"))
check("empty utm values are dropped, not stored blank", "ref" not in raw["utm"], raw.get("utm"))

print("\n4. Untrusted query values are clamped before storage")
dirty = at.record_click(fbclid="A" * 5000, user_agent="U" * 5000,
                        utm={"utm_source": "x\x00\x07y"}, ip="1.2.3.4")
d = json.loads(user_store.get_blob(f"attr:click:{dirty}"))
check(f"fbclid is bounded ({len(d['fbclid'])})", len(d["fbclid"]) <= 255)
check(f"user agent is bounded ({len(d['ua'])})", len(d["ua"]) <= 400)
check("control characters are stripped", "\x00" not in d["utm"]["utm_source"], repr(d["utm"]))

print("\n5. The click binds to the chat that opened it")
check("claim succeeds", at.claim(token, "555001") is True)
rec = at.for_chat("555001")
check("the chat now carries the click id", rec and rec["fbclid"] == "IwAR0TESTCLICKID")
check("the chat id is recorded on it", rec.get("chat_id") == "555001", rec)

print("\n6. First claim wins")
# A returning visitor tapping an older ad must not overwrite the click that
# actually brought them in, and one token must not be claimable twice.
second = at.record_click(fbclid="LATERCLICK")
check("a second token cannot displace the first",
      at.claim(second, "555001") is False)
check("the original click is intact", at.for_chat("555001")["fbclid"] == "IwAR0TESTCLICKID")
check("the click record is retired, so a leaked token claims nothing",
      at.claim(token, "555002") is False and at.for_chat("555002") is None)

print("\n7. Bad input never raises")
for bad in (None, "", "not-a-token", 12345):
    check(f"claim({bad!r}) returns False quietly", at.claim(bad, "555003") is False)
check("an unknown token claims nothing", at.claim(at.mint_token(), "555004") is False)
check("a chat with no click reads as None", at.for_chat("999999") is None)

print("\n8. Nothing reaches Meta unless it is switched on")
check("off by default", at.report_purchase("555001", 497.0) == "disabled")
os.environ["META_CAPI_ENABLED"] = "true"
check("credentials alone are not consent — still off without a dataset",
      at.report_purchase("555001", 497.0) == "disabled")
os.environ["META_DATASET_ID"] = "1234567890"
check("still off without a token", at.report_purchase("555001", 497.0) == "disabled")
os.environ["META_CAPI_TOKEN"] = "test-token"
check("a chat with no click is not reported",
      at.report_purchase("no-such-chat", 497.0) == "no click on record")
os.environ["META_CAPI_ENABLED"] = "false"
check("the flag turns it back off", at.report_purchase("555001", 497.0) == "disabled")

print("\n9. The email is hashed, never sent in the clear")
SRC = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "apex", "attribution.py"), encoding="utf-8").read()
body = "\n".join(l for l in SRC.splitlines() if not l.strip().startswith("#"))
check("sha256 is what fills the em field",
      'user_data["em"] = [_sha256(email)]' in body)
check("the raw address is never assigned to a user_data field",
      'user_data["em"] = [email]' not in body and 'user_data["em"] = email' not in body)
check("the access token rides in the query string, not a logged body",
      "access_token=" in body)
check("Meta's response is truncated before it is printed",
      "r.text[:200]" in body)

print("\n10. The reporting path cannot break a completed sale")
STRIPE = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "apex", "stripe_license.py"), encoding="utf-8").read()
tail = STRIPE[STRIPE.index("activated {chat_id} with license"):]
check("report_purchase is called after the licence is written",
      "attribution.report_purchase" in tail)
check("it is wrapped so an exception cannot reach Stripe",
      "attribution reporting raised" in tail)
check("the handler still answers 200 afterwards", tail.rstrip().endswith('return 200, b"ok"'))
already = STRIPE[STRIPE.index("already licensed"):STRIPE.index("activated {chat_id}")]
check("a redelivery does not report the sale a second time",
      "report_purchase" not in already)

print("\n11. /go redirects even when everything else fails")
BOT = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "apex", "bot.py"), encoding="utf-8").read()
go = BOT[BOT.index('if self.path == "/go"'):]
go = go[:go.index("return") + 6]
check("the redirect target is set before anything can throw",
      go.index("target =") < go.index("try:"))
check("a failure falls through to a plain bot link, not an error page",
      "except Exception" in go and "self.send_response(302)" in go)
check("the token is percent-encoded into the deep link", "_go_quote(_go_token" in go)
check("the response is not cacheable", "no-store" in go)
check("the referrer is not leaked onward", "Referrer-Policy" in go)
check("the click is rate limited", "http_security.GO.check" in go)

print("\n12. /start tells an ad click apart from a licence key")
TG = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "apex", "telegram.py"), encoding="utf-8").read()
start = TG[TG.index('cmd_l = cmd.lower().split("@")[0]'):]
start = start[:start.index("licence_shape_ok")]
check("the token is checked before .upper() destroys its case",
      start.index("looks_like_token") < start.index("raw_arg.upper()"))
check("the ad landing is reached", "_welcome_ad_click(chat_id, raw_arg)" in start)
LAND = TG[TG.index("def _welcome_ad_click"):TG.index("def _license_ok")]
check("the click is claimed", "attribution.claim(token, str(chat_id))" in LAND)
check("an ad visitor is shown the offer, not a key error",
      "_handle_purchase(chat_id)" in LAND)
check("a messaging failure cannot stop the claim",
      LAND.index("attribution.claim") < LAND.index("try:"))

print("\n" + "=" * 50)
_redis.terminate()
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:8])}")
    sys.exit(1)
print("ALL ATTRIBUTION CHECKS PASSED - the click survives the trip into Telegram.")
