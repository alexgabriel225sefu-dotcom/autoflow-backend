"""The decided refund rule, and the words checkout records.

The free 14-day demo is the trial. A licence purchase is final once access
is granted, except where the law requires otherwise. The 14-day withdrawal
right for digital content (Consumer Rights Directive 2011/83/EU, article
16(m)) is lost only when performance began with prior express consent, the
consumer acknowledged the loss, and the trader confirms that on a durable
medium. The sentences below are that consent and that confirmation.

The web copy in ``web/src/content/refund-policy.ts`` has to stay identical.
A test reads both files.
"""

from datetime import datetime, timezone

POLICY_VERSION = "2026-11-09"

PURCHASE_NOTE = "You get a free 14-day demo to test Apex4Traders before buying. Licence purchases are final and non-refundable once access is granted, except where required by law."

DEMO_CONDITIONS_NOTE = "Demo conditions (fills, spreads, slippage) can differ from live trading."

CONSENT_STATEMENT = "I request immediate access to the licence and acknowledge that I lose my 14-day right of withdrawal once access is granted."

DURABLE_MEDIUM = "This purchase confirmation, kept on your account, is the confirmation of that consent on a durable medium under the EU Consumer Rights Directive 2011/83/EU, article 16(m)."

# Stripe Checkout Session metadata. The key limit is 40 characters.
META_AT = "withdrawalConsentAt"
META_VERSION = "withdrawalPolicyVersion"
META_USER = "withdrawalConsentUserId"


def version_ok(value):
    text = str(value or "").strip()
    if len(text) != 10 or text[4] != "-" or text[7] != "-":
        return False
    year, month, day = text.split("-")
    return year.isdigit() and month.isdigit() and day.isdigit()


def _iso(ts):
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def confirmation_text(*, user_id, policy_version, consented_at,
                      access_granted_at=None):
    """The receipt text. Quotes the waiver and names who consented, when."""
    parts = [
        "Purchase confirmation.",
        f'You agreed: "{CONSENT_STATEMENT}"',
        (
            f"Consent recorded for user {user_id} at {_iso(consented_at)} "
            f"under refund policy {policy_version}."
        ),
        DURABLE_MEDIUM,
    ]
    if access_granted_at is not None:
        parts.append(
            f"Access was granted at {_iso(access_granted_at)}. "
            "That is when the 14-day right of withdrawal was lost."
        )
    parts.append(PURCHASE_NOTE)
    parts.append(DEMO_CONDITIONS_NOTE)
    return " ".join(parts)
