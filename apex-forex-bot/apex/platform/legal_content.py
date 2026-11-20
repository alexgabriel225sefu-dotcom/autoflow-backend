"""Versioned legal drafts. Nothing in this module is published on import.

The pages under the web app carry the text (terms, refund policy, tax
notice) at ``CURRENT_VERSION``. This module is the switch that promotes
that version into the live gate.

Publication is off unless ``A4T_LEGAL_PUBLISH`` is exactly
``CURRENT_VERSION``. ``1``, ``true``, ``yes`` and any other version do
not publish. An operator must then call ``publish_current``. Setting the
variable is the owner's action; the call is the admin step. Neither
happens here.
"""

import os

from apex.platform.live_gate import LiveGateError

# Keep in lockstep with web/src/content/legal-publication.ts.
CURRENT_VERSION = "2026-10-24"
PUBLISH_ENV = "A4T_LEGAL_PUBLISH"
DRAFT_MARK = "DRAFT - requires legal review"

# The live gate's document ids. The public routes are /terms, /refunds, /tax.
DOCUMENTS = ("terms", "refund", "tax")

PLACEHOLDERS = (
    "COMPANY_NAME",
    "REGISTRATION_NUMBER",
    "ADDRESS",
    "JURISDICTION",
    "VAT",
)


def published_version():
    """The current version when the owner has named it, otherwise None."""
    got = (os.getenv(PUBLISH_ENV) or "").strip()
    if got == CURRENT_VERSION:
        return CURRENT_VERSION
    return None


def status():
    """What a caller may be told. No company details and no document body."""
    version = published_version()
    return {
        "version": CURRENT_VERSION,
        "published": version is not None,
        "notice": None if version else DRAFT_MARK,
        "documents": list(DOCUMENTS),
    }


def publish_current(actor):
    """Record this draft as the live gate's current version.

    Refuses when the env does not name ``CURRENT_VERSION``, and writes
    nothing in that case. Does not accept a version from the caller.
    """
    if published_version() is None:
        raise LiveGateError(
            "UNPUBLISHED",
            "publication is off until A4T_LEGAL_PUBLISH equals the current "
            "draft version",
            status=409)
    from apex.platform import live_gate as gate
    for doc in DOCUMENTS:
        gate.publish(doc, CURRENT_VERSION, actor=actor)
    return status()
