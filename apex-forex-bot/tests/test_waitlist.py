"""Early access: what is stored, what is refused, and what comes back.

This is the only route on the API a stranger can write through, so the
assertions below are mostly about what it REFUSES and what it does not keep.
A waitlist is the cheapest thing in the product to build and the easiest to
turn into a liability: an address stored under a guessable key, a profile
assembled from fields nobody asked for, or a response that confirms who is on
the list.

Run: python3 tests/test_waitlist.py
"""
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_TMP = tempfile.mkdtemp(prefix="a4t-wait-")
os.environ["DATA_DIR"] = _TMP
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"
os.environ["SUPABASE_URL"] = "https://stub.supabase.co"
os.environ["SUPABASE_ANON_KEY"] = "anon"
from cryptography.fernet import Fernet  # noqa: E402
os.environ["TOKEN_ENCRYPTION_KEY"] = Fernet.generate_key().decode()

from apex import user_store                             # noqa: E402
from apex.platform import api as _API                   # noqa: E402
from apex.platform import store as _store               # noqa: E402
from apex.platform import waitlist as W                 # noqa: E402

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


def post(email, source=None, ip="203.0.113.1"):
    body = {"email": email}
    if source is not None:
        body["source"] = source
    return _API._handle("POST", "/api/v1/waitlist", headers={},
                        body=json.dumps(body), client_key=ip)


print("\n[1] what counts as an address")
for bad, why in (
    ("", "empty"), ("   ", "blank"), ("nope", "no @"),
    ("a@b", "no dot in the domain"), ("a@@b.com", "two @"),
    ("a b@c.com", "a space"), ("a@b..com", "an empty label"),
    ("x" * 250 + "@b.com", "over the RFC length"),
):
    try:
        W.normalise(bad)
        check(f"refuses {why}", False, repr(bad[:40]))
    except W.WaitlistError as e:
        check(f"refuses {why}", e.code in ("EMAIL_REQUIRED", "EMAIL_INVALID"),
              e.code)

# A refusal list that refuses everything is no test at all.
for good in ("a@b.com", "First.Last+tag@sub.example.co.uk", "x@y.io"):
    try:
        check(f"accepts {good}", bool(W.normalise(good)))
    except W.WaitlistError as e:
        check(f"accepts {good}", False, e.code)

check("case is folded, because one mailbox is one person",
      W.normalise("  AleX@Example.COM ") == "alex@example.com",
      W.normalise("  AleX@Example.COM "))
check("but the local part is not otherwise rewritten",
      W.normalise("a.b+tag@gmail.com") == "a.b+tag@gmail.com",
      "dots and plus-tags are a Gmail convention, not a rule")

print("\n[2] joining is idempotent and says which it was")
r1 = W.join("Trader@Example.com", source="landing")
check("a new address is added", r1["status"] == "added", json.dumps(r1))
r2 = W.join("trader@example.com", source="landing")
check("the same address differently cased is not a second entry",
      r2["status"] == "already", json.dumps(r2))
check("and the original moment is kept, not overwritten",
      r2.get("joinedAt") == r1.get("joinedAt"),
      f"{r2.get('joinedAt')} vs {r1.get('joinedAt')}")
check("the list counts one", W.count() == 1, str(W.count()))
W.join("second@example.com", source="pricing")
check("a different address is a second entry", W.count() == 2, str(W.count()))

print("\n[3] what is on disk")
raw = _store._read(W._key("trader@example.com"))
check("the record exists under the hashed key", raw is not None)
blob = json.dumps(raw)
check("the address is NOT stored in the clear",
      "trader@example.com" not in blob, blob[:120])
check("and it decrypts back to what was typed",
      user_store.decrypt_value(raw["email"]) == "trader@example.com")
check("the key does not contain the address either",
      "trader" not in W._key("trader@example.com"),
      W._key("trader@example.com"))
check("only the fields we asked for are kept, and no more",
      set(raw) == {"email", "joinedAt", "source"}, str(sorted(raw)))
