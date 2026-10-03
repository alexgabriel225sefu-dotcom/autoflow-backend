"""What the Apex4Traders surfaces say, and what they must never say.

TWO PRODUCTS, ONE REPOSITORY

This repository holds Apex Trade Bot — the Telegram forex bot, which still
runs and is legitimately called that — and Apex4Traders, the web platform.
A repository-wide ban on the old name would be false: it is the other
product's actual name. So this audit is scoped to the Apex4Traders surfaces,
and everything outside them is listed explicitly rather than skipped by
accident.

The allowlist is the interesting part. A historical handoff document that
records what a previous session decided is evidence, and rewriting it to pass
an audit would be falsifying a record to make a test green. Those are named
here with the reason, and the test asserts the list itself stays honest — an
allowlisted file that no longer exists is a stale exemption, and a stale
exemption is how an audit stops auditing.

Run: python3 tests/test_product_copy.py
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(ROOT)

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL {name} {detail}")


# The surfaces this product speaks through: the web client, the platform
# backend, and the documents written for it.
SURFACES = (
    os.path.join(REPO, "web", "src"),
    os.path.join(ROOT, "apex", "platform"),
    os.path.join(ROOT, "scripts", "smoke_ctrader_demo.py"),
    os.path.join(REPO, "docs"),
)

# Deliberately NOT audited — but only for the SPECIFIC rule each file needs.
#
# WHY THIS IS PER-RULE AND NOT PER-FILE
#
# It used to be per-file: an entry here exempted a file from every ban. That
# was a hole as wide as the list. `web/src/app/terms/page.tsx` was exempt
# because it "records what the previous terms described" — and so the page most
# likely to carry a support address was exempt from the rule forbidding the old
# brand's support address. A mutation putting that address back into /terms
# survived the audit.
#
# Recomputing what each file ACTUALLY trips found that 14 of the 25 entries
# needed no exemption at all. They had a plausible reason and no cause. Those
# are gone; what is left grants exactly the rule the file needs, and the test
# below fails if an exemption is ever wider than its cause.
ALLOWED = {
    "apex-forex-bot/apex/platform/billing.py": (
        "names the old price and SKU as the defaults it refuses to substitute",
        frozenset({"the previous price", "the previous SKU"})),
    "web/src/app/api/create-payment-intent/route.ts": (
        "documents the old price and SKU as the fallback that was removed",
        frozenset({"the previous price", "the previous SKU"})),
    "docs/PAYMENT_AND_LICENCE_DECISIONS.md": (
        "names the old price and SKU as what must NOT be defaulted to",
        frozenset({"the previous price", "the previous SKU"})),
    "web/src/app/configurator/page.tsx": (
        "records the old copy it replaced",
        frozenset({"the previous product's name"})),
    "web/src/app/layout.tsx": (
        "records the old title a client read in their browser tab",
        frozenset({"the previous product's name"})),
    "web/src/app/content.test.ts": (
        "the test that bans these phrases has to name them",
        frozenset({"the previous product's name", "the previous SKU",
                   "a profit promise",
                   "the other brand named in the product"})),
    "docs/LEGAL_LAUNCH_BLOCKERS.md": (
        "records the old brand's contact address as the thing that was removed",
        frozenset({"the previous product's name",
                   "another brand's domain or contact address"})),
    "docs/UI_AUDIT_V1.md": (
        "records the legacy remnants it found, by quoting them",
        frozenset({"the previous product's name", "the previous price",
                   "the previous SKU",
                   "another brand's domain or contact address"})),
    "docs/FOUNDATIONS_IMPLEMENTATION_PLAN.md": (
        "plans the removal, so it names every thing being removed",
        frozenset({"the previous product's name", "the previous price",
                   "the previous SKU",
                   "another brand's domain or contact address"})),
}

BANNED = (
    ("the previous product's name", re.compile(r"Apex\s*Trade\s*Bot", re.I)),
    ("the previous price", re.compile(r"\$\s*297\b|\b29700\b")),
    ("the previous SKU", re.compile(r"apex-bot", re.I)),
    ("another brand's domain or contact address",
     re.compile(r"aicashsystem\s*\.\s*\w|@\s*aicashsystem|https?://\S*aicashsystem",
                re.I)),
    ("a profit promise", re.compile(
        r"\b(guaranteed|guarantee)\b[^.\n]{0,40}\b(profit|return|win)", re.I)),
    ("a claim that live trading is available", re.compile(
        r"live trading is (available|enabled|supported|on)\b", re.I)),
)

# Banned on the PRODUCT surfaces only — code a client runs and copy a client
# reads. An infrastructure document has to be able to name a hosting service
# that exists; rewording it to pass an audit would make it useless to the
# operator reading the same name in their dashboard.
PRODUCT_SURFACES = ("web/src/", "apex-forex-bot/apex/platform/")
BARE_BRAND = "the other brand named in the product"
SURFACE_ONLY = (
    (BARE_BRAND, re.compile(r"aicashsystem", re.I)),
)


def files():
    for surface in SURFACES:
        if os.path.isfile(surface):
            yield os.path.relpath(surface, REPO), surface
            continue
        for dirpath, dirnames, names in os.walk(surface):
            dirnames[:] = [d for d in dirnames
                           if d not in ("node_modules", "__pycache__", ".next")]
            for n in names:
                if not n.endswith((".ts", ".tsx", ".py", ".md", ".css")):
                    continue
                full = os.path.join(dirpath, n)
                yield os.path.relpath(full, REPO).replace(os.sep, "/"), full


ALL = list(files())


def _exempt(rel):
    """The labels this file is allowed to trip, and only those."""
    entry = ALLOWED.get(rel)
    return entry[1] if entry else frozenset()


# Every file is audited. What changes per file is WHICH rules apply to it, so
# a file can never fall out of the audit entirely.
AUDITED = ALL

# ── 1. the allowlist is honest ──────────────────────────────────────────────
print("\n[1] every exemption is exactly as wide as its cause")
present = {rel for rel, _ in ALL}
stale = sorted(set(ALLOWED) - present)
check("every allowlisted file still exists", not stale,
      f"stale exemptions: {stale}")
check("every exemption has a reason written down",
      all(len(reason) > 10 for reason, _ in ALLOWED.values()))
check("every exemption names at least one rule",
      all(labels for _, labels in ALLOWED.values()),
      "a blanket exemption is a hole, not an exemption")
_labels = {label for label, _ in BANNED} | {label for label, _ in SURFACE_ONLY}
check("no exemption names a rule that does not exist",
      all(labels <= _labels for _, labels in ALLOWED.values()),
      str({r: sorted(l - _labels) for r, (_, l) in ALLOWED.items() if l - _labels}))
check("no file is audited by exclusion — every file is audited",
      len(AUDITED) == len(ALL))
check("it covers the web client", any(r.startswith("web/src/") for r, _ in AUDITED))
check("it covers the platform backend",
      any(r.startswith("apex-forex-bot/apex/platform/") for r, _ in AUDITED))
check("it covers the documents", any(r.startswith("docs/") for r, _ in AUDITED))

# ── 2. nothing banned survives outside the allowlist ────────────────────────
print("\n[2] no legacy identity, price, SKU or promise on an audited surface")
bodies = {}
for rel, full in AUDITED:
    with open(full, encoding="utf-8", errors="replace") as fh:
        bodies[rel] = fh.read()

for label, pattern in BANNED:
    hits = sorted(r for r, b in bodies.items()
                  if pattern.search(b) and label not in _exempt(r))
    check(f"no {label}", not hits, f"found in {hits}")

# ── 2a. an exemption that is not needed is a hole ───────────────────────────
# This is the check that would have caught the old per-file allowlist: an
# entry granting a rule the file never trips is an exemption waiting to be
# used by something that does trip it.
print("\n[2a] no exemption is wider than what the file actually trips")
for rel, (reason, labels) in sorted(ALLOWED.items()):
    body = bodies.get(rel)
    if body is None:
        continue
    _all_rules = dict(BANNED) | dict(SURFACE_ONLY)
    unnecessary = sorted(
        label for label in labels
        if not _all_rules[label].search(body))
    check(f"{rel} needs every rule it is exempt from", not unnecessary,
          f"exempt from {unnecessary} without tripping it")

# ── 2b. the other brand is not NAMED on a product surface ───────────────────
# Infrastructure documents may name a service. Code a client runs, and copy a
# client reads, may not name the brand at all.
print("\n[2b] the other brand is not named in code or client-facing copy")
hits = sorted(r for r, b in bodies.items()
              if r.startswith(PRODUCT_SURFACES)
              and dict(SURFACE_ONLY)[BARE_BRAND].search(b)
              and BARE_BRAND not in _exempt(r))
check("no mention of the other brand in the product itself", not hits,
      f"found in {hits}")
# And prove the domain form is still caught everywhere, so tightening the rule
# above did not quietly switch the protection off.
_domain_rule = dict(BANNED)["another brand's domain or contact address"]
for form in ("aicashsystem.space", "support@aicashsystem.space",
             "https://aicashsystem.space/contact", "AiCashSystem.Space"):
    check(f"{form!r} is still refused", bool(_domain_rule.search(form)), form)
check("but a bare service name is allowed in an infrastructure document",
      not _domain_rule.search("the aicashsystem service is suspended"))

# ── 3. no public page claims live trading ───────────────────────────────────
# The pages a visitor reads without signing in. Each must state the limit,
# not merely avoid contradicting it: silence reads as "yes" to somebody
# deciding whether to trust this with money.
print("\n[3] every public page states that live trading is off")
PUBLIC = ("web/src/app/page.tsx", "web/src/app/terms/page.tsx",
          "web/src/app/configurator/page.tsx")
LIMIT = re.compile(r"live (trading|execution) is not (available|enabled)", re.I)
for rel in PUBLIC:
    full = os.path.join(REPO, rel)
    check(f"{rel} exists", os.path.exists(full))
    body = open(full, encoding="utf-8").read()
    check(f"{rel} says live trading is not available", bool(LIMIT.search(body)),
          "silence reads as yes")

# ── 4. the sentence about paid access is one sentence ───────────────────────
# It exists twice — Python for signed-in clients, TypeScript for pages with
# no session to ask. Two copies is one more than ideal, so they are pinned.
print("\n[4] the plan notice says the same thing in both languages")
py = open(os.path.join(ROOT, "apex", "platform", "entitlement.py"),
          encoding="utf-8").read()
ts = open(os.path.join(REPO, "web", "src", "lib", "api.ts"), encoding="utf-8").read()


def joined(text):
    """Source with string concatenation flattened.

    Both languages wrap the sentence across lines — Python by adjacency,
    TypeScript with `+`. Comparing raw source would compare formatting, and a
    reflow would fail a test about wording.
    """
    out = re.sub(r'"\s*\+?\s*"', "", text)      # "a" "b" and "a" + "b"
    return re.sub(r"\s+", " ", out)


SENTENCE = ("Demo accounts are free. Real-money account access will be a paid "
            "plan, and live execution is not enabled in this release.")
check("the backend's notice is that sentence", SENTENCE in joined(py),
      "python copy drifted")
check("the client's notice is that sentence too", SENTENCE in joined(ts),
      "typescript copy drifted")
check("and it promises no price",
      not re.search(r"[$€£]\s*\d|\b\d+\s*(usd|eur|gbp)\b", SENTENCE, re.I))
check("and no date", not re.search(r"\b(soon|shortly|Q[1-4]|20\d\d)\b", SENTENCE, re.I))
check("and no outcome", not re.search(r"\b(profit|return|win|earn)\b", SENTENCE, re.I))

# ── 5. checkout says it is disabled, whatever else is missing ───────────────
print("\n[5] the checkout route answers about the product, not the deployment")
route = open(os.path.join(REPO, "web", "src", "app", "api",
                          "create-payment-intent", "route.ts"),
             encoding="utf-8").read()
i_flag = route.index("A4T_CHECKOUT_ENABLED")
i_key = route.index("process.env.STRIPE_SECRET_KEY")
check("the disabled check runs BEFORE any configuration check", i_flag < i_key,
      "otherwise a caller asking to buy is told a Stripe key is missing")
check("and the answer says demo accounts are free",
      "Demo accounts are free" in route)
check("and that paying is not how an entitlement is granted",
      "verified payment webhook" in route)
check("the route still cannot grant anything",
      "licence.grant" not in route and "grant(" not in route)

print()
if _fails:
    print(f"FAILED ({len(_fails)}):")
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print(f"All product-copy checks passed ({len(AUDITED)} files audited, "
      f"{len(ALLOWED)} carrying a per-rule exemption).")
