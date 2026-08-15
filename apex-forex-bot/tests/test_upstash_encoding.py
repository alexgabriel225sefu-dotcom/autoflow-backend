"""Upstash REST arguments are path segments and must be percent-encoded.

Each command argument becomes one segment of the URL. An unencoded slash
therefore silently becomes an argument separator:

    SET  skipalert:758:EURUSD|at max positions (1/1)  1  NX  EX  10800
              ↓ without encoding
    /SET/skipalert:758:EURUSD|at max positions (1/1)/1/NX/EX/10800
                                                  ^ new argument

A 6-argument SET arrives as 7, under a truncated key. Spaces were being
encoded by requests as a side effect; slashes never were. Every key in use was
alphanumeric, so this stayed latent until a skip-alert key carried a
human-readable reason like "at max positions (1/1)".

`safe=":"` is load-bearing in the fix: the namespace separator in
`forex:user:123` must stay literal or every existing key changes and the whole
store reads as empty.

Run: python tests/test_upstash_encoding.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Tests are a development environment and say so explicitly: user_store now
# REFUSES to start without TOKEN_ENCRYPTION_KEY rather than falling back to
# plaintext, and that refusal is the behaviour under test elsewhere.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-enc-test-")

from apex import user_store  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


# Capture the URL _upstash builds without touching the network.
built = []


class FakeResp:
    status_code = 200

    @staticmethod
    def raise_for_status():
        pass

    @staticmethod
    def json():
        return {"result": "OK"}


def fake_get(url, **kw):
    built.append(url)
    return FakeResp()


user_store._UPD_URL = "https://example.upstash.io"
user_store._UPD_TOKEN = "t"
user_store._req.get = fake_get


def url_for(parts):
    built.clear()
    user_store._upstash(parts)
    return built[0]


print("\n── existing keys must not change ──")
u = url_for(["GET", "forex:user:7585109158"])
check("colons stay literal", u.endswith("/GET/forex:user:7585109158"), u)
check("no percent-escapes appear at all", "%" not in u, u)
u = url_for(["SMEMBERS", "forex:active_users"])
check("underscores are untouched", u.endswith("/SMEMBERS/forex:active_users"), u)

print("\n── THE BUG: a slash in an argument used to split it in two ──")
u = url_for(["SET", "skipalert:758:EURUSD|at max positions (1/1)",
             "1", "NX", "EX", 10800])
check("the slash is encoded, not passed through",
      "%2F1" in u and "/1/NX/" in u, u)
check("the command still has exactly 6 segments after the host",
      len(u.split("/")[3:]) == 6, str(u.split("/")[3:]))
check("and it still ends with the TTL", u.endswith("/10800"), u)

print("\n── spaces are encoded explicitly rather than incidentally ──")
u = url_for(["SET", "skipalert:758:XAUUSD|HTF gate: BUY blocked by H1 BEARISH trend",
             "1", "NX", "EX", 10800])
check("no raw spaces survive", " " not in u, u)
check("still 6 segments", len(u.split("/")[3:]) == 6, str(u.split("/")[3:]))

print("\n── a JSON value with a slash is one argument, not several ──")
import json  # noqa: E402

val = json.dumps({"symbol": "EUR/USD", "note": "a b", "n": 1})
u = url_for(["SET", "forex:user:1", val])
check("SET stays 3 arguments", len(u.split("/")[3:]) == 3,
      str(u.split("/")[3:]))
check("the embedded slash is escaped", "%2F" in u, u)

print("\n── round-trip: decoding gives back exactly what went in ──")
from urllib.parse import unquote  # noqa: E402

for arg in ("at max positions (1/1)",
            "HTF gate: BUY blocked by H1 BEARISH trend",
            "spread too wide (2.4p > 1.5p)",
            'edge too thin: TP 70p vs costs 1.8p',
            "forex:user:123",
            val):
    u = url_for(["SET", arg])
    seg = u.split("/", 4)[4] if arg == val else u.split("/")[-1]
    check(f"{arg[:34]!r} survives", unquote(seg) == arg, f"{unquote(seg)!r}")

print("\n── claim() builds a valid NX/EX command ──")
built.clear()
user_store._BACKEND = "upstash"
user_store._USE_REDIS = True
got = user_store.claim("skipalert:758:EURUSD|at max positions (1/1)", ttl_s=10800)
check("returns True on OK", got is True, str(got))
check("NX and EX are present and unmangled",
      built and built[0].endswith("/1/NX/EX/10800"), str(built))

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed: {', '.join(failures)}")
    sys.exit(1)
print("✅ ALL UPSTASH-ENCODING CHECKS PASSED.")
