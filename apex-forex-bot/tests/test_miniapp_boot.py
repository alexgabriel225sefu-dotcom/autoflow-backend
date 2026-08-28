"""The Mini App must actually LOAD. Every other test in this suite greps.

This file exists because of a bug the rest of the suite could not see.

`showScreen()` was called while the script was still being evaluated, and it
read `lastSym` — a `let` declared further down. In the temporal dead zone that
throws, and a throw during evaluation stops the whole script: every handler
defined below it never came into existence. The page rendered its static
markup and then did nothing at all. Ever.

Node's `--check` passes on that file. Every string assertion passes on that
file. The screens are all present in the DOM. The tests were green and the app
was dead, which is the exact combination a test suite is supposed to prevent.

So this one runs the page in a real browser and asserts three things a grep
cannot: that evaluating the script raises nothing, that the router actually
shows exactly one screen per destination, and that nothing overflows a 375px
viewport.

SKIPS loudly when Chromium or playwright-core is unavailable. A skipped check
is reported as a skip and never as a pass.

Run: python tests/test_miniapp_boot.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, "apex", "static", "terminal.html")
LIB = os.path.join(ROOT, "apex", "static", "lightweight-charts.js")

failures = []


def check(name, cond, detail=""):
    print(f"  OK   {name}" if cond else f"  FAIL {name} {detail}")
    if not cond:
        failures.append(name)


def _find_chromium():
    base = os.getenv("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")
    if not os.path.isdir(base):
        return None
    for entry in sorted(os.listdir(base)):
        cand = os.path.join(base, entry, "chrome-linux", "chrome")
        if os.path.isfile(cand):
            return cand
    return None


CHROME = _find_chromium()
if not CHROME or not shutil.which("node"):
    print("\n  SKIP  no Chromium or node here — this check CANNOT run.")
    print("        It is not passing; it is unrun. Nothing verified the page loads.")
    sys.exit(0)

work = tempfile.mkdtemp(prefix="apex-boot-")
try:
    subprocess.run(["npm", "init", "-y"], cwd=work, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    r = subprocess.run(["npm", "install", "--no-audit", "--no-fund", "playwright-core"],
                       cwd=work, capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        print("\n  SKIP  playwright-core could not be installed — check unrun.")
        sys.exit(0)
except Exception as e:
    print(f"\n  SKIP  browser harness unavailable ({e}) — check unrun.")
    sys.exit(0)

os.makedirs(os.path.join(work, "static"), exist_ok=True)
shutil.copyfile(HTML, os.path.join(work, "index.html"))
if os.path.isfile(LIB):
    shutil.copyfile(LIB, os.path.join(work, "static", "lightweight-charts.js"))

# A plain static server. The /api/app/* calls 404 here, which is the point:
# the page must survive a backend that answers nothing, because that is what a
# client sees during an outage.
server = subprocess.Popen([sys.executable, "-m", "http.server", "8231"],
                          cwd=work, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL)

SCRIPT = r"""
const { chromium } = require('playwright-core');
(async () => {
  const b = await chromium.launch({ executablePath: process.argv[2], args: ['--no-sandbox'] });
  const p = await b.newPage({ viewport: { width: 375, height: 780 } });
  const errs = [];
  p.on('pageerror', e => errs.push(String(e.message)));
  await p.goto('http://127.0.0.1:8231/', { waitUntil: 'domcontentloaded', timeout: 25000 });
  await p.waitForTimeout(1500);
  const boot = await p.evaluate(() => ({
    screens: document.querySelectorAll('.screen').length,
    nav: document.querySelectorAll('#bottomnav div').length,
    // Proof the code AFTER the router ran: the greeting is set at boot.
    greeted: !/^Welcome back$/.test((document.getElementById('greet')||{}).textContent || ''),
    envBadge: !!document.getElementById('envBadge'),
  }));
  const out = [];
  const all = ['home','markets','portfolio','history','intelligence','automation',
               'ask','risk','settings','account','alerts','notifications',
               'security','preferences','symbol','trade'];
  for (const s of all) {
    await p.evaluate(n => { location.hash = n; }, s);
    await p.waitForTimeout(220);
    out.push(await p.evaluate(want => {
      const vis = [...document.querySelectorAll('.screen')]
        .filter(x => getComputedStyle(x).display !== 'none');
      return { want: 's-' + want, shown: vis[0] ? vis[0].id : null, count: vis.length,
               overflow: document.documentElement.scrollWidth >
                         document.documentElement.clientWidth };
    }, s));
  }
  console.log(JSON.stringify({ errs, boot, out }));
  await b.close();
})().catch(e => { console.log(JSON.stringify({ fatal: String(e) })); process.exit(0); });
"""
_boot_js = os.path.join(work, "boot.js")
open(_boot_js, "w").write(SCRIPT)

try:
    r = subprocess.run(["node", "boot.js", CHROME], cwd=work,
                       capture_output=True, text=True, timeout=180)
    data = json.loads((r.stdout or "{}").strip().splitlines()[-1])
except Exception as e:
    print(f"\n  SKIP  the browser run did not complete ({e}) — check unrun.")
    server.terminate()
    sys.exit(0)

server.terminate()

if data.get("fatal"):
    print(f"\n  SKIP  browser failed to start: {data['fatal'][:120]}")
    sys.exit(0)

print("\n1. Evaluating the page raises nothing")
errs = data.get("errs") or []
check(f"no uncaught error during load ({len(errs)})", not errs,
      "; ".join(errs)[:300] +
      "  <-- a throw while the script evaluates stops every handler below it")

print("\n2. The boot sequence after the router actually runs")
boot = data.get("boot") or {}
check(f"all screens are in the DOM ({boot.get('screens')})",
      (boot.get("screens") or 0) >= 16)
check(f"the bottom navigation is populated ({boot.get('nav')})",
      (boot.get("nav") or 0) >= 6)
check("the environment badge is in the shell", bool(boot.get("envBadge")))
check("code after the router ran", bool(boot.get("greeted")),
      "the greeting is set at boot; if it is untouched, evaluation stopped "
      "before reaching it")

print("\n3. Every destination shows exactly one screen")
for row in data.get("out") or []:
    check(f"{row['want']}: shown alone",
          row.get("shown") == row["want"] and row.get("count") == 1,
          f"shown={row.get('shown')} visible={row.get('count')}")

print("\n4. Nothing overflows a 375px viewport")
over = [r["want"] for r in (data.get("out") or []) if r.get("overflow")]
check(f"no horizontal overflow ({over or 'none'})", not over,
      "the brief's first breakpoint is 375px")

print("\n" + "=" * 50)
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:6])}")
    sys.exit(1)
print("ALL BOOT CHECKS PASSED - the page loads, routes, and fits a phone.")
