"""An MT4 connector through a cloud provider. READ ONLY, and unwired.

STATUS: spike. Nothing imports this outside provider-safety tests. No route
serves it, no UI mentions it, and no client can enter credentials for it.

WHY THIS EXISTS

MetaApi supports both MetaTrader 4 and MetaTrader 5 through the same cloud
terminal model: account login, password, broker server name and platform. For
Apex4Traders, the only acceptable V1.5 shape is the read-only version of that
model, using an INVESTOR password. A client installs nothing and can use phone
or PC, but the privacy cost is real: a broker credential is held by a vendor.

The safety property is the same one recorded for MT5: an investor password can
read account data and cannot place, modify or close orders at the broker. This
module is therefore read-only by credential, not merely by an application flag.

Execution is deliberately absent. If MT4 execution is ever considered, it needs
a separate design, a master password, legal review, and a new live-execution
gate. None of that is present here.
"""
import os

from apex.platform.brokers import base

PROVIDER = "mt4_cloud"
_ENABLED_VAR = "A4T_MT4_SPIKE_ENABLED"
_VERIFIED_VAR = "A4T_MT4_SPIKE_VERIFIED"


def _flag(name) -> bool:
    return (os.getenv(name) or "").strip().lower() in (
        "1", "true", "yes", "on")


def enabled() -> bool:
    return _flag(_ENABLED_VAR)


def verified() -> bool:
    return enabled() and _flag(_VERIFIED_VAR)


class Mt4CloudProvider:
    """Reads an MT4 account through a cloud vendor. Places nothing."""

    def capabilities(self):
        return base.Capabilities(
            provider=PROVIDER,
            mode=base.READ_ONLY,
            reads_accounts=True,
            reads_positions=True,
            reads_orders=True,
            reads_candles=True,
            supports_preview=True,
            supports_automation=False,
            can_place_orders=False,
            credential_model=(
                "MT4 login + INVESTOR password + broker server name, held by "
                "the cloud vendor; investor password cannot place orders at "
                "the broker"),
            verified=verified(),
        )

    def _unimplemented(self, what):
        return base.ProviderError(
            "PROVIDER_NOT_IMPLEMENTED",
            f"the MT4 cloud connector cannot {what} yet")

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
    return Mt4CloudProvider() if enabled() else None
