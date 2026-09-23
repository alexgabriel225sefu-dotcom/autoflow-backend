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

# Deliberately NOT audited, each for a stated reason. A file is exempt
# because of what it is, never because it happened to fail.
ALLOWED = {
    # Historical records. These say what a previous session decided, in the
    # language it decided in. Editing one to pass an audit would falsify a
    # record.
    "docs/CODEX_REVIEW_A_B_C.md": "Codex↔Claude handoff, kept verbatim",
    "docs/CHANGE_A_B_C.md": "a record of changes A, B and C as proposed",
    "docs/ARCHITECTURE_V2.md": "describes the architecture it replaced",
    "docs/APEX_ENGINE_AUDIT.md": "an audit of the legacy engine, by name",
    "docs/APEX_ENGINE_REPORT.md": "a report on the legacy engine, by name",
    "docs/UI_AUDIT_V1.md": "records the legacy remnants it found, by quoting them",
    # Documents whose subject IS the previous product or the migration.
    "docs/APEX4TRADERS_PLATFORM_SCOPE.md": "defines the split from the old product",
    "docs/APEX4TRADERS_PROGRESS.md": "a progress log that names what was removed",
    "docs/PLATFORM_V1_PLAN.md": "names the old product as the thing being left",
    "docs/PLATFORM_V1_RELEASE_CHECKLIST.md": "checks off the removal of the old product's surfaces",
    "docs/CTRADER_CAPABILITIES.md": "records what the legacy bot proved possible",
    "docs/PAYMENT_AND_LICENCE_DECISIONS.md": "names the old price and SKU as what must NOT be defaulted to",
    "docs/LAUNCH_QA_REPORT.md": "records the legacy findings it closed",
    "docs/LEGAL_LAUNCH_BLOCKERS.md": "names the old brand's contact address as removed",
    "docs/FOUNDATIONS_IMPLEMENTATION_PLAN.md": "plans the removal, so it names the thing",
    "docs/MANUAL_LICENCE_OPERATIONS.md": "names the legacy Telegram entitlement store",
    "docs/RELEASE_READINESS.md": "records what was removed",
    "docs/BETA_CONFIGURATION.md": "names what the beta is not",
    # Code whose subject is the boundary between the two products.
    "apex-forex-bot/apex/platform/billing.py": "names the old price and SKU as the defaults it refuses to substitute",
    "web/src/app/api/create-payment-intent/route.ts": "documents the old price and SKU as the fallback that was removed",
    "web/src/app/configurator/page.tsx": "records the old copy it replaced",
    "web/src/app/layout.tsx": "records the old title a client read in their browser tab",
    "web/src/app/terms/page.tsx": "records what the previous terms described",
    "web/src/app/content.test.ts": "the test that bans these phrases has to name them",
    "web/src/app/(app)/rules/[id]/page.test.tsx": "asserts absence by naming",
}

BANNED = (
    ("the previous product's name", re.compile(r"Apex\s*Trade\s*Bot", re.I)),
    ("the previous price", re.compile(r"\$\s*297\b|\b29700\b")),
    ("the previous SKU", re.compile(r"apex-bot", re.I)),
    ("another brand's domain", re.compile(r"aicashsystem", re.I)),
    ("a profit promise", re.compile(
        r"\b(guaranteed|guarantee)\b[^.\n]{0,40}\b(profit|return|win)", re.I)),
    ("a claim that live trading is available", re.compile(
        r"live trading is (available|enabled|supported|on)\b", re.I)),
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
AUDITED = [(rel, full) for rel, full in ALL if rel not in ALLOWED]

# ── 1. the allowlist is honest ──────────────────────────────────────────────
print("\n[1] the allowlist is a list of reasons, not a list of failures")
present = {rel for rel, _ in ALL}
stale = sorted(set(ALLOWED) - present)
check("every allowlisted file still exists", not stale,
      f"stale exemptions: {stale}")
check("every exemption has a reason written down",
      all(len(v) > 10 for v in ALLOWED.values()))
check("the audit still covers most of the surface",
      len(AUDITED) > len(ALLOWED) * 3, f"{len(AUDITED)} audited, {len(ALLOWED)} exempt")
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
    hits = sorted(r for r, b in bodies.items() if pattern.search(b))
    check(f"no {label}", not hits, f"found in {hits}")

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
      f"{len(ALLOWED)} exempt with reasons).")
