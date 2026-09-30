"""Adding a broker provider cannot add a way to trade.

WHY THIS FILE EXISTS

`test_platform_live_invariants.py` proves live execution is unreachable in the
platform as it stands. This one is about what happens when the platform grows
a SECOND broker — the moment when "live trading is off" usually stops being
true, because the new integration is written by somebody reading the new
vendor's docs rather than this codebase's locks.

So the questions here are deliberately about the shape of a provider, not
about MT5: can a provider acquire execution by declaring it? by implementing
it? by being enabled? Can the platform tell a client a broker is supported
because the code exists? Can a vendor's error reach a client with a credential
in it?

Run: python3 tests/test_platform_provider_safety.py
"""
import ast
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
BROKERS = os.path.join(ROOT, "apex", "platform", "brokers")

os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("APP_ENV", "dev")

from apex.platform.brokers import base                    # noqa: E402
from apex.platform.brokers import mt4_cloud               # noqa: E402
from apex.platform.brokers import mt5_cloud               # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"  OK   {name}" if cond else f"  FAIL {name} {detail}")
    if not cond:
        failures.append(name)


def raises(exc, fn):
    try:
        fn()
        return False
    except exc:
        return True
    except Exception:  # noqa: BLE001
        return False


def read_only_caps(**over):
    kw = dict(provider="test", mode=base.READ_ONLY, reads_accounts=True,
              reads_positions=True, reads_orders=True, reads_candles=True,
              supports_preview=True, supports_automation=False,
              can_place_orders=False, credential_model="test credential",
              verified=True)
    kw.update(over)
    return base.Capabilities(**kw)


print("\n1. a provider must state what it can do — there are no defaults")
# The failure being prevented: a provider omits can_place_orders, inherits
# False, and a later change "fixes" it to True believing the default was a
# decision somebody made rather than one nobody made.
import inspect                                             # noqa: E402
sig = inspect.signature(base.Capabilities.__init__)
required = [p for p in sig.parameters.values()
            if p.name != "self" and p.default is inspect.Parameter.empty]
check("every capability is a required argument",
      len(required) >= 11, f"{len(required)} required: "
      f"{[p.name for p in required]}")
check("and all of them are keyword-only, so they cannot be passed by "
      "position and silently transposed",
      all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in required))
check("omitting one is an error, not a default",
      raises(TypeError, lambda: base.Capabilities(provider="x",
                                                  mode=base.READ_ONLY)))

print("\n2. read-only and execution cannot both be claimed")
check("a read_only provider claiming can_place_orders is refused",
      raises(ValueError, lambda: read_only_caps(can_place_orders=True)))
check("an unknown mode is refused",
      raises(ValueError, lambda: read_only_caps(mode="sort-of")))
check("a provider must say what credential it takes",
      raises(ValueError, lambda: read_only_caps(credential_model="")))
check("a trading-mode provider is still constructible — this file is not "
      "pretending execution can never exist, only that it cannot arrive by "
      "accident",
      read_only_caps(mode=base.TRADING, can_place_orders=True,
                     supports_automation=True).can_place_orders is True)

print("\n3. the contract has no way to place an order")
# The absence is the design: adding execution must be a reviewed edit to
# base.py, not something a provider does by defining a method.
proto_methods = {n for n in dir(base.BrokerConnectionProvider)
                 if not n.startswith("_")}
FORBIDDEN = {"place_order", "submit", "close_position", "amend_sltp",
             "modify_position", "send_order", "execute"}
check("no execution method is in the provider contract",
      not (proto_methods & FORBIDDEN), str(proto_methods & FORBIDDEN))
check("but the read-only surface is actually there, so this check is not "
      "passing because the Protocol is empty",
      {"list_accounts", "get_positions", "get_orders", "get_candles",
       "get_account_status", "capabilities"} <= proto_methods,
      str(sorted(proto_methods)))

print("\n4. no provider module names a broker-mutating operation")
# Same list the platform-wide invariant uses. Checked again here, against the
# AST rather than the text, because a provider is the one place somebody has a
# genuine reason to write these words.
MUTATING = ("place_order", "close_position", "amend_sltp", "force_trade",
            "authorize_order", "authorize_close", "modify_position",
            "create_order", "send_order", "trade")
