/**
 * The decided refund rule. The same sentences as
 * apex/platform/refund_policy.py. Checkout, pricing, the terms and the
 * refunds page all read these, so none of them can drift.
 *
 * The free 14-day demo is the trial. A licence purchase is final once
 * access is granted, except where the law requires otherwise.
 */
export const REFUND_POLICY_VERSION = "2026-11-09";

export const PURCHASE_NOTE =
  "You get a free 14-day demo to test Apex4Traders before buying. Licence purchases are final and non-refundable once access is granted, except where required by law.";

export const DEMO_CONDITIONS_NOTE =
  "Demo conditions (fills, spreads, slippage) can differ from live trading.";

export const WITHDRAWAL_CONSENT_LABEL =
  "I request immediate access to the licence and acknowledge that I lose my 14-day right of withdrawal once access is granted.";

export const DURABLE_MEDIUM =
  "This purchase confirmation, kept on your account, is the confirmation of that consent on a durable medium under the EU Consumer Rights Directive 2011/83/EU, article 16(m).";

export const DEMO_IS_NOT_LIVE =
  "The free 14-day demo is the trial. It is not live trading, and a demo result is not a forecast of a live result.";
