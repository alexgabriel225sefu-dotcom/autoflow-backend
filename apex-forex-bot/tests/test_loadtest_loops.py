"""scripts/loadtest_loops.py stays fake: no apex import, no socket, real numbers out.

Run: python3 tests/test_loadtest_loops.py
"""
import argparse
import importlib.util
import io
import os
import socket
import sys
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(name)
        print(f"  FAIL {name} {detail}")


path = os.path.join(ROOT, "scripts", "loadtest_loops.py")
src = open(path, encoding="utf-8").read()
code = src.split('"""', 2)[2]                       # everything after the docstring
check("code never imports apex", "import apex" not in code and "from apex" not in code)
check("code never imports a socket or http client",
      not any(w in code for w in ("import socket", "urllib", "requests", "http.client")))

spec = importlib.util.spec_from_file_location("loadtest_loops", path)
L = importlib.util.module_from_spec(spec)
spec.loader.exec_module(L)

connects = []
_orig = socket.socket.connect
socket.socket.connect = lambda self, *a, **k: connects.append(a)
buf = io.StringIO()
try:
    with redirect_stdout(buf):
        rc = L.main(["--n", "2,4", "--duration", "1.2", "--interval", "0.4",
                     "--net-ms", "1", "--candles", "120", "--symbols", "2"])
finally:
    socket.socket.connect = _orig
out = buf.getvalue()
check("exits 0", rc == 0)
check("made no network connection", not connects, str(connects))
check("no apex module was loaded",
      not any(m == "apex" or m.startswith("apex.") for m in sys.modules))
check("reports a row per level", "   2 " in out and "   4 " in out, out)
check("reports the columns an operator reads",
      all(c in out for c in ("rssMB", "perLoopKB", "threads", "p95ms", "overruns")))

ns = argparse.Namespace(duration=0.8, interval=0.3, symbols=2, candles=100,
                        net_ms=1.0, aligned=True)
r = L.run_level(2, ns, L.rss_kb())
check("ticks happened", r["ticks"] >= 2, str(r))
check("two threads per loop were running (+ main)", r["threads"] >= 5, str(r["threads"]))
check("latency is a positive number", r["p50"] > 0 and r["max"] >= r["p95"] >= r["p50"])
check("rss was read", r["rss_mb"] > 1)
check("percentile of empty is 0", L.percentile([], 0.95) == 0.0)
ind = L.indicators(L.FakeBroker(1, ["A"], 100, 0).buffers["A"])
check("indicators are finite numbers",
      all(isinstance(v, float) and v == v for v in ind.values()), str(ind))

if _fails:
    print(f"FAILED {len(_fails)}: {_fails}")
    sys.exit(1)
print("ALL LOADTEST HARNESS CHECKS PASSED")
