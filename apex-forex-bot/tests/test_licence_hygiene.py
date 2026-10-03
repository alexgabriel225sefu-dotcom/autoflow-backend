"""A licence key is a credential: it must be strong, and it must not be logged.

Two findings from the second audit, pinned together because they are the same
mistake seen from two sides — treating an entitlement credential as if it were
an identifier.

ENTROPY. generate_license_key() produced three four-character groups over a
32-symbol alphabet: 12 x 5 = 60 BITS. That is what a buyer presents to claim
the product, and 60 bits is not enough for a bearer credential.

LOGGING. The activation path printed the complete key. Render's log stream, any
aggregator in front of it, a support export or a screenshot then carries a
working credential. A log store is not a credential store.

Run: python tests/test_licence_hygiene.py
"""
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
os.environ.setdefault("PAPER_TRADING", "true")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apex-lichyg-")

from apex import stripe_license as sl, telegram as tg, config as cfg  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"  OK   {name}" if cond else f"  FAIL {name} {detail}")
    if not cond:
        failures.append(name)


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALPHABET = 32
BITS_PER_CHAR = 5          # log2(32)

print("\nLICENCE HYGIENE - strong enough to be a credential, never logged as one\n")

print("1. Entropy")
key = sl.generate_license_key()
body = key.split("-", 1)[1].replace("-", "")
bits = len(body) * BITS_PER_CHAR
check(f"a new key carries {bits} bits (was 60)", bits >= 128, f"only {bits}")
check("the prefix is the configured one", key.startswith(cfg.LICENSE_KEY_PREFIX + "-"))
check("it passes the shape validator", tg.licence_shape_ok(key))

print("\n2. The randomness comes from the CSPRNG, not from time or a counter")
src = open(os.path.join(ROOT, "apex", "stripe_license.py"), encoding="utf-8").read()
gen_full = src[src.index("def generate_license_key"):src.index("def _verify_signature")]
# The function's own docstring explains which sources are NOT used, so scanning
# raw text finds the words in the explanation. Strip docstrings and comments
# first — otherwise this check asserts on its own documentation.
gen = re.sub(r'("""|\'\'\')(?:.|\n)*?\1', '""', gen_full)
gen = re.sub(r"#.*$", "", gen, flags=re.M)
check("uses secrets.choice", "secrets.choice" in gen, gen[:200])
for banned in ("random.random", "random.choice", "time.time", "uuid1",
               "datetime", "md5", "chat_id", "email"):
    check(f"does not use {banned}", banned not in gen, gen[:200])

# Behavioural, not just textual: two keys minted back to back must not share a
# prefix. A timestamp- or counter-derived key does; a CSPRNG one does not.
a = sl.generate_license_key().split("-", 1)[1].replace("-", "")
b = sl.generate_license_key().split("-", 1)[1].replace("-", "")
shared = 0
while shared < len(a) and a[shared] == b[shared]:
    shared += 1
check("consecutive keys share no meaningful prefix", shared < 6, f"shared {shared}")

print("\n3. Uniqueness and distribution over a real sample")
sample = [sl.generate_license_key() for _ in range(20000)]
check("20,000 keys, zero collisions", len(set(sample)) == 20000,
      f"{20000 - len(set(sample))} collisions")
symbols = {c for k in sample[:3000] for c in k.split("-", 1)[1].replace("-", "")}
check(f"the whole {ALPHABET}-symbol alphabet is used", len(symbols) == ALPHABET,
      f"only {len(symbols)}")
check("no I or O (they read as 1 and 0)", not (symbols & set("IO")), str(symbols & set("IO")))
# 256 % 32 == 0, so no symbol should be favoured.
from collections import Counter  # noqa: E402
counts = Counter(c for k in sample for c in k.split("-", 1)[1].replace("-", ""))
expected = sum(counts.values()) / ALPHABET
worst = max(abs(n - expected) / expected for n in counts.values())
check(f"distribution is uniform (worst drift {worst * 100:.1f}%)", worst < 0.08)

