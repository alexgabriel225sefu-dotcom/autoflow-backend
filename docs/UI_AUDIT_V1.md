# Apex4Traders — runtime UI audit

**Date:** 2026-09-23 · **Commit audited:** `8058dd12d`
**Method:** the app was built and served locally (`next start`, production build)
and driven with Playwright/Chromium at 1440×900 and 390×844. Every page below
was actually loaded and photographed; nothing here is inferred from source
alone.

**Nothing was changed.** This document records findings only. No redesign, no
pricing, legal, payment or behavioural edit was made.

## How it was run

The backend was served by a local harness that calls the **real**
`apex.platform.api.handle()` against a throwaway `DATA_DIR` with a per-run
encryption key, with token verification replaced by a fixed test principal.
Every API response seen below is produced by product code, not by a mock.
The two rules in the screenshots were created through the real `POST /rules`
and `POST /rules/{id}/activate`, so they passed real validation.

cTrader is genuinely **not connected** in this environment, which is the
correct state for the audit: it is exactly what a new client sees.

Harness and screenshots live outside the repository history
(`ui-audit/`, ignored). `web/.env.local` points at the local harness and is
already covered by `.gitignore`.

## Summary

| | |
|---|---|
| Routes loaded | **21 / 21** |
| Console errors | **0** |
| Horizontal overflow on mobile | **0 px** on every page checked |
| Unreadable filled controls | **15**, across 8 routes |
| Nav items reachable on a 390 px screen | **1 of 8** |

The platform pages are honest and well-written. Two defects make them hard to
use, and three legacy pages still carry the previous product's identity.

---

## Finding 1 — every primary call to action is invisible (blocker)

`globals.css:134` defines

```css
.a4t a { color: var(--a4t-accent); }     /* specificity (0,1,1) */
```

and `globals.css:161` defines

```css
.btn { background: var(--a4t-accent); color: #061024; }   /* (0,1,0) */
```

The first wins. Every **link** styled as a primary button therefore renders
accent text on an accent fill: measured contrast **1.00 : 1**. A `<button
class="btn">` is unaffected, which is why "Save draft" and "Sign out" read
correctly while "Connect cTrader" does not.

| Route | Unreadable controls |
|---|---|
| `/` | Create account, Create your account |
| `/dashboard` | Connect cTrader × 3 |
| `/accounts` | Connect cTrader |
| `/positions` | Connect cTrader |
| `/orders` | Connect cTrader |
| `/rules` | New rule |

`Connect cTrader` is the first action in onboarding and it is invisible on five
screens. This is the single highest-impact defect in the product.

## Finding 2 — the app is not navigable on a phone (blocker)

On a 390 px viewport the nav strip measures `clientWidth` 135 px against
`scrollWidth` 599 px. Only **Dashboard** is on screen. Rules, Positions,
Orders, Journal, Alerts, Accounts and Settings are all off to the right, with
no scroll affordance, no overflow menu and no bottom bar. The page itself does
not overflow, so there is no cue that anything is hidden.

## Finding 3 — the Rule Builder cannot express most of a rule

`ruledoc.blank()` defines `sizing`, `stopLoss`, `takeProfit`, `trailingStop`,
`breakEven`, `limits`, `schedule` and `order`. The builder submits only
`name`, `symbols`, `timeframe`, `sides`, `entry` and `exit`.

Everything else silently takes the server default — 1.0 % risk, a 1.5 × ATR
stop, a 2.0 RR target, one open position, no schedule. The client never sees
those numbers and cannot change them. That sits badly against the product
invariant, which promises to respect *the limits the client switched on*.

## Finding 4 — a rule's detail page does not show the rule

`/rules/{id}` shows instruments, timeframe, sides and state. It does not show
the entry or exit conditions, the stop, the target or the sizing. There is no
way to read what an active rule will actually do, and no way to see a version's
terms before or after editing.

## Finding 5 — three legacy pages carry the previous product

| Route | What it still says |
|---|---|
| `/terms` | "Apex Trade Bot is sold as a one-time purchase of software source code"; risk clause is about **cryptocurrency** |
| `/privacy` | Title "Privacy Policy — Apex Trade Bot"; contact address `support@aicashsystem.space`, a different brand entirely |
| `/configurator` | "Setup Your Bot", "deploy your Apex Trade Bot", "source code download link"; amber accent, not the platform blue |

`/terms` and `/privacy` are linked from the live landing page footer.
`/configurator` is reachable by URL. All three are **business and legal
surfaces** and are left untouched by decision.

Also still present, not customer-visible: `POST /api/create-payment-intent`
(`amount: 29700`, `product: "apex-bot"`), and the unused
`components/ui/modern-payment-form.tsx`.

## Finding 6 — two competing button systems

`components/ui/button.tsx` (shadcn, `--primary: #f59e0b` amber) is used in 3
files. The hand-written `.btn` class (`--a4t-accent` blue) is used in 18. The
amber token is what `/configurator` renders; the blue is the platform. Two
accent colours are live in one product.

## Smaller observations

- Instrument notation is inconsistent: the builder pre-fills `EUR_USD`, the
  rules list shows `EURUSD`.