# That record answered no question, so it carries no answer. The two optional
# fields are written only when somebody actually answers them — see [9].

# The hash is keyed. An unkeyed SHA-256 of an email is a pseudonym, not a
# protection: the input space is small enough to enumerate.
import hashlib                                          # noqa: E402

check("the key is not a bare digest anyone could recompute",
      hashlib.sha256(b"trader@example.com").hexdigest()
      not in W._key("trader@example.com"))

print("\n[9] what the visitor volunteers, and only that")
# Added to answer a question the business could not otherwise answer without
# guessing: which platform to support next, and whether MetaTrader earns its
# cost. Optional by design — an unanswered question must never cost a sign-up.
W.join("plat@example.com", source="landing", platform="MT5 ", broker="  IC  Markets ")
_p = _store._read(W._key("plat@example.com"))
check("a known platform is stored, folded to lower case",
      _p.get("platform") == "mt5", json.dumps(_p.get("platform")))
check("the broker is kept as typed, with the spacing tidied",
      _p.get("broker") == "IC Markets", json.dumps(_p.get("broker")))

W.join("junk@example.com", platform="definitely-not-a-platform")
_j = _store._read(W._key("junk@example.com"))
check("a platform we do not know is not stored at all",
      "platform" not in _j, json.dumps(_j))
check("and the sign-up still succeeds — the question is optional",
      _j.get("joinedAt") is not None)

W.join("quiet@example.com")
_q = _store._read(W._key("quiet@example.com"))
check("somebody who answers nothing carries no empty fields",
      "platform" not in _q and "broker" not in _q, json.dumps(sorted(_q)))

W.join("long@example.com", broker="B" * 200)
_l = _store._read(W._key("long@example.com"))
check("a broker name cannot be used as storage",
      len(_l.get("broker") or "") == W.MAX_BROKER, len(_l.get("broker") or ""))

W.join("empty@example.com", broker="   ")
check("whitespace is not an answer",
      "broker" not in _store._read(W._key("empty@example.com")))

# The form asks about platform and broker on the CONFIRMATION, not on the way
# in: a question before the address costs sign-ups, and the address is worth
# more than the answer. So a second call must be able to fill in a blank.
W.join("later@example.com", source="landing")
_r = W.join("later@example.com", platform="mt4", broker="XM")
check("answering afterwards is recorded", _r.get("answered") is True, json.dumps(_r))
_lr = _store._read(W._key("later@example.com"))
check("and lands on the original record",
      _lr.get("platform") == "mt4" and _lr.get("broker") == "XM", json.dumps(_lr))
check("the original joining moment is untouched",
      _lr.get("joinedAt") is not None)

# But it cannot REWRITE an answer, and cannot clear one.
W.join("later@example.com", platform="ctrader", broker="Someone Else")
_lr2 = _store._read(W._key("later@example.com"))
check("a later call cannot overwrite what was already said",
      _lr2.get("platform") == "mt4" and _lr2.get("broker") == "XM",
      json.dumps(_lr2))
_r3 = W.join("later@example.com")
check("and a call with nothing to add says so",
      _r3.get("answered") is False, json.dumps(_r3))
check("nor can it clear an answer",
      _store._read(W._key("later@example.com")).get("platform") == "mt4")

print("\n[10] the tally, which is the point of asking")
W.join("a1@example.com", platform="mt5", broker="IC Markets")
W.join("a2@example.com", platform="mt5", broker="ic markets")
W.join("a3@example.com", platform="ctrader", broker="Pepperstone")
_t = W.tally()
check("platforms are counted", _t["platforms"].get("mt5", 0) >= 3,
      json.dumps(_t["platforms"]))
check("brokers are counted case-insensitively",
      _t["brokers"].get("ic markets", 0) >= 3, json.dumps(_t["brokers"]))
check("the most common platform comes first",
      list(_t["platforms"])[0] == "mt5", json.dumps(_t["platforms"]))
