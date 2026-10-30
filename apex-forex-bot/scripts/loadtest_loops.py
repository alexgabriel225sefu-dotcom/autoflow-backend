"""Capacity harness: N fake per-user loops against a FAKE broker. No network.

    python3 scripts/loadtest_loops.py                      # 5,10,20,40 loops
    python3 scripts/loadtest_loops.py --n 10,20,30 --duration 60
    python3 scripts/loadtest_loops.py --n 20 --aligned     # worst case: all tick together

WHAT IT MODELS (and what it does not)

Production runs one daemon thread per client loop plus one lease-renewer thread
(`user_loop.start`, `ownership.start_renewer`), each loop holding a blocking
socket to cTrader and ticking every 300 s. This harness reproduces that SHAPE in
one process: two threads per fake user, a fake broker that returns synthetic
candles (no socket, no sleep beyond a configurable stand-in for broker latency),
and pure-Python indicator arithmetic on those candles each tick. The interval is
compressed (default 5 s instead of 300 s) so a short run exercises many ticks.

It does NOT import apex, user_loop or any broker module, and never opens a
socket. It therefore measures the cost of the threading and the arithmetic
model, not the real engine. Use it to find the shape of the curve (where the
tick latency starts to climb, how RSS grows per loop) and to compare machines;
calibrate against the real service by comparing the harness's baseline RSS and
per-loop growth with the real process's, as docs/PRODUCTION_RUNBOOK.md
describes. Treat any absolute number as a floor, not a promise.

OUTPUT, one row per N
    rssMB       process resident set after the run (VmRSS; peak in parentheses)
    perLoopKB   (rss at N - rss with 0 loops) / N
    threads     threading.active_count() at peak
    p50/p95/max tick latency in ms (work time of one tick, not the sleep)
    overruns    ticks that took longer than the interval (a loop falling behind)
"""
import argparse
import math
import os
import random
import sys
import threading
import time


def rss_kb():
    """Resident set in KB, current. Linux /proc, else peak from resource."""
    try:
        with open("/proc/self/status", encoding="ascii") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
    except OSError:
        pass
    try:
        import resource
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(peak / 1024) if sys.platform == "darwin" else int(peak)
    except Exception:                                        # noqa: BLE001
        return 0


def peak_rss_kb():
    try:
        with open("/proc/self/status", encoding="ascii") as f:
            for line in f:
                if line.startswith("VmHWM:"):
                    return int(line.split()[1])
    except OSError:
        pass
    return rss_kb()


class FakeBroker:
    """Stands in for a broker connection. Holds a candle buffer, as a loop does."""

    def __init__(self, seed, symbols, candles, net_ms):
        self._rng = random.Random(seed)
        self._net = net_ms / 1000.0
        self._price = {s: 1.0 + self._rng.random() for s in symbols}
        self.symbols = list(symbols)
        self.buffers = {s: self._make(s, candles) for s in symbols}

    def _make(self, sym, n):
        p, out = self._price[sym], []
        for _ in range(n):
            p *= 1.0 + self._rng.uniform(-0.001, 0.001)
            out.append({"o": p, "h": p * 1.0005, "l": p * 0.9995, "c": p, "v": 100})
        self._price[sym] = p
        return out

    def get_candles(self, sym):
        if self._net:
            time.sleep(self._net)             # stand-in for broker latency
        buf = self.buffers[sym]
        buf.extend(self._make(sym, 1))        # a new bar arrives
        del buf[0]
        return buf


def indicators(candles):
    """RSI(14), EMA(20/50), ATR(14) in pure Python: the shape of a tick's CPU."""
    closes = [c["c"] for c in candles]
    gains = losses = 0.0
    for a, b in zip(closes[-15:-1], closes[-14:]):
        d = b - a
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    rsi = 100.0 if losses == 0 else 100.0 - 100.0 / (1.0 + gains / losses)
    out = {"rsi": rsi}
    for period in (20, 50):
        k = 2.0 / (period + 1)
        ema = closes[0]
        for c in closes:
            ema = c * k + ema * (1 - k)
        out[f"ema{period}"] = ema
    trs = [max(c["h"] - c["l"], abs(c["h"] - p["c"]), abs(c["l"] - p["c"]))
           for p, c in zip(candles[-15:-1], candles[-14:])]
    out["atr"] = sum(trs) / len(trs)
    out["vol"] = math.sqrt(sum((c - out["ema20"]) ** 2 for c in closes[-50:]) / 50)
    return out