- The condition parameter grid is ragged — `op` and `pips` leave a hole at
  1440 px, and the form is a single narrow column in a wide canvas.
- `v1 · active` on the rule page is monospace and low contrast against the
  page title beside it.
- Condition labels are raw ids (`atr`, `ma_cross`, `price_vs_ma`) rather than
  the human names the backend already supplies in `doc`.
- `/rules/new` offers no validate or preview; both exist only after saving.

## What is already right

Worth stating plainly, because it constrains the redesign rather than being
replaced by it:

- **No invented data anywhere.** Every empty state names its cause — "No
  cTrader account is connected", "Nothing recorded for this filter" — and the
  `{connected, status}` contract is respected in the UI.
- **No profit claims, no pricing, no testimonials** on any platform page.
- The landing page's "What this is not" block already states: not financial
  advice, no claim about returns, risk of capital loss, orders placed through
  an account the client connects and can disconnect.
- Demo-first is stated on the landing page and repeated on the rule page
  ("Automation (demo)").
- The journal filter exposes the real status vocabulary, including `hold` and
  `reject` — decisions that do nothing are first-class.
- Zero console errors on 21 routes.

---

# Proposed design direction — Apex4Traders V1

A serious trading operations platform: cTrader-connected, demo-first, no
broker custody, no profit promises. The direction below follows from what the
product already refuses to do, rather than from a visual trend.

## 1. Posture: an operations console, not a landing page

The client's question on every screen is *what is running, on what account,
and what did it decide*. The UI should answer that above the fold and never
make them hunt for it. Concretely: a persistent status strip carrying account
· mode (DEMO/LIVE) · automation state · licence, visible on every page of the
app shell, not only on the dashboard.

## 2. Make mode impossible to misread

`demo` and `live` must be distinguishable without reading. A permanent,
colour-coded mode badge in the status strip, and a distinct chrome treatment
when an account is live. Since live is not enabled in this release, the demo
badge should be present and explicit rather than absent.

## 3. One accent, and a semantic palette

Retire the amber shadcn token or the blue `.btn` system — not both alive.
Then reserve colour for meaning: one accent for actions, and separate, fixed
hues for `demo`, `live`, `ok`, `warn`, `danger`. The `.pill-*` classes already
sketch this; it should become the rule rather than an exception.

Fix the cascade properly: give `.btn` its own foreground that a link colour
cannot outrank, and add a contrast assertion to the test suite so a 1.00 : 1
control can never ship again.

## 4. The rule is the product — show all of it

The rule surface needs to carry the whole `RuleDoc`, in the builder and in the
detail view:

- entry and exit conditions in readable language, using the `doc` string the
  backend already returns, not the raw id
- sizing, stop, target, trailing, break-even, limits and schedule as visible,
  editable sections with their current values — defaults shown as defaults,
  never hidden
