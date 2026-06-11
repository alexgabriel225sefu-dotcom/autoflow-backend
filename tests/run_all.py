"""Run every test file in one shot (CI-friendly).

Run: python tests/run_all.py
"""
import glob
import os
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
files = sorted(f for f in glob.glob(os.path.join(here, "test_*.py")))
failed = []
for f in files:
    name = os.path.basename(f)
    r = subprocess.run([sys.executable, f], capture_output=True, text=True)
    ok = r.returncode == 0
    print(f"{'✅ PASS' if ok else '❌ FAIL'}  {name}")
    if not ok:
        failed.append(name)
        print(r.stdout[-1500:])
        print(r.stderr[-500:])

print("\n" + "=" * 50)
if failed:
    print(f"❌ {len(failed)}/{len(files)} test file(s) failed: {', '.join(failed)}")
    sys.exit(1)
print(f"✅ ALL {len(files)} TEST FILES PASSED.")
