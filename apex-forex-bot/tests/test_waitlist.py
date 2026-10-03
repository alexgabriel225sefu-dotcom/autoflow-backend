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
check("only the three fields we asked for are kept",
      set(raw) == {"email", "joinedAt", "source"}, str(sorted(raw)))

# The hash is keyed. An unkeyed SHA-256 of an email is a pseudonym, not a
# protection: the input space is small enough to enumerate.
import hashlib                                          # noqa: E402

check("the key is not a bare digest anyone could recompute",
      hashlib.sha256(b"trader@example.com").hexdigest()
      not in W._key("trader@example.com"))

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

shutil.rmtree(_TMP, ignore_errors=True)

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All waitlist checks passed.")