- a plain-language restatement of the rule ("Buy EURUSD on 1h when EMA(50) is
  below price AND RSI(14) is above 55; risk 1.0 % per trade; stop 1.5 × ATR")

A client who cannot read their own rule back cannot be said to have configured
it.

## 5. Preview as the centre of trust, not a side panel

The evaluator already returns every condition with its result. That is the
product's strongest differentiator and it is currently behind a disabled box.
Preview should be a first-class view: each condition listed with true / false /
unknown, the verdict, and the reason — the same structure the journal shows
afterwards, so the client learns one layout and reads it in both places.

## 6. Refusals get the same care as successes

The platform's distinctive behaviour is that it stops and says why. Those
moments deserve designed states, not grey text: insufficient history, a limit
that cannot be honoured, a stop inside the spread, an expired licence, a broker
that could not be reached. Each with its cause and its one next action.

## 7. Mobile: a real shell

A bottom navigation bar for the primary destinations, an overflow for the rest,
and tables that become stacked records rather than horizontally scrolling grids.
The monitoring case — checking what happened from a phone — is at least as
common as building a rule at a desk.

## 8. Typography and density

Tabular figures for every price, volume, pip and percentage. A tighter type
scale with a clear hierarchy of page title → card title → label → value; the
current cards read flat because labels and values share weight. Dark stays, but
with one more elevation step so cards separate from the page without borders
doing all the work.

## 9. Keep the honesty, make it visible

The disclaimers are already correct. They should be placed where the decision
happens — next to the connect button, next to activation, next to automation
start — rather than only in a footer block. The same applies to "we never see
your broker tokens" and "we cannot move your money", which are currently stated
once on `/connect` and are among the strongest things the product can say.

## Suggested order of work

| # | Item | Why first |
|---|---|---|
| 1 | Fix `.btn` contrast + add a contrast test | One line of CSS; the product is unusable without it |
| 2 | Mobile navigation shell | Seven of eight destinations are unreachable on a phone |
| 3 | Rule Builder: sizing, stop, target, limits, schedule | Closes the gap against the product invariant |
| 4 | Rule detail: show the whole document | A client must be able to read their own rule |
| 5 | Preview as a first-class view | The differentiator, currently hidden |
| 6 | Status strip + mode badge | Makes demo/live unmissable before live ever exists |
| 7 | Single accent + semantic palette | Removes the second button system |
| 8 | Designed refusal states | Turns the engine's honesty into visible product value |

Legal, pricing and payment surfaces (`/terms`, `/privacy`, `/configurator`,
the payment route) are deliberately excluded from this plan. They are business
decisions and are listed here only so they are not forgotten.

---

# Redesign — what shipped

**Date:** 2026-09-23 · Verified the same way as the audit above: built,
served locally against the real `apex.platform.api.handle()`, and driven in
Chromium at 1440×900 and 390×844.

## The two blockers are closed

| | Before | After |
|---|---|---|
| Unreadable filled controls | **15** across 8 routes | **0** across 18 routes |
| Nav destinations reachable at 390 px | **1 of 8** | **8 of 8** |
| Console errors | 0 | 0 |
| Horizontal overflow, mobile | 0 px | 0 px |

### Finding 1 — contrast

`.a4t a` became `.a4t :where(a)`, which contributes zero specificity, so a
link styled as a control now takes the control's colour. Every `.btn` variant
also declares its own `color`, and `a.btn` reinforces it.

`src/app/contrast.test.ts` makes the regression un-shippable. It does not read
the `.btn` rule — that rule was always correct — it **runs the cascade**:
globals.css is loaded, its custom properties are resolved, the result is given
to jsdom as a stylesheet, the real markup is mounted, and the computed colours
are read back and composited. Reintroducing the old selector fails two tests
with the original 1.00:1 diagnosis. The same file asserts the palette has no
amber, and that every token calling itself an accent sits in one hue band.

### Finding 2 — mobile navigation

A fixed bottom bar carries Dashboard, Rules, Positions and Journal; **More**
opens a drawer listing all eight destinations plus sign-out. Desktop has a
grouped sidebar instead. Measured after: nothing hidden.

## Findings 3 and 4 — the rule is now the product

The builder submits the whole document: sizing, stop, target, trailing stop,
break even, limits, schedule, order type, slippage and expiry, alongside
symbols, timeframe, sides, entry and exit. Defaults are shown as values rather
than applied silently.

Both the builder and the rule page carry a natural-language restatement built
from the condition registry's own parameter order — not a phrasebook, which
would drift from the evaluator the first time a condition was added:

> Buy or sell EURUSD on 1h when Price vs MA(ema, 50, above) AND RSI(14, above,
> 55); exit when RSI(14, below, 45); risk 1% per trade; stop 1.5× ATR; target
> 2R; at most 1 open position.

`Rule terms` on the detail page lists all nineteen fields.

**Fields the engine does not enforce yet are labelled, not hidden.**
`trailingStop`, `breakEven`, `limits.maxDailyTrades` and
`limits.maxExposurePercent` are stored on the document and say so. A non-MARKET
order type, a `maxSlippagePoints` or an `expiresAfterSec` each warn at the
input that execution will **refuse the order** rather than send a different
one — `bridge.SUPPORTED_CONSTRAINTS` is empty and `SUPPORTED_ORDER_TYPES` is
`{MARKET}`.

## Finding 5 — preview

Preview is the main column of the rule page. The outcome is one of three
first-class states — **SETUP** (with the side), **HOLD**, **REJECT** (with its
refusal code) — each with a banner, a conditions-met count, and every condition
listed as met / not met / unknown. Unknown is never folded into "not met", and
a preview containing unknowns says so.

Five tests cover this, and two mutations were run against them: removing the
SETUP state and folding unknown into "not met" each fail a test.

## Finding 6 — one accent

`--primary: #f59e0b` is gone. The shadcn token block is aliased onto the
platform palette, so the primitives in `components/ui` cannot reintroduce a
second accent. `/configurator`'s amber shield is now the platform accent.

## Legacy pages — restyled, not rewritten

`/terms`, `/privacy` and `/configurator` were moved onto the platform's
neutral surfaces so they no longer read as a second brand. **Not one word of
their copy changed**, and their metadata titles were left alone.

They therefore still carry, unchanged and still reachable:

- `/terms` — "Apex Trade Bot is sold as a one-time purchase of software source
  code"; the risk clause is about **cryptocurrency**. Linked from the landing
  page footer.
- `/privacy` — title "Privacy Policy — Apex Trade Bot"; contact address
  `support@aicashsystem.space`, a different brand. Linked from the footer.
- `/configurator` — "Setup Your Bot", "deploy your Apex Trade Bot", "source
  code download link". Reachable by URL.
- `POST /api/create-payment-intent` — `amount: 29700`, `product: "apex-bot"`.
- `components/ui/modern-payment-form.tsx` — `$297`, unused.

These are business and legal decisions and remain outside this work.

## Still open

- Positions and orders show what the broker returns. There is no P&L column
  because the read contract does not carry one.
- No chart. Preview states the bars' source, count and as-of time instead;
  a candle chart is worth doing once there is a connected account to draw.
- `/rules/{id}` shows the whole document but cannot edit it. Editing an active
  rule has to create a new draft version, and that flow is not built.
