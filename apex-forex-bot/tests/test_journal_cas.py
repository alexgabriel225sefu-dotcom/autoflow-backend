"""Two writers to the journal cannot silently drop a trade.

WHY THIS TEST EXISTS

The user's account record has had compare-and-set for a long time; the journal
had none. append_trade read the whole list, appended, and wrote it back, and
its own comment said so. Two writers to the same journal are not hypothetical
here — they are documented: the trading loop books a closed trade while an
operator runs mark_journal_artefacts.py or purge_bad_trades.py against the same
live account. Whichever write lands second wins outright, and the row the other
one added is gone. No exception, no log line, nothing to notice afterwards.

That is the same damage as the false -$27,052 report, reached by losing a row
rather than by trusting a bad one. The journal is also the one record a client
cannot reconstruct: the tax export reads it.

WHY APPEND RETRIES INSTEAD OF FAILING

The caller is a loop booking a trade that has already happened at the broker.
A refusal gives it nothing it can act on and the record cannot be produced
again, so a conflict is re-read and re-applied rather than reported. A full
rewrite — the migrations — is the opposite: it gets the conflict, because
silently rewriting on top of someone else's change is the bug.

Run: python tests/test_journal_cas.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("PRODUCT", "forex")

from apex import user_store as us  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"  OK   {name}" if cond else f"  FAIL {name} {detail}")
    if not cond:
        failures.append(name)


class FakeStore:
    """In-memory backend implementing the semantics of _LUA_SAVE_TRADES.

    Not a Lua interpreter — the point is to exercise the CALLER: does it read a
    version, pass it, notice a mismatch, and retry rather than overwrite.
    """

    def __init__(self):
        self.kv = {}
        self.on_write = None   # hook: fires once, mid-write, like a rival writer

    def get(self, key):
        return self.kv.get(key)

    def eval(self, script, keys, args):
        payload, expected = args[0], args[1]
        vkey = keys[1]
        if self.on_write is not None:
            hook, self.on_write = self.on_write, None
            hook()
        if expected != "":
            cur = self.kv.get(vkey, "0")
            if str(cur) != str(expected):
                return -1
        self.kv[keys[0]] = payload
        self.kv[vkey] = str(int(self.kv.get(vkey, "0")) + 1)
        return int(self.kv[vkey])


_orig = (us._USE_REDIS, us._redis_get, us._redis_set, us._eval)
fake = FakeStore()
us._USE_REDIS = True
us._redis_get = fake.get
us._redis_set = lambda k, v: (fake.kv.__setitem__(k, v), True)[1]
us._eval = fake.eval

try:
    UID = "cas-user"

    print("\n1. The journal has a version of its own")
    check("it starts at zero", us.trades_version(UID) == 0,
          str(us.trades_version(UID)))
    us.save_trades(UID, [{"symbol": "EURUSD"}])
    check("a write bumps it", us.trades_version(UID) == 1,
          str(us.trades_version(UID)))
    check("it is separate from the record's version",
          us._tvkey(UID) != us._vkey(UID))

    print("\n2. A rewrite that names a stale version is REFUSED, not applied")
    stale = us.trades_version(UID)
    us.save_trades(UID, [{"symbol": "GBPUSD"}])          # somebody else writes
    try:
        us.save_trades(UID, [{"symbol": "WIPED"}], expect_version=stale)
        check("a stale rewrite raises", False, "it was accepted")
    except us.TradeJournalConflict as e:
        check("a stale rewrite raises TradeJournalConflict", True)
        check("...and says what it expected", "expected v" in str(e), str(e))
    survived = us.load_trades(UID, include_artefacts=True)
    check("the other writer's row is still there",
          survived == [{"symbol": "GBPUSD"}], str(survived))

    print("\n3. Callers that pass no version are unchanged")
    check("a plain rewrite still succeeds",
          us.save_trades(UID, [{"symbol": "MIGRATED"}]) is True,
          "the backfill and migrations pass no version and must keep working")

    print("\n4. THE BUG: an append racing another writer loses nothing")
    us.save_trades(UID, [{"symbol": "OLD"}])
    rival = {"symbol": "RIVAL-OPERATOR-ROW"}

    def rival_writes():
        # Lands between the append's version read and its write — exactly the
        # window that used to swallow one of the two rows.
        current = us.load_trades(UID, include_artefacts=True)
        us.save_trades(UID, current + [rival])

    fake.on_write = rival_writes
    us.append_trade(UID, {"symbol": "APPENDED-BY-LOOP"})
    final = us.load_trades(UID, include_artefacts=True)
    syms = [t["symbol"] for t in final]
    check(f"the rival's row survived ({syms})", "RIVAL-OPERATOR-ROW" in syms)
    check("the appended row survived too", "APPENDED-BY-LOOP" in syms)
    check("both are present, not one", len(final) == 3, str(len(final)))

    print("\n5. An append never raises at its caller")
    fake.on_write = None
    try:
        us.append_trade(UID, {"symbol": "QUIET"})
        check("a normal append returns cleanly", True)
    except Exception as e:
        check("a normal append returns cleanly", False, repr(e))

    print("\n6. The 500-row bound still holds")
    us.save_trades(UID, [{"i": i} for i in range(600)])
    kept = us.load_trades(UID, include_artefacts=True)
    check("kept at 500", len(kept) == 500, str(len(kept)))
    check("...the NEWEST 500", kept[-1]["i"] == 599, str(kept[-1]))
finally:
    us._USE_REDIS, us._redis_get, us._redis_set, us._eval = _orig

print("\n" + "=" * 50)
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:6])}")
    sys.exit(1)
print("ALL CHECKS PASSED - a race adds a row, it does not replace one.")
