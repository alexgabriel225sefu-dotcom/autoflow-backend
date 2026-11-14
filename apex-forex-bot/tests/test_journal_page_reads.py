"""A page of the journal is ONE read, and a row it cannot read is counted, not dropped.

WHY THIS EXISTS

An independent review measured `journal_store.query` as an index read plus up
to 25 single-key reads, one after another, and found two honesty problems in
the same loop:

* a row the store could not return was SKIPPED, so the page came back one entry
  short with status "ok" while `total` still counted it;
* the index itself was read with the forgiving reader, so a store that was down
  looked like a journal with nothing in it.

WHAT THESE TESTS WILL NOT ACCEPT

* more than one shared-store round trip for the rows of a page, however many
  rows it holds;
* an entry the index names and the store cannot produce being silently absent:
  it is reported in `unreadable`;
* an unreachable store answering 200 with an empty list instead of the 503 every
  other route gives;
* another client's row ever appearing in a page, whatever the index says;
* the batch reader returning anything but a list aligned with its keys.

Run: python3 tests/test_journal_page_reads.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="a4t-jpage-")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ["APP_ENV"] = "dev"
os.environ["PRODUCT"] = "forex"

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


from apex import user_store as US                            # noqa: E402
from apex.platform import api as API                         # noqa: E402
from apex.platform import journal as J                       # noqa: E402
from apex.platform import journal_store as JS                # noqa: E402

OWNER, OTHER = "owner-1", "owner-2"


def add(user, n, tag="e"):
    ids = []
    for i in range(n):
        e = JS.record_error(f"{tag} {i}", correlation_id=f"c-{tag}-{i}",
                            user_id=user, account_id="1")
        ids.append(e.entry_id)
    return ids


print("\n[1] a page is one batch read, however many rows it holds")
ids = add(OWNER, 12)
calls = {"many": 0, "single_entry": 0}
_many, _read = JS._store._read_many_strict, JS._store._read


def counting_many(keys):
    calls["many"] += 1
    return _many(keys)


def counting_read(key):
    if ":jentry:" in str(key):
        calls["single_entry"] += 1
    return _read(key)


JS._store._read_many_strict, JS._store._read = counting_many, counting_read
try:
    page = JS.query(OWNER, limit=10)
finally:
    JS._store._read_many_strict, JS._store._read = _many, _read
check("ten rows came back", len(page["entries"]) == 10, str(len(page["entries"])))
check("in exactly one batch read", calls["many"] == 1, str(calls))
check("with no per-row single reads", calls["single_entry"] == 0, str(calls))
check("total and paging are unchanged", page["total"] == 12 and page["hasMore"] is True)
check("nothing was lost, so unreadable is 0", page["unreadable"] == 0, str(page["unreadable"]))
check("newest first, as before",
      [e["entryId"] for e in page["entries"]] == list(reversed(ids))[:10])

print("\n[2] a row the store cannot produce is COUNTED, not skipped")
gone = ids[5]
os.remove(JS._store._local_path(JS._k_entry(OWNER, gone)))
page = JS.query(OWNER, limit=50)
check("the page has one fewer row", len(page["entries"]) == 11, str(len(page["entries"])))
check("total still says 12, because the index does", page["total"] == 12)
check("and the difference is reported, not hidden", page["unreadable"] == 1, str(page["unreadable"]))
check("the missing one is not among the rows", gone not in [e["entryId"] for e in page["entries"]])

with open(JS._store._local_path(JS._k_entry(OWNER, ids[6])), "w") as f:
    f.write("{not json")
page = JS.query(OWNER, limit=50)
check("a corrupt row is counted too", page["unreadable"] == 2, str(page["unreadable"]))
check("and the rest of the page is intact", len(page["entries"]) == 10, str(len(page["entries"])))

print("\n[3] another client's row never appears, whatever the index says")
other_ids = add(OTHER, 1, tag="x")
idx = JS._store._read(JS._k_index(OWNER))
idx.append({"id": other_ids[0], "ts": 9e9, "status": "broker_error"})
JS._store._write(JS._k_index(OWNER), idx)
# The OTHER client's entry lives under THEIR key, so the owner's index naming
# it points at a key that does not exist for them: it is unreadable, not shown.
page = JS.query(OWNER, limit=50)
check("it is not shown", other_ids[0] not in [e["entryId"] for e in page["entries"]])
check("and it is counted as unreadable, never leaked", page["unreadable"] >= 3, str(page["unreadable"]))
foreign_row = JS._store._read(JS._k_entry(OTHER, other_ids[0]))
JS._store._write(JS._k_entry(OWNER, other_ids[0]), foreign_row)
page = JS.query(OWNER, limit=50)
check("even a copy of it under the owner's own key is refused (userId differs)",
      other_ids[0] not in [e["entryId"] for e in page["entries"]])

print("\n[4] an unreachable store is a 503, never an empty journal")
_ms, _rs = JS._store._read_many_strict, JS._store._read_strict


def down(*a, **k):
    raise US.StoreUnavailable("redis MGET failed: ConnectionError")


JS._store._read_many_strict = down
try:
    try:
        JS.query(OWNER)
        raised = False
    except US.StoreUnavailable:
        raised = True
finally:
    JS._store._read_many_strict = _ms
check("a failed batch read raises", raised)

JS._store._read_strict = down
try:
    try:
        JS.query(OWNER)
        raised = False
    except US.StoreUnavailable:
        raised = True
finally:
    JS._store._read_strict = _rs
check("a failed index read raises, not an empty list", raised)

print("\n[5] the batch reader itself")


class _R:
    def __init__(self, data=None, boom=False, short=False):
        self.data, self.boom, self.short = data or {}, boom, short

    def mget(self, keys):
        if self.boom:
            raise ConnectionError("down")
        out = [self.data.get(k) for k in keys]
        return out[:-1] if self.short else out


_save = (US._USE_REDIS, US._BACKEND, US._r)
try:
    US._USE_REDIS, US._BACKEND = True, "redis"
    US._r = _R({"a": "1", "c": "3"})
    check("aligned with the keys, a missing one is None",
          US.get_blobs_strict(["a", "b", "c"]) == ["1", None, "3"])
    check("an empty key list asks nothing", US.get_blobs_strict([]) == [])
    US._r = _R(boom=True)
    try:
        US.get_blobs_strict(["a"])
        ok = False
    except US.StoreUnavailable:
        ok = True
    check("an unreachable store raises StoreUnavailable", ok)
    US._r = _R({"a": "1"}, short=True)
    try:
        US.get_blobs_strict(["a", "b"])
        ok = False
    except US.StoreUnavailable:
        ok = True
    check("an answer that does not match the keys raises", ok)
    US._BACKEND = "upstash"
    _post = US._upstash_post_strict
    US._upstash_post_strict = lambda cmd: ["x", None] if cmd[0] == "MGET" else None
    check("the Upstash path sends one MGET and keeps alignment",
          US.get_blobs_strict(["k1", "k2"]) == ["x", None])
    US._upstash_post_strict = lambda cmd: "not a list"
    try:
        US.get_blobs_strict(["k1"])
        ok = False
    except US.StoreUnavailable:
        ok = True
    check("and a malformed Upstash answer raises", ok)
    US._upstash_post_strict = _post
finally:
    US._USE_REDIS, US._BACKEND, US._r = _save

print("\n[6] through the API: the count reaches the browser, a down store is a 503")
_orig_auth = API._authenticate


class _P:
    user_id = OWNER


API._authenticate = lambda headers: _P()
try:
    st, body = API.handle("GET", "/api/v1/journal?limit=50", {})
    JS._store._read_many_strict = down
    st_down, body_down = API.handle("GET", "/api/v1/journal?limit=50", {})
finally:
    JS._store._read_many_strict = _ms
    API._authenticate = _orig_auth
check("the journal route answers 200 and carries `unreadable`",
      st == 200 and "unreadable" in str(body), f"{st} {str(body)[:160]}")
check("a down store answers 503 STORE_UNAVAILABLE, not 200 with fewer rows",
      st_down == 503 and "STORE_UNAVAILABLE" in str(body_down),
      f"{st_down} {str(body_down)[:160]}")

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("All journal page-read checks passed.")
