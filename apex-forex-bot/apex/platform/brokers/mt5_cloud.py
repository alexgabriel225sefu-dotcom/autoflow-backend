"""An MT5 connector through a cloud provider. READ ONLY, and unwired.

STATUS: spike. Nothing imports this. No route serves it. It is here so the
contract in `base.py` has a second implementation to be tested against, and so
the credential model is written down in code rather than argued about later.

WHY A CLOUD PROVIDER AT ALL

MetaTrader 5 has no first-party REST API. MetaQuotes ships MQL5 for Expert
Advisors, a Manager/Server API licensed to brokers, and a web terminal for
humans; none of those is a machine interface a platform may use on a client's
behalf. So the options are: make the client install something, get a broker
partnership, or go through a vendor that runs the terminals. The owner's
requirement — no local bridge, no EA, no VPS, works from a phone — rules out
the first, and the second is not available to a new platform.

See docs/MT5_CLOUD_CONNECTOR_SPIKE.md for the full comparison.

THE CREDENTIAL MODEL, WHICH IS THE WHOLE SAFETY ARGUMENT

MetaApi's account provisioning takes `login`, `password`, `server` and
`platform`. Their documentation states:

    "The password can be either investor password for read-only access or
    master password to enable trading features."
    — https://metaapi.cloud/docs/provisioning/api/account/createAccount/

This connector accepts ONLY an investor password. That is not a policy this
code enforces with an `if`; it is a property of the credential. On an investor
password the BROKER refuses order placement, so read-only survives a bug in
this file, a mistake in the platform, and a compromise of the vendor account.

A software flag that says "read only" is worth much less than a credential
that cannot trade.

WHAT THIS STILL COSTS, stated plainly because it does not go away:

  - The client hands a broker credential to a third party. Even an investor
    password discloses every position, order and balance to MetaApi and to us.
  - It is a vendor dependency in the data path: their outage is our outage.
  - An investor password cannot be scoped or revoked per-integration. The only
    revocation is the client changing it at the broker.

None of that is acceptable to ship silently, which is why no UI collects this
and why `verified` is False until somebody proves the path end to end.
"""
import os

from apex.platform.brokers import base

PROVIDER = "mt5_cloud"

# Two switches, both off, and neither of them turns on execution — there is no
# execution here to turn on. The first admits the provider at all; the second
# says a human has proven it against the real vendor in THIS deployment.
_ENABLED_VAR = "A4T_MT5_SPIKE_ENABLED"
_VERIFIED_VAR = "A4T_MT5_SPIKE_VERIFIED"

# Read at call time, never captured at import: a module-level constant means a
# deployment cannot turn this off without a restart, and "turn it off now" is
# the operation that matters.
def enabled() -> bool:
    return (os.getenv(_ENABLED_VAR) or "").strip().lower() in (
        "1", "true", "yes", "on")


def verified() -> bool:
    """Whether this deployment has PROVEN the connector, not merely enabled it.

    Kept separate from `enabled` so that switching the spike on for a
    developer cannot, by itself, make the platform tell a client that MT5 is
    supported. Enabling is a deployment decision; verification is a claim
    about reality.
    """
    return enabled() and (os.getenv(_VERIFIED_VAR) or "").strip().lower() in (
        "1", "true", "yes", "on")


class Mt5CloudProvider:
    """Reads an MT5 account through a cloud vendor. Places nothing.

    Every accessor raises until the vendor call is written. Raising is the
    honest state: returning [] would be a claim that the account has no
    positions, and this connector has not looked.
    """

    def capabilities(self):
        return base.Capabilities(
            provider=PROVIDER,
            mode=base.READ_ONLY,
            reads_accounts=True,
            reads_positions=True,
            reads_orders=True,
            reads_candles=True,
            # Preview evaluates a rule against market data and decides nothing,
            # so it is reachable read-only. Automation ends in an order, so it
            # is not, and saying so here is what stops the platform offering an
            # automation toggle beside an MT5 account.
            supports_preview=True,
            supports_automation=False,
            can_place_orders=False,
            credential_model=(
                "MT5 login + INVESTOR password + broker server name, held by "
                "the cloud vendor; investor password cannot place orders at "
                "the broker"),
            verified=verified(),
        )

    # ── read-only accessors ─────────────────────────────────────────────
    # Each refuses the same way, for the same reason: this is a skeleton, and
    # a skeleton that answers is worse than one that does not.

    def _unimplemented(self, what):
        return base.ProviderError(
            "PROVIDER_NOT_IMPLEMENTED",
            f"the MT5 cloud connector cannot {what} yet")

    def list_accounts(self, user_id):
        raise self._unimplemented("list accounts")

    def get_account_status(self, user_id, account_id):
        raise self._unimplemented("report account status")

    def get_positions(self, user_id, account_id):
        raise self._unimplemented("read positions")

    def get_orders(self, user_id, account_id):
        raise self._unimplemented("read orders")

    def get_candles(self, user_id, account_id, symbol, timeframe, limit):
        raise self._unimplemented("read candles")


def provider_if_enabled():
    """The provider, or nothing at all.

    Returning None rather than a disabled object means a caller that forgets
    to check gets an AttributeError in its own tests, instead of an object
    that quietly answers for a connector this deployment never turned on.
    """
    return Mt5CloudProvider() if enabled() else None