for fn in sorted(os.listdir(BROKERS)):
    if not fn.endswith(".py"):
        continue
    tree = ast.parse(io.open(os.path.join(BROKERS, fn), encoding="utf-8").read())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.FunctionDef):
            names.add(node.name)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            names.add(node.value)
    hits = sorted(set(MUTATING) & names)
    check(f"{fn} names no mutating operation", hits == [], str(hits))

print("\n5. enabling the MT4/MT5 spikes does not enable anything that trades")
for var in ("A4T_MT4_SPIKE_ENABLED", "A4T_MT4_SPIKE_VERIFIED",
            "A4T_MT5_SPIKE_ENABLED", "A4T_MT5_SPIKE_VERIFIED"):
    os.environ.pop(var, None)
for module, label, enable, verify in (
        (mt4_cloud, "MT4", "A4T_MT4_SPIKE_ENABLED", "A4T_MT4_SPIKE_VERIFIED"),
        (mt5_cloud, "MT5", "A4T_MT5_SPIKE_ENABLED", "A4T_MT5_SPIKE_VERIFIED")):
    check(f"{label} is off by default", module.enabled() is False)
    check(f"{label} is not verified by default", module.verified() is False)
    check(f"{label} hands out no provider while off",
          module.provider_if_enabled() is None)

for module, label, enable, verify in (
        (mt4_cloud, "MT4", "A4T_MT4_SPIKE_ENABLED", "A4T_MT4_SPIKE_VERIFIED"),
        (mt5_cloud, "MT5", "A4T_MT5_SPIKE_ENABLED", "A4T_MT5_SPIKE_VERIFIED")):
    os.environ[enable] = "true"
    p = module.provider_if_enabled()
    check(f"switching {label} on yields a provider", p is not None)
    caps = p.capabilities()
    check("which is read-only", caps.mode == base.READ_ONLY)
    check("and states it cannot place orders",
          caps.can_place_orders is False)
    check("and does not offer automation, because automation ends in an order",
          caps.supports_automation is False)
    check("preview is still offered, since it decides nothing",
          caps.supports_preview is True)
    check("enabled alone does NOT make it verified — a developer switching "
          "the spike on must not thereby tell clients MT4/MT5 works",
          caps.verified is False)
    check("the credential model is stated, and says investor password",
          "investor" in caps.credential_model.lower(),
          caps.credential_model)

    print("\n6. an unverified provider is never described to a client")
    check(f"describe() omits unverified {label}", base.describe([p]) == [])
    os.environ[verify] = "true"
    p2 = module.provider_if_enabled()
    check(f"and includes {label} once verified", len(base.describe([p2])) == 1)
    shown = base.describe([p2])[0]
    check("what is shown still says it cannot place orders",
          shown["canPlaceOrders"] is False, str(shown))

    print("\n7. nothing a client is shown carries a credential")
    blob = repr(shown)
    for secret in ("password", "investor", "login", "server", "token",
                   "secret", "credential"):
        check(f"the public view does not mention {secret}",
              secret not in blob.lower(), blob)

    print("\n8. the accessors refuse rather than inventing an answer")
    # An empty list would be a claim about the account. This connector has not
    # looked at the account, and saying "no positions" when you have not
    # looked is the kind of lie that loses money.
    for name, args in (("list_accounts", ("u",)),
                       ("get_account_status", ("u", "a")),
                       ("get_positions", ("u", "a")),
                       ("get_orders", ("u", "a")),
                       ("get_candles", ("u", "a", "EURUSD", "M5", 10))):
        check(f"{name} raises instead of returning a fabricated result",
              raises(base.ProviderError, lambda n=name, a=args:
                     getattr(p2, n)(*a)))
for var in ("A4T_MT4_SPIKE_ENABLED", "A4T_MT4_SPIKE_VERIFIED",
            "A4T_MT5_SPIKE_ENABLED", "A4T_MT5_SPIKE_VERIFIED"):
    os.environ.pop(var, None)

print("\n9. provider errors are safe to surface")
e = base.ProviderError("VENDOR_UNAVAILABLE", "the broker data service did "
                       "not answer")
check("a provider error carries a code the UI can branch on",
      e.code == "VENDOR_UNAVAILABLE")
check("and a message this codebase wrote, not the vendor's",
      "did not answer" in e.detail)