print("\n4. Existing customers are not locked out")
check("a legacy 12-character key still passes the shape check",
      tg.licence_shape_ok("FORX-ABCD-EFGH-JKLM"))
check("legacy keys containing I and O are still accepted",
      tg.licence_shape_ok("FORX-IIII-OOOO-ABCD"),
      "the old generator could emit them; refusing now locks out real buyers")
check("lowercase is normalised, not refused",
      tg.licence_shape_ok(sl.generate_license_key().lower()))

print("\n5. Malformed keys are refused")
for bad in ("", "   ", "FORX", "FORX-", "nope", "FORX-AAAA", "FORX-AAAA-BBBB",
            "FORX-AAAAA-BBBBB", "FORX-" + "A" * 200, "FORX-AAA!-BBBB-CCCC",
            "XXXX-AAAA-BBBB-CCCC", "FORX-AAAA-BBBB-CCCC-DDDD", None, 12345):
    check(f"{str(bad)[:28]!r:32} refused", not tg.licence_shape_ok(bad))

print("\n6. The mask keeps enough to correlate and too little to use")
k = sl.generate_license_key()
m = tg.mask_licence(k)
parts = k.split("-")
check("the prefix survives", m.startswith(parts[0] + "-"), m)
check("the first group survives", parts[1] in m, m)
for g in parts[2:]:
    check(f"group {g} is gone", g not in m, m)
check("the mask is not the key", m != k, m)
check("empty input is safe", tg.mask_licence("") == "(none)")
check("None is safe", tg.mask_licence(None) == "(none)")

print("\n7. No Python source logs a complete licence key")
# Behavioural: run the masking path over a known canary and prove the whole
# value cannot appear. Textual: no print() interpolates a bare key variable.
CANARY = sl.generate_license_key()
check("the canary never survives masking", CANARY not in tg.mask_licence(CANARY))

def _blank_docstrings_and_comments(text):
    """Remove docstring/comment CONTENT but keep the line count intact.

    The first version of this replaced whole docstrings with "", which shifted
    every later line number and made the reported locations point at unrelated
    code. Blanking in place keeps `file:line` meaningful.
    """
    def _blank(m):
        return m.group(0)[:3] + "\n" * m.group(0).count("\n") + m.group(0)[:3]
    text = re.sub(r'("""|\'\'\')(?:.|\n)*?\1', _blank, text)
    return re.sub(r"#.*$", "", text, flags=re.M)


# `key` alone is far too broad — Redis keys, dict keys and strategy keys are all
# called that and none of them is a credential. The scan therefore looks for a
# licence-shaped variable, OR a bare `key` on a line that also mentions a
# licence. Every hit is inspected rather than pattern-deleted.
_LICENCE_VAR = r"\{\s*(license_key|licence_key|licenseKey|licenceKey)\s*[}:!]"
_BARE_KEY = r"\{\s*key\s*[}:!]"

offenders = []
for dirpath, _dirs, files in os.walk(os.path.join(ROOT, "apex")):
    for fn in sorted(files):
        if not fn.endswith(".py"):
            continue
        text = _blank_docstrings_and_comments(
            open(os.path.join(dirpath, fn), encoding="utf-8").read())
        for i, line in enumerate(text.split("\n"), 1):
            if not re.search(r"\b(print|logger\.\w+)\(", line):
                continue
            hit = re.search(_LICENCE_VAR, line) or (
                re.search(_BARE_KEY, line) and re.search(r"(?i)licen[cs]e", line))
            if hit:
                offenders.append(f"{fn}:{i}: {line.strip()[:90]}")
check("no print/logger interpolates a bare licence key",
      not offenders, "offenders: " + "; ".join(offenders))

print("\n8. The Stripe activation line is masked")
check("it calls mask_licence", "mask_licence(key)" in src,
      "the activation log still carries the raw key")
check("and does not interpolate the raw key",
      "with license {key}" not in src)

print("\n" + "=" * 50)
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:8])}")
    sys.exit(1)
print("ALL LICENCE-HYGIENE CHECKS PASSED.")
