"""A test that greps source must assert on CODE, not on the comment beside it.

Forty of this suite's files check behaviour by searching module source for a
string. That is a reasonable technique for properties with no runtime seam —
"this call site is inside that function", "this handler runs nothing" — but it
has a specific failure mode: the string it searches for can live in the
COMMENT that explains the rule. Delete the behaviour, keep the comment, and
the test still passes.

This has happened in this codebase three times:

  * a check for `CtraderBroker` matched the word inside a docstring;
  * a check for `/deploy` in the deny list matched the paragraph above it;
  * `test_final_hardening` claimed to verify "a failed close does NOT release
    the claim" by searching for the literal comment "The claim STANDS".

The last one is the shape that matters. The assertion was about an ABSENCE —
nothing releases the claim — and it was verified by the presence of prose. The
code could have been rewritten to release on failure, with the comment left
in place, and the suite would have stayed green while a retry closed a
position nobody asked to close.

So this file scans every positive source assertion in the suite and fails if
the literal exists ONLY inside comments and docstrings.

Known and deliberate exception: an assertion whose PURPOSE is that a reason is
documented — a bare constant gets raised by whoever finds it annoying, so the
"why" beside it is part of what is being protected. Those are listed below by
name, so adding one is a decision rather than an accident.

Run: python tests/test_prose_assertions.py
"""
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Assertions that deliberately check for documentation rather than code.
ALLOWED_PROSE = {
    # The Auto-Pilot scan cap is a budget on one broker socket. A number with
    # no reason next to it gets raised by the next person who finds twelve
    # symbols limiting; the comment is the guard.
    "single socket",
}

failures = []


def check(name, cond, detail=""):
    print(f"  ✅ {name}" if cond else f"  ❌ {name} {detail}")
    if not cond:
        failures.append(name)


def strip_prose(src):
    """Source with comments and DOCSTRINGS removed — and nothing else.

    Written with Python's own tokenizer and AST rather than regular
    expressions, because the regex version produced three false alarms on this
    very suite and a check that cries wolf gets switched off:

      * the module-level `_SYSTEM` constant in assistant.py is the model's
        system prompt, written as a triple-quoted string. It is not a
        docstring. A regex that strips every triple-quoted block deletes the
        prompt, and then every test asserting the prompt's content looks like
        it is matching prose;
      * the Mini App's fallback page is one long single-quoted string full of
        CSS colours. `re.sub(r"#.*$")` truncates each line at the first `#`,
        which is a colour, destroying the markup that tests legitimately check.

    tokenize knows a COMMENT from a STRING, and ast knows which strings are
    docstrings. Both distinctions are exactly the ones this needs.
    """
    import ast
    import io as _io
    import tokenize

    try:
        tree = ast.parse(src)
    except SyntaxError:
        return src

    # Docstrings: the first statement of a module, class or function when it
    # is a bare string expression.
    doc_spans = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            doc_spans.add((first.lineno, first.col_offset))

    # Blank the comment and docstring SPANS in place. Rebuilding the file by
    # re-joining tokens would lose the original spacing, and then a perfectly
    # good assertion like `"weekend_failed = set()" in SRC` stops matching
    # because the three tokens no longer sit next to each other. (Tried it;
    # it turned five real checks into eighty-seven false alarms.)
    lines = src.splitlines(keepends=True)
    try:
        spans = []
        for tok in tokenize.generate_tokens(_io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT or (
                    tok.type == tokenize.STRING and tok.start in doc_spans):
                spans.append((tok.start, tok.end))
    except (tokenize.TokenError, IndentationError):
        return src

    for (srow, scol), (erow, ecol) in spans:
        for row in range(srow, erow + 1):
            line = lines[row - 1]
            a = scol if row == srow else 0
            b = ecol if row == erow else len(line.rstrip("\n"))
            keep_nl = "\n" if line.endswith("\n") else ""
            body = line.rstrip("\n")
            lines[row - 1] = body[:a] + " " * (b - a) + body[b:] + keep_nl
    return "".join(lines)


MODULES = {}
for pattern in ("apex/**/*.py", "backtest.py", "main.py"):
    for path in glob.glob(os.path.join(ROOT, pattern), recursive=True):
        if "__pycache__" in path or not os.path.isfile(path):
            continue
        src = open(path, encoding="utf-8").read()
        MODULES[os.path.relpath(path, ROOT)] = (src, strip_prose(src))

POSITIVE = re.compile(r'["\']([^"\'\n]{6,150})["\']\s+in\s+([A-Z_][A-Za-z_0-9]*)')
NEGATED = re.compile(r'["\']([^"\'\n]{6,150})["\']\s+not\s+in\s+[A-Z_]')

print("\n🔍 PROSE ASSERTIONS — a test must not pass on a comment\n")

print("1. Every source assertion has code behind it")
suspect = []
scanned = 0
for test in sorted(glob.glob(os.path.join(ROOT, "tests", "test_*.py"))):
    tsrc = open(test, encoding="utf-8").read()
    if 'encoding="utf-8").read()' not in tsrc:
        continue
    src_vars = set(re.findall(r'([A-Z_][A-Za-z_0-9]*)\s*=\s*open\(', tsrc))
    if not src_vars:
        continue
    scanned += 1
    # A `"x" not in SRC` assertion is SATISFIED by absence — never suspect.
    negated = set(NEGATED.findall(tsrc))
    for literal, var in POSITIVE.findall(tsrc):
        if var not in src_vars or literal in negated or literal in ALLOWED_PROSE:
            continue
        hits = [m for m, (raw, _) in MODULES.items() if literal in raw]
        if not hits:
            continue                      # not about this package at all
        if not any(literal in MODULES[m][1] for m in hits):
            suspect.append((os.path.basename(test), literal, hits[0]))

check(f"{scanned} source-asserting test files scanned", scanned >= 30, scanned)
for name, literal, module in suspect:
    check(f"{name}: {literal[:48]!r} exists in code, not only in {module}",
          False,
          "delete the behaviour, keep the comment, and this assertion still "
          "passes")
check("no assertion depends on a comment alone", not suspect,
      f"{len(suspect)} found")

print("\n2. The exception list stays a decision, not a habit")
check("it is short", len(ALLOWED_PROSE) <= 3, ALLOWED_PROSE)
for entry in ALLOWED_PROSE:
    found = any(entry in raw for raw, _ in MODULES.values())
    check(f"{entry!r} still exists somewhere", found,
          "a stale exception hides a real regression")

print("\n3. The specific regression that prompted this")
LSRC = open(os.path.join(ROOT, "apex", "user_loop.py"), encoding="utf-8").read()
check("a failed close still does not release the claim",
      "ledger.release" not in LSRC,
      "asserted on the absent CALL, not on the comment that explains it")

print("\n" + "=" * 50)
if failures:
    print(f"❌ {len(failures)} check(s) failed")
    sys.exit(1)
print("✅ ALL TESTS PASSED — the suite tests code, not comments.")
