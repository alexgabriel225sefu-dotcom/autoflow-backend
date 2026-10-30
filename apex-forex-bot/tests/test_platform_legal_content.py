"""Legal drafts stay unpublished until the owner names the version.

The pages can be read. Recording them as the version a client must accept
requires A4T_LEGAL_PUBLISH to equal the draft version, and then an operator
call. Importing this code does neither.

Run: python3 tests/test_platform_legal_content.py
"""
import json
import os
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(ROOT)
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-legal-")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"
os.environ.pop("A4T_LEGAL_PUBLISH", None)
os.environ.pop("A4T_LIVE_EXECUTION", None)
os.environ.pop("APEX_ALLOW_LIVE_ACCOUNTS", None)

from apex import user_store                              # noqa: E402

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


class Fake:
    def __init__(self):
        self.lock = threading.Lock()
        self.data = {}

    def install(self):
        user_store._USE_REDIS = True
        user_store._BACKEND = "redis"
        for name in ("set_blob_nx", "set_blob", "get_blob", "get_blob_strict",
                     "del_blob", "claim", "claim_value", "release_claim", "incr"):
            setattr(user_store, name, getattr(self, name))

    def set_blob_nx(self, key, value):
        with self.lock:
            if key in self.data:
                return False
            self.data[key] = value
            return True

    def set_blob(self, key, value, ttl_s=None):
        with self.lock:
            self.data[key] = value
        return True

    def get_blob(self, key):
        with self.lock:
            return self.data.get(key)

    def get_blob_strict(self, key):
        return self.get_blob(key)

    def del_blob(self, key):
        with self.lock:
            return self.data.pop(key, None)

    def claim(self, key, ttl_s=120):
        return self.claim_value(key, "1", ttl_s=ttl_s)

    def claim_value(self, key, value, ttl_s=120):
        with self.lock:
            if key in self.data:
                return False
            self.data[key] = str(value)
            return True

    def release_claim(self, key, value):
        with self.lock:
            if self.data.get(key) != str(value):
                return False
            del self.data[key]
        return True

    def incr(self, key, ttl_s=60):
        with self.lock:
            self.data[key] = int(self.data.get(key, 0)) + 1
            return self.data[key]


Fake().install()

from apex.platform import legal_content as LC             # noqa: E402
from apex.platform import live_gate as LG                 # noqa: E402
from apex.platform import store as ST                     # noqa: E402

ACTOR = "operator-1"
CLIENT = "client-1"

print("\n[1] the draft version matches the pages, and nothing is published")
web_version = open(os.path.join(
    REPO, "web", "src", "content", "legal-publication.ts"), encoding="utf-8").read()
check("the web version constant is this draft",
      f'LEGAL_VERSION = "{LC.CURRENT_VERSION}"' in web_version, web_version)
check("the draft mark is the one the pages show",
      LC.DRAFT_MARK == "DRAFT - requires legal review")
check("the document ids are the live gate's",
      LC.DOCUMENTS == LG.DOCUMENTS, str(LC.DOCUMENTS))
shell = open(os.path.join(
    REPO, "web", "src", "components", "legal", "draft-shell.tsx"),
    encoding="utf-8").read()
for token in LC.PLACEHOLDERS:
    check(f"the company block keeps {token}", "{{" + token + "}}" in shell)
for page in ("terms/page.tsx", "refunds/page.tsx", "tax/page.tsx"):
    body = open(os.path.join(REPO, "web", "src", "app", page), encoding="utf-8").read()
    check(f"{page} is marked as a draft",
          "DRAFT - requires legal review" in body and "not final" in body)
    check(f"{page} renders the company placeholders", "CompanyBlock" in body)
check("import does not publish",
      LC.published_version() is None and LC.status()["published"] is False)
check("the live gate has no published versions",
      ST._read_strict(LG._key("published")) is None)

print("\n[2] the env has to name this version, and an operator has to call")
for bad in ("true", "1", "yes", "on", "2020-01-01", LC.CURRENT_VERSION + "-draft"):
    os.environ["A4T_LEGAL_PUBLISH"] = bad
    check(f"{bad!r} does not publish", LC.published_version() is None, bad)
    try:
        LC.publish_current(ACTOR)
        check(f"{bad!r} refused the write", False, "publish_current returned")
    except LG.LiveGateError as e:
        check(f"{bad!r} is unpublished", e.code == "UNPUBLISHED" and e.status == 409,
              f"{e.code} {e.status}")
check("a wrong value wrote nothing", ST._read_strict(LG._key("published")) is None)

os.environ["A4T_LEGAL_PUBLISH"] = LC.CURRENT_VERSION
check("the exact version is the published one",
      LC.published_version() == LC.CURRENT_VERSION)
try:
    LC.publish_current("")
    check("a blank actor is refused", False)
except LG.LiveGateError as e:
    check("a blank actor is refused", e.code == "NO_ACTOR", e.code)
written = LC.publish_current(ACTOR)
check("the operator call reports published", written["published"] is True, str(written))
stored = ST._read_strict(LG._key("published"))
check("terms, refund and tax are that version",
      all((stored.get(doc) or {}).get("version") == LC.CURRENT_VERSION
          for doc in LC.DOCUMENTS), str(stored))

os.environ.pop("A4T_LEGAL_PUBLISH", None)
check("clearing the env unpublishes the public status",
      LC.status()["published"] is False and LC.status()["notice"] == LC.DRAFT_MARK)
check("and does not pretend the variable is still set",
      LC.published_version() is None)

print("\n[3] the HTTP step is operator-only and ignores a version in the body")
import apex.platform.identity as ID                       # noqa: E402
from apex.platform import api as A                        # noqa: E402


class _Principal:
    def __init__(self, user_id):
        self.user_id = user_id
        self.email = "person@example.test"
        self.email_verified = True

    def as_dict(self):
        return {"userId": self.user_id, "email": self.email, "emailVerified": True}


ID.verify_token = lambda token, **_kw: _Principal(ACTOR if token == "op" else CLIENT)
os.environ[LG.OPERATOR_ENV] = ACTOR
ST._delete(LG._key("published"))


def call(token, body=None):
    raw = json.dumps(body or {}).encode()
    return A.handle("POST", "/api/v1/live/terms/publish-current",
                    {"Authorization": f"Bearer {token}"}, raw)


status, payload = call("client", {"version": "attacker"})
check("a client cannot publish",
      status == 403 and payload["error"]["code"] == "NOT_OPERATOR", str(payload))
check("the body did not publish a version",
      ST._read_strict(LG._key("published")) is None)

status, payload = call("op", {"version": "attacker"})
check("without the env the operator is refused",
      status == 409 and payload["error"]["code"] == "UNPUBLISHED", str(payload))
check("still nothing stored", ST._read_strict(LG._key("published")) is None)

os.environ["A4T_LEGAL_PUBLISH"] = LC.CURRENT_VERSION
status, payload = call("op", {"version": "not-the-draft"})
pub = (payload or {}).get("publication") or {}
stored = ST._read_strict(LG._key("published")) or {}
check("the operator publishes the repo version, not the body",
      status == 200 and pub.get("version") == LC.CURRENT_VERSION
      and stored.get("terms", {}).get("version") == LC.CURRENT_VERSION
      and "not-the-draft" not in json.dumps(stored), str(payload)[:300])

os.environ.pop("A4T_LEGAL_PUBLISH", None)
os.environ.pop(LG.OPERATOR_ENV, None)

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for item in _fails:
        print("  -", item)
    sys.exit(1)
print("All legal-content checks passed.")