# The failure this guards against really happened, in apex/brokers/ctrader.py:
# requests' own HTTPError message carried the full URL, and the URL carried
# client_secret and the authorization code.
src_all = "\n".join(
    io.open(os.path.join(BROKERS, f), encoding="utf-8").read()
    for f in sorted(os.listdir(BROKERS)) if f.endswith(".py"))
tree_all = ast.parse(src_all)
bare_reraise = []
for node in ast.walk(tree_all):
    if isinstance(node, ast.Raise) and node.exc is None:
        bare_reraise.append(node.lineno)
    if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Name):
        # `raise e` where e came from an except clause re-emits the vendor's
        # own message. Every raise here must construct a ProviderError.
        bare_reraise.append(node.lineno)
check("no provider module re-raises a vendor exception unchanged",
      bare_reraise == [], f"bare re-raise at lines {bare_reraise}")

print("\n10. the spike is not reachable from the running platform")
# The strongest statement available: no production module imports it. When
# somebody wires it up, this fails, and that failure is the review.
import subprocess                                          # noqa: E402
plat = os.path.join(ROOT, "apex", "platform")
importers = []
for d, subdirs, files in os.walk(plat):
    subdirs[:] = [s for s in subdirs if s != "__pycache__"]
    for f in files:
        if not f.endswith(".py"):
            continue
        rel = os.path.relpath(os.path.join(d, f), plat)
        if rel.startswith("brokers" + os.sep):
            continue
        text = io.open(os.path.join(d, f), encoding="utf-8").read()
        # Matched precisely, not by substring. `apex.brokers` is the cTrader
        # client and is imported all over the platform; `apex.platform.brokers`
        # is this package. A substring check calls the first one a violation —
        # it did, on the first run.
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod == "apex.platform.brokers" or \
                        mod.startswith("apex.platform.brokers."):
                    importers.append(rel)
                elif mod == "apex.platform" and any(
                        a.name == "brokers" for a in node.names):
                    importers.append(rel)
                elif node.level and (mod == "brokers"
                                     or mod.startswith("brokers.")):
                    importers.append(rel)
                elif node.level and mod == "" and any(
                        a.name == "brokers" for a in node.names):
                    importers.append(rel)
            elif isinstance(node, ast.Import):
                if any(a.name == "apex.platform.brokers"
                       or a.name.startswith("apex.platform.brokers.")
                       for a in node.names):
                    importers.append(rel)
check("no platform module outside the package imports a provider",
      importers == [], f"imported by {sorted(set(importers))}")

# A check that cannot fail proves nothing. The same walk, over a module that
# DOES import the package, must find it — including the cTrader import that
# made the first version of this check fire wrongly.
_probe = ast.parse(
    "from apex.brokers import ctrader as _ct\n"          # must NOT match
    "from apex.platform import store as _store\n"        # must NOT match
    "from apex.platform.brokers import mt5_cloud\n")     # must match
_found = []
for node in ast.walk(_probe):
    if isinstance(node, ast.ImportFrom):
        mod = node.module or ""
        if mod == "apex.platform.brokers" or \
                mod.startswith("apex.platform.brokers."):
            _found.append(mod)
        elif mod == "apex.platform" and any(
                a.name == "brokers" for a in node.names):
            _found.append(mod)
check("and the scan detects a real importer when there is one",
      _found == ["apex.platform.brokers"], str(_found))

api = io.open(os.path.join(plat, "api.py"), encoding="utf-8").read()
check("and no route mentions mt4 or mt5",
      "mt4" not in api.lower() and "mt5" not in api.lower())
web = os.path.join(ROOT, "..", "web", "src")
if os.path.isdir(web):
    hits = []
    for dirpath, _dirnames, filenames in os.walk(web):
        for name in filenames:
            path = os.path.join(dirpath, name)
            try:
                text = io.open(path, encoding="utf-8").read().lower()
            except UnicodeDecodeError:
                continue
            if "mt4" in text or "mt5" in text:
                hits.append(os.path.relpath(path, web))
    check("nor does the web UI claim MT4/MT5 anywhere", not hits,
          ", ".join(sorted(hits)))

print("\n" + "=" * 62)
if failures:
    print(f"{len(failures)} FAILED: {', '.join(failures)}")
    sys.exit(1)
print("all provider safety checks passed")