check("and it reports how many people answered at all, not only the winners",
      _t["answered"] < _t["total"],
      f"answered {_t['answered']} of {_t['total']}")

print("\n[11] the two new fields reach the record over HTTP")
_st, _b = post("http2@example.com", "landing", ip="203.0.113.21")
check("a plain sign-up still works", _st == 200, f"{_st}")
_res = _API._handle("POST", "/api/v1/waitlist", headers={},
                    body=json.dumps({"email": "wired@example.com",
                                     "source": "landing",
                                     "platform": "mt4",
                                     "broker": "XM Global"}),
                    client_key="203.0.113.22")
check("the route accepts them", _res[0] == 200, json.dumps(_res[1]))
_w = _store._read(W._key("wired@example.com"))
check("and they land on the record",
      _w.get("platform") == "mt4" and _w.get("broker") == "XM Global",
      json.dumps({k: _w.get(k) for k in ("platform", "broker")}))
check("while the response still carries only a status",
      set(_res[1]) <= {"ok", "status"}, str(sorted(_res[1])))

print("\n[4] the source is ours or it is nothing")
W.join("src@example.com", source="landing")
check("a known source is kept",
      _store._read(W._key("src@example.com"))["source"] == "landing")
W.join("evil@example.com", source="https://attacker.test/?x=1")
check("an arbitrary one is not stored",
      _store._read(W._key("evil@example.com"))["source"] == "direct",
      _store._read(W._key("evil@example.com"))["source"])

print("\n[5] the export is for the operator, not for the API")
dump = W.export()
check("it returns the addresses in the clear, for the operator",
      "trader@example.com" in [e["email"] for e in dump["entries"]],
      json.dumps([e["email"] for e in dump["entries"]]))
check("ordered by when they joined",
      [e["joinedAt"] for e in dump["entries"]]
      == sorted(e["joinedAt"] for e in dump["entries"]))
check("and an index entry with no record is reported, never skipped silently",
      isinstance(dump.get("unresolved"), list))
_store._set_add(W._k_index(), "forex:a4t:waitlist:ghost")
# A record whose address will not decrypt is a sign-up, not a blank row.
# decrypt_value answers "" for both "nothing there" and "wrong key", so an
# export that trusted it would silently drop real people.
_store._write(W._key("broken@example.com"),
              {"email": user_store._ENC_PREFIX + "not-valid-ciphertext",
               "joinedAt": 1, "source": "landing"})
_store._set_add(W._k_index(), W._key("broken@example.com"))
_d = W.export()
check("a record that will not decrypt is reported, not emitted blank",
      W._key("broken@example.com") in _d.get("unreadable", []),
      json.dumps(_d.get("unreadable")))
check("and no empty address reaches the export",
      all(e["email"] for e in _d["entries"]),
      json.dumps([e["email"] for e in _d["entries"]]))

check("a dangling index entry shows up as unresolved",
      "forex:a4t:waitlist:ghost" in W.export()["unresolved"],
      json.dumps(W.export()["unresolved"]))

print("\n[6] over HTTP")
st, b = post("http@example.com", "landing")
check("a good address is accepted", st == 200, f"{st} {json.dumps(b)}")
check("the answer says it was added", b.get("status") == "added", json.dumps(b))
check("and carries no address back", "http@example.com" not in json.dumps(b),
      json.dumps(b))
check("nothing else leaks into the body",
      set(b) <= {"ok", "status"}, str(sorted(b)))

st, b = post("http@example.com", "landing", ip="203.0.113.2")
check("a repeat is a 200, not an error", st == 200, f"{st} {json.dumps(b)}")
check("and says so", b.get("status") == "already", json.dumps(b))

st, b = post("not-an-email", ip="203.0.113.3")
check("a bad address is a 400", st == 400, f"{st} {json.dumps(b)}")
check("with a code the form can branch on",
      (b.get("error") or {}).get("code") == "EMAIL_INVALID", json.dumps(b))

