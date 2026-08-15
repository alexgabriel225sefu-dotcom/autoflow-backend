"""Tests for walk-forward validation and the history corpus.

The point of both modules is to stop a fitted result from being mistaken for an
edge, so most of these check that the machinery says NO when it should — a
validator that always passes is worse than none.

Run: python tests/test_walkforward.py
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
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

from apex import walkforward as wf  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}")
        failures.append(name)


def _refuses(fn):
    """True if fn() raises — used to assert a guard actually guards."""
    try:
        fn()
        return False
    except Exception:
        return True

print("\n── splits are chronological and non-overlapping in test ──")
s = list(wf.splits(100, train=40, validate=10, test=10, step=10))
check("produces the expected number of windows", len(s) == 5, str(len(s)))
tr, va, te = s[0]
check("train precedes validate precedes test",
      tr.stop == va.start and va.stop == te.start)
check("first window starts at 0", tr.start == 0)
check("test blocks advance by step",
      s[1][2].start - s[0][2].start == 10)
check("no window runs past the data", all(t.stop <= 100 for _, _, t in s))
check("too little history yields no windows",
      list(wf.splits(30, 40, 10, 10)) == [])

try:
    list(wf.splits(100, 0, 10, 10))
    check("rejects a zero-length block", False, "no error raised")
except ValueError:
    check("rejects a zero-length block", True)

print("\n── a strategy with no edge must FAIL ──")
bars = list(range(12000))


def flat(_slice, _params):
    # Alternating +1R/-1R, minus cost: a coin flip that pays the spread.
    return [1.0 - 0.1, -1.0 - 0.1] * 20


res = wf.run(bars, flat, train=4000, validate=1000, test=1000)
ok, why = wf.verdict(res)
check("no-edge strategy is rejected", ok is False, why)
check("and the reason names the negative expectancy", "expectancy" in why, why)

print("\n── a genuine, consistent edge must PASS ──")


def edged(_slice, _params):
    # 45% winners at 2R, 55% losers at 1R → +0.35R expectancy before costs.
    return ([2.0 - 0.1] * 45 + [-1.0 - 0.1] * 55)


res_ok = wf.run(bars, edged, train=4000, validate=1000, test=1000)
ok, why = wf.verdict(res_ok)
check("consistent edge is accepted", ok is True, why)
check("out-of-sample expectancy is positive",
      res_ok["out_of_sample"]["expectancy_R"] > 0)
check("every window scored", res_ok["windows_scored"] == len(
    list(wf.splits(12000, 4000, 1000, 1000))))
check("consistency reported as a fraction", 0.0 <= res_ok["consistency"] <= 1.0)

print("\n── an edge that only worked early must FAIL ──")
_call = {"n": 0}


def decaying(slice_, _params):
    # Strong in the first half of the history, dead in the second — the exact
    # shape of a strategy fitted to an old market regime.
    _call["n"] += 1
    early = slice_[0] < 6000 if slice_ else True
    if early:
        return [2.0] * 40 + [-1.0] * 60
    return [1.0] * 30 + [-1.0] * 70


res_decay = wf.run(bars, decaying, train=3000, validate=500, test=500, step=500)
ok, why = wf.verdict(res_decay)
check("a decaying edge is rejected", ok is False, why)

print("\n── too little history is refused, not guessed at ──")
res_small = wf.run(list(range(5200)), edged, train=4000, validate=500, test=500)
ok, why = wf.verdict(res_small)
check("one window is not enough to conclude", ok is False, why)
check("the reason says so plainly", "not enough history" in why, why)

print("\n── a strategy that never trades is refused ──")
res_none = wf.run(bars, lambda s, p: [], train=4000, validate=1000, test=1000)
ok, why = wf.verdict(res_none)
check("no trades → no verdict", ok is False, why)

print("\n── the test block is scored once, after selection ──")
# Windows overlap by design: window N's test block becomes training data for
# window N+1, so index ranges repeat across windows and cannot identify a call.
# Order can. Each window makes exactly (params x {train, validate}) calls, then
# one call on test — so the test call is the last of each group, and it must
# carry the parameters the window selected.
calls = []


def spy(slice_, params):
    calls.append({"k": params["k"], "start": slice_[0] if slice_ else None})
    return [params["k"] * 0.1, -0.05] * 25


grid = [{"k": 1}, {"k": 2}]
res_spy = wf.run(bars, spy, train=4000, validate=1000, test=1000,
                 param_grid=grid)
windows = list(wf.splits(len(bars), 4000, 1000, 1000))
per_window = len(grid) * 2 + 1

check("evaluate() called exactly once per (param, in-sample block) plus one test",
      len(calls) == len(windows) * per_window,
      f"{len(calls)} vs {len(windows) * per_window}")

for i, (_tr, _va, te) in enumerate(windows):
    group = calls[i * per_window:(i + 1) * per_window]
    in_sample, scored = group[:-1], group[-1]
    check(f"window {i}: test scored last, exactly once",
          scored["start"] == te.start
          and sum(1 for c in group if c["start"] == te.start) == 1,
          str(group))
    check(f"window {i}: no in-sample call touched the test block",
          all(c["start"] != te.start for c in in_sample))
    check(f"window {i}: scored with the selected params",
          scored["k"] == res_spy["windows"][i]["selected"]["k"])

print("\n── return concentration is surfaced ──")
c = wf.concentration([10.0] + [0.1] * 50)
check("a single outlier is flagged", c["top_share"] > 0.6, str(c["top_share"]))
c2 = wf.concentration([0.2] * 50)
check("evenly spread returns are not", c2["top_share"] < 0.15, str(c2["top_share"]))
check("empty input is safe", wf.concentration([])["trades"] == 0)

print("\n── history corpus: merge and round-trip ──")
import collect_history as ch  # noqa: E402

ch.DATA_DIR = tempfile.mkdtemp(prefix="apex-hist-test-")

A = [{"time": 100, "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 10},
     {"time": 200, "open": 1.5, "high": 2.5, "low": 1, "close": 2, "volume": 12}]
B = [{"time": 200, "open": 1.5, "high": 9.9, "low": 1, "close": 2, "volume": 12},
     {"time": 50, "open": 0.9, "high": 1.1, "low": 0.8, "close": 1, "volume": 8}]

m = ch.merge(A, B)
check("merge dedupes on timestamp", len(m) == 3, str(len(m)))
check("merge sorts oldest first", [c["time"] for c in m] == [50, 100, 200])
check("later data wins a collision",
      next(c for c in m if c["time"] == 200)["high"] == 9.9)
check("merging is idempotent", ch.merge(m, m) == m)

ch.save("EURUSD", "1min", m)
back = ch.load("EURUSD", "1min")
check("saved bars load back identically",
      [c["time"] for c in back] == [50, 100, 200])
check("prices survive the round trip", back[2]["high"] == 9.9)
check("missing file is an empty corpus, not an error",
      ch.load("NOPE", "1min") == [])
check("a re-save after merge does not duplicate",
      len(ch.merge(ch.load("EURUSD", "1min"), A)) == 3)


print("\n── cTrader paging: the window must move, not stay anchored to now ──")
import types as _types  # noqa: E402

_reqs = []


class _FakeTB:
    def __init__(self, minute, price=100000):
        self.utcTimestampInMinutes = minute
        self.low = price
        self.deltaOpen = 1
        self.deltaHigh = 2
        self.deltaClose = 1
        self.volume = 5


class _FakeCtrader:
    """Records the requested window and serves bars ending at toTimestamp."""

    def get_candles(self, instrument=None, interval=None, limit=None, to_ts=None):
        import time as _time
        end = int(to_ts if to_ts else _time.time())
        _reqs.append(end)
        step = 60
        return [{"time": end - (n + 1) * step, "open": 1.1, "high": 1.2,
                 "low": 1.0, "close": 1.15, "volume": 3}
                for n in reversed(range(limit or 10))]


ch.DATA_DIR = tempfile.mkdtemp(prefix="apex-ct-test-")
_reqs.clear()
r = ch.collect_ctrader("EURUSD", "1min", days=1, broker=_FakeCtrader(),
                       max_calls=5)
check("more than one request was made (it paged)", len(_reqs) > 1, str(len(_reqs)))
check("each request ends strictly earlier than the last",
      all(b < a for a, b in zip(_reqs, _reqs[1:])), str(_reqs))
check("bars accumulate across pages", r["bars"] > 10, str(r["bars"]))
check("the corpus is sorted and deduped",
      [c["time"] for c in ch.load("EURUSD", "1min")]
      == sorted({c["time"] for c in ch.load("EURUSD", "1min")}))
check("rerunning adds nothing new", ch.collect_ctrader(
    "EURUSD", "1min", days=1, broker=_FakeCtrader(), max_calls=5)["bars"]
    >= r["bars"])
check("an unsupported interval is refused, not silently wrong",
      _refuses(lambda: ch.collect_ctrader("EURUSD", "3min", 1,
                                          _FakeCtrader(), 2)))

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed: {', '.join(failures)}")
    sys.exit(1)
print("✅ ALL WALK-FORWARD CHECKS PASSED.")
