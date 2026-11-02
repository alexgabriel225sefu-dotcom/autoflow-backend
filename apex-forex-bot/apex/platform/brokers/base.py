"""What every broker connector must be able to say about itself.

WHY A CONTRACT BEFORE A SECOND BROKER

cTrader is currently wired in directly: `ctrader_link` knows about OAuth,
`api.py` knows about `ctrader/*` routes, the connect page knows about a
two-step approval. Adding MT5 by copying that shape would duplicate the parts
that must never diverge — the live-execution locks, the entitlement check, the
redaction rules — into a second place where only one of them gets fixed next
time.

So the platform talks to a PROVIDER, and a provider answers three kinds of
question:

  1. What can you do?          → capabilities(), declared, never inferred
  2. What does this client have? → the read-only accessors
  3. May you trade?             → `can_place_orders`, which is a claim the
                                  provider makes and the platform still
                                  refuses to act on in this release

THE POINT OF (3)

`can_place_orders` is deliberately NOT a switch. A provider setting it True
does not make execution reachable: `bridge.submit` remains unimported by
anything in production, and `entitlement.live_execution_enabled()` returns a
literal False. The flag exists so the platform can describe a provider
honestly in an operator view, and so a provider CANNOT quietly acquire
execution by implementing a method nobody declared.

tests/test_platform_provider_safety.py holds that line, and
tests/test_platform_live_invariants.py proves the execution module is still
unreachable from anywhere — including from this package, which it now walks
because a subpackage used to escape it.

NOT A BASE CLASS

A Protocol, so a provider is whatever satisfies the shape. Inheritance would
let a provider pick up a default implementation of something dangerous by
forgetting to override it; there are no defaults to inherit here.
"""
from typing import Protocol, runtime_checkable

# Read-only means read-only. A provider in this mode is not trusted to refuse
# an order — it is never asked to place one, and for MT5 the broker itself
# refuses, because the credential is an investor password.
READ_ONLY = "read_only"
TRADING = "trading"

MODES = (READ_ONLY, TRADING)


class Capabilities:
    """A provider's own account of what it supports.

    Every field is required and explicit. There is no default: a provider that
    forgets to state whether it can place orders must fail to construct, not
    quietly inherit False and later be "fixed" to True by somebody who assumed
    the default was the decision.
    """

    __slots__ = ("provider", "mode", "reads_accounts", "reads_positions",
                 "reads_orders", "reads_candles", "supports_preview",
                 "supports_automation", "can_place_orders",
                 "credential_model", "verified")

    def __init__(self, *, provider, mode, reads_accounts, reads_positions,
                 reads_orders, reads_candles, supports_preview,
                 supports_automation, can_place_orders, credential_model,
                 verified):
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, not {mode!r}")
        if mode == READ_ONLY and can_place_orders:
            # Not a warning. A provider that calls itself read-only and claims
            # execution is describing two different things, and the platform
            # has no way to know which one the code does.
            raise ValueError(
                f"{provider}: a read_only provider cannot also claim "
                f"can_place_orders")
        if not isinstance(credential_model, str) or not credential_model:
            raise ValueError(
                f"{provider}: credential_model must say what the client hands "
                f"over, so the risk is visible wherever capabilities are")
        self.provider = provider
        self.mode = mode
        self.reads_accounts = bool(reads_accounts)
        self.reads_positions = bool(reads_positions)
        self.reads_orders = bool(reads_orders)
        self.reads_candles = bool(reads_candles)
        self.supports_preview = bool(supports_preview)
        self.supports_automation = bool(supports_automation)
        self.can_place_orders = bool(can_place_orders)
        self.credential_model = credential_model
        # Whether this provider has been proven against the real vendor in
        # this deployment. A provider that exists in code is not a provider a
        # client may be told about.
        self.verified = bool(verified)

    def public(self):
        """What may be shown outside the server.

        Never the credential itself, never a vendor token, never a broker
        server name — a server name plus a login is most of what an attacker
        needs to try the rest.
        """
        return {
            "provider": self.provider,
            "mode": self.mode,
            "reads": {
                "accounts": self.reads_accounts,
                "positions": self.reads_positions,
                "orders": self.reads_orders,
                "candles": self.reads_candles,
            },
            "supportsPreview": self.supports_preview,
            "supportsAutomation": self.supports_automation,
            "canPlaceOrders": self.can_place_orders,
            "verified": self.verified,
        }


@runtime_checkable
class BrokerConnectionProvider(Protocol):
    """The whole surface the platform is allowed to use.

    Every method takes `user_id` first and is expected to refuse anything that
    does not belong to that user. Ownership is not the caller's business to
    check and then forget to check: it is the provider's contract.

    There is no `place_order` in this Protocol, and that absence is the
    design. Adding one is a reviewable change to this file, not something a
    provider can do on its own by defining a method.
    """

    def capabilities(self) -> Capabilities:
        """What this provider supports. Declared, never inferred."""
        ...

    def list_accounts(self, user_id):
        """The broker accounts this user has connected, demo and live
        separated by the BROKER's own flag and never by anything the client
        sent."""
        ...

    def get_account_status(self, user_id, account_id):
        """Whether the account is reachable right now, and in what mode."""
        ...

    def get_positions(self, user_id, account_id):
        """Open positions. An empty list is a fact, not a placeholder."""
        ...

    def get_orders(self, user_id, account_id):
        """Working and historical orders."""
        ...

    def get_candles(self, user_id, account_id, symbol, timeframe, limit):
        """Market candles for a symbol this account can actually see."""
        ...


class ProviderError(RuntimeError):
    """A provider refusal, already safe to surface.

    Providers talk to vendors, and vendor errors quote what was sent — which
    for a broker connector means a login, a server name, sometimes a password
    in a URL. `apex/brokers/ctrader.py` had exactly that: an HTTPError whose
    message carried the client secret, found only because somebody exercised
    the failure path on purpose.

    So a provider never raises the vendor's exception. It raises this, with a
    code the UI can branch on and a message it wrote itself.
    """

    def __init__(self, code, detail):
        self.code, self.detail = code, detail
        super().__init__(f"{code}: {detail}")


def describe(providers):
    """What the platform may say about the brokers it supports.

    Only VERIFIED providers are described. A provider that exists in the
    codebase but has never been proven against the real vendor in this
    deployment is not something a client may be shown — "MT5 supported" is a
    promise, and a skeleton is not a promise anyone should make.
    """
    return [p.capabilities().public() for p in providers
            if p.capabilities().verified]