class Loop:
    def __init__(self, idx, args, stop, results, lock):
        self.idx, self.args, self.stop = idx, args, stop
        self.results, self.lock = results, lock
        symbols = [f"SYM{idx % 7}_{j}" for j in range(args.symbols)]
        self.broker = FakeBroker(idx, symbols, args.candles, args.net_ms)

    def tick(self):
        t0 = time.perf_counter()
        for sym in self.broker.symbols:
            indicators(self.broker.get_candles(sym))
        return (time.perf_counter() - t0) * 1000.0

    def run(self):
        a = self.args
        if not a.aligned:                     # a deploy staggers real loops
            self.stop.wait(random.Random(self.idx).random() * a.interval)
        while not self.stop.is_set():
            ms = self.tick()
            with self.lock:
                self.results.append(ms)
            if self.stop.wait(a.interval):
                break

    def renewer(self):
        # The lease renewer: a thread that wakes occasionally and does nothing.
        while not self.stop.wait(max(1.0, self.args.interval / 2)):
            pass


def percentile(sorted_vals, q):
    if not sorted_vals:
        return 0.0
    i = min(len(sorted_vals) - 1, int(round(q * (len(sorted_vals) - 1))))
    return sorted_vals[i]


def run_level(n, args, base_kb):
    stop, lock, results = threading.Event(), threading.Lock(), []
    threads = []
    for i in range(n):
        lp = Loop(i, args, stop, results, lock)
        threads.append(threading.Thread(target=lp.run, daemon=True))
        threads.append(threading.Thread(target=lp.renewer, daemon=True))
    for t in threads:
        t.start()
    time.sleep(0.2)
    peak_threads = threading.active_count()
    time.sleep(args.duration)
    rss_now = rss_kb()
    stop.set()
    for t in threads:
        t.join(timeout=2)
    with lock:
        lat = sorted(results)
    over = sum(1 for v in lat if v > args.interval * 1000.0)
    return {
        "n": n, "rss_mb": rss_now / 1024.0, "peak_mb": peak_rss_kb() / 1024.0,
        "per_loop_kb": (rss_now - base_kb) / n if n else 0.0,
        "threads": peak_threads, "ticks": len(lat),
        "p50": percentile(lat, 0.50), "p95": percentile(lat, 0.95),
        "max": lat[-1] if lat else 0.0, "overruns": over,
    }


def render(rows):
    head = (f"{'N':>4} {'rssMB':>8} {'peakMB':>8} {'perLoopKB':>10} {'threads':>8} "
            f"{'ticks':>6} {'p50ms':>8} {'p95ms':>8} {'maxms':>8} {'overruns':>8}")
    lines = [head, "-" * len(head)]
    for r in rows:
        lines.append(f"{r['n']:>4} {r['rss_mb']:>8.1f} {r['peak_mb']:>8.1f} "
                     f"{r['per_loop_kb']:>10.0f} {r['threads']:>8} {r['ticks']:>6} "
                     f"{r['p50']:>8.1f} {r['p95']:>8.1f} {r['max']:>8.1f} "
                     f"{r['overruns']:>8}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--n", default="5,10,20,40", help="comma-separated loop counts")
    ap.add_argument("--duration", type=float, default=30.0, help="seconds per level")
    ap.add_argument("--interval", type=float, default=5.0,
                    help="seconds between ticks (production: 300)")
    ap.add_argument("--symbols", type=int, default=3, help="symbols scanned per tick")
    ap.add_argument("--candles", type=int, default=500, help="candles held per symbol")
    ap.add_argument("--net-ms", type=float, default=150.0,
                    help="stand-in broker latency per candle fetch")
    ap.add_argument("--aligned", action="store_true",
                    help="start every loop's tick at once (worst case)")
    args = ap.parse_args(argv)
    levels = [int(x) for x in args.n.split(",") if x.strip()]
    base = rss_kb()
    print(f"fake broker, no network. baseline rss {base / 1024.0:.1f} MB, "
          f"interval {args.interval}s, {args.symbols} symbols x {args.candles} candles, "
          f"{'aligned' if args.aligned else 'staggered'}")
    rows = []
    for n in levels:
        rows.append(run_level(n, args, base))
        print(render(rows[-1:]) if len(rows) == 1 else render(rows[-1:]).split("\n")[-1])
        sys.stdout.flush()
    print("\n" + render(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