st, b = post("", ip="203.0.113.4")
check("an empty one is refused too", st == 400, f"{st}")

# No session anywhere in the above: that is the point of the route.
st, b = post("nosession@example.com", ip="203.0.113.5")
check("none of this needed a session", st == 200, f"{st} {json.dumps(b)}")

print("\n[7] the form is rate limited on its own budget")
# Its own bucket, so hammering it cannot exhaust the one the dashboard polls
# through — and so the dashboard's generous limit cannot be borrowed here.
from apex.platform import ratelimit as _rl              # noqa: E402

check("the route classifies into its own bucket",
      _rl.classify("POST", "waitlist") == "waitlist",
      _rl.classify("POST", "waitlist"))
check("which is tighter than the default",
      _rl.LIMITERS["waitlist"].limit < _rl.LIMITERS["default"].limit,
      f"{_rl.LIMITERS['waitlist'].limit} vs {_rl.LIMITERS['default'].limit}")

codes = [post(f"flood{i}@example.com", ip="198.51.100.99")[0] for i in range(12)]
check("a flood from one address is refused before it fills the list",
      429 in codes, str(codes))
check("but the first ones got through, so the limit is not simply 'off'",
      codes[0] == 200, str(codes[:3]))

print("\n[8] a GET is not a sign-up")
res = _API._handle("GET", "/api/v1/waitlist", headers={},
                   client_key="203.0.113.6")
check("GET does not join anybody",
      res is None or res[0] != 200, str(res and res[0]))

print("\n[9] an address can be taken off the list")
# Somebody who asked to be told may ask to be forgotten. Until there was a
# remove(), the only honest answer was that we could not.
W.join("erase.me@example.com", source="landing")
before = W.count()
addresses = [e["email"] for e in W.export()["entries"]]
check("the address is on the list to begin with",
      "erase.me@example.com" in addresses, str(addresses))

out = W.remove("erase.me@example.com")
check("removing it says so", out.get("status") == "removed", json.dumps(out))
check("the count drops by exactly one", W.count() == before - 1,
      f"{W.count()} vs {before}")

dump = W.export()
check("and the address is gone from the export",
      "erase.me@example.com" not in [e["email"] for e in dump["entries"]],
      str([e["email"] for e in dump["entries"]]))
# The index entry must go with the record. If it stayed, export() would
# report it forever as an unresolved key — a deletion that leaves a scar.
# (Section 5 plants its own ghost on purpose, so this asks about THIS key.)
check("leaving no unresolved index entry behind",
      W._key("erase.me@example.com") not in dump["unresolved"],
      str(dump["unresolved"]))

out = W.remove("erase.me@example.com")
check("removing it again is 'absent', not an error",
      out.get("status") == "absent", json.dumps(out))
out = W.remove("never.joined@example.com")
check("so is removing somebody who never joined",
      out.get("status") == "absent", json.dumps(out))

# Case is folded on the way in, so it must be folded on the way out too —
# otherwise an erasure request typed with a capital letter silently does
# nothing and reports "absent", which reads as "you were not on the list".
W.join("mixedcase@example.com")
out = W.remove("  MixedCase@Example.COM ")
check("an address joined in one case is removed in another",
      out.get("status") == "removed", json.dumps(out))

try:
    W.remove("not-an-email")
    check("a bad address is refused rather than quietly deleting nothing",
          False, "it returned instead of raising")
except W.WaitlistError as e:
    check("a bad address is refused rather than quietly deleting nothing",
          e.code == "EMAIL_INVALID", e.code)

# Removal is operator tooling. A public route that deletes by address would
# let anyone remove anyone, and tell them who is on the list while doing it.
res = _API._handle("DELETE", "/api/v1/waitlist", headers={},
                   body=json.dumps({"email": "erase.me@example.com"}),
                   client_key="203.0.113.7")
check("there is no API route that removes an address",
      res is None or res[0] != 200, str(res and res[0]))

shutil.rmtree(_TMP, ignore_errors=True)

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All waitlist checks passed.")
