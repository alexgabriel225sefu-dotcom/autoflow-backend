# Legal launch blockers

Values the operator has to supply before the public pages can be described as
complete. Each one appears in the product as a literal `[TO BE CONFIRMED]`
marker, so they are greppable:

```
grep -rn "TO BE CONFIRMED" web/src
```

**The site must not be described as legally ready until this list is empty.**
Nothing here was guessed. Writing a plausible registered address or a
plausible refund policy would be worse than leaving the field blank, because a
blank is visibly unfinished and a plausible invention is not.

---

## What was removed

The previous Terms and Privacy pages described a different product:

| Was | Problem |
|---|---|
| "Apex Trade Bot is sold as a one-time purchase of software source code" | No source code is sold. The product is a hosted platform. |
| "Cryptocurrency trading involves significant financial risk" | The platform trades forex and CFDs through cTrader. The asset class was wrong. |
| "all sales are final once the source code has been delivered" | Describes delivery of a thing that is not delivered. |
| "We collect your name and email address when you make a purchase … to deliver your product" | Describes a one-off sale, not an account on a platform. |
| `support@aicashsystem.space` | A different brand's domain. |
| "Setup Your Bot" / "source code download link" (`/configurator`) | Nothing is downloaded and there is no bot. |

## What the pages now state, and why those parts are safe

These are factual claims about the software, checkable by reading the code:

| Claim | Where it is true in the code |
|---|---|
| Orders go to a cTrader account the client connects themselves | `apex/platform/ctrader_link.py` |
| The client can disconnect it | `POST /api/v1/ctrader/disconnect` |
| The platform holds no client funds and cannot move money | no deposit or withdrawal endpoint exists |
| Cash flow history is not read | `tests/test_positioning_claims.py` forbids the string `CashFlowHistory` under `apex/` |
| Broker tokens are encrypted at rest and never reach the browser | `apex/user_store.py`; no endpoint returns a token |
| Live trading is not available in this release | `automation.start` refuses a non-demo account; `tests/test_live_path_invariants.py` |
| No advertising or analytics tracking | no third-party script or iframe in `web/src` |

## The blockers

| # | Needed | Appears in | Consequence of leaving it |
|---|---|---|---|
| **L1** | **Legal entity name, registered address, company number** | Terms §10, Privacy §9 | The site does not say who the contract is with. |
| **L2** | **Governing law and jurisdiction** | Terms §10 | No stated forum for a dispute. |
| **L3** | **Support / contact address** | Terms §11, Privacy §9 | A client has no way to reach the operator. The old address belonged to another brand and was removed rather than replaced. |
| **L4** | **Refund policy** | Terms §9 | The webhook already revokes a licence on refund; what a client is *entitled* to is not a code question. |
| **L5** | **Pricing and billing period** | Terms §9 | Blocked on the same decisions as `docs/PAYMENT_AND_LICENCE_DECISIONS.md` D1–D3. |
| **L6** | **Hosting provider, data region, sub-processor list** | Privacy §4 | Required by most privacy regimes. Supabase, cTrader and Stripe are named because they are in the dependency list; the hosting provider and region are not something this repository can state. |
| **L7** | **Retention periods** | Privacy §6 | How long account data, journal entries and disconnected broker links are kept. |
| **L8** | **Data subject rights and how to exercise them** | Privacy §7 | Depends on L2. |
| **L9** | **Last-updated date of the approved version** | Terms, Privacy | A policy with no date cannot be versioned. |

## Beyond the two pages

These are not in the page text but bear on the same launch decision, and are
listed so they are not discovered late:

- **Regulatory classification.** `docs/ARCHITECTURE_V2.md` §8 already records
  this: the fact that a client chooses their own settings does not by itself
  determine the provider's liability or the product's classification. Whether
  offering rule-based automated execution requires any authorisation in the
  operator's jurisdiction is a question for a qualified adviser, not for this
  repository.
- **Marketing claims.** The landing page carries no performance figure, no
  testimonial and no return claim, and nothing in the platform invents a
  balance or a profit. Keeping it that way is a launch condition, not a
  preference.
- **Risk warning placement.** Some jurisdictions require a specific risk
  warning, in specific words, in a specific position. The platform states risk
  plainly; whether it states it in the required form is L2-dependent.
