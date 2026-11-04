# Marketing idea: "Founder 100"

Status: **idea, owner's, not built.** Nothing here is live, and nothing in the
code reads it. It is written down so it is not lost and so the open questions
are in one place. Owner decides; no queue task should start from this file.

## The idea, as the owner put it

A reward tied to a customer number: the 100th customer who logs in or tries to
buy gets a licence (or something else) free from us, while access stays on sale
to everyone else. Possibly a bonus for the 100th licence as well.

The psychology: people buy sooner when a visible number is moving and one of the
places is a prize. The free place makes the paid ones feel like entries into
something, not just a price.

## Recommended shape (what I would build first)

**Count paid Founder licences, not logins.**
Logins and "tried to buy" are free to fake: ten throwaway emails reach the
milestone. A completed, paid, non-refunded Founder purchase cannot be faked
cheaply. So:

| Milestone | Reward | Cost to us |
|---|---|---|
| Founder #100 (paid) | Their Founder licence is refunded in full, announced as "free" | one licence, about 1% of the first 100 sales |
| Optional: Founder #50 | A thank-you that is not money (name on a public "first founders" list, if they opt in) | none |
| Demo side: 100th verified signup | A small non-cash perk (see below) | negligible |

The demo-side perk lets the owner keep the "100th person who logs in" idea
without handing a real-money licence to whoever games it. It must be something
that is free to give and has no cash value, e.g. an early-access badge, or the
first look at a new feature. It must not be the Founder licence.

**Show a real counter.** "37 of 100 Founder places taken", read from the server
(count of paid licences), never typed into the page and never rounded up. The
page already refuses invented discounts and countdowns (`pricing-section.test`
asserts it); a counter is allowed only if it is the real number. A fake
"only 3 left" is a lie to a buyer and would break the same rule.

**Say the rule out loud.** The reverse-psychology effect works when the rule is
public: "Founder #100 gets their licence refunded." Hiding it, or deciding the
winner after the fact, turns a promotion into something that looks like a trick.

## What has to be true before it can start

1. **Checkout is open.** Today the Founder plan shows "Not on sale yet" and live
   execution is off. A "buy and win" scheme cannot run until a licence can be
   bought. Until then it is just a counter at zero.
2. **There is a legal entity and a published rule text.** The owner has decided
   to start without a company and without VAT, with legal text deferred. A prize
   or refund promotion needs written rules (who qualifies, how the number is
   counted, what happens to a refunded or charged-back purchase, when it ends).
   Ask a lawyer before the first sale; this file is not legal advice.
3. **A definition of "the 100th".** Proposed: the 100th Founder purchase that
   is paid and still not refunded 14 days after payment, in the order Stripe
   confirms them. If an earlier purchase is refunded, the count does not move
   backwards; the 100th place goes to whoever reaches it.
4. **Anti-abuse.** One licence per person; the purchase email must be a verified
   account email; chargebacks cancel the reward.

## Open questions for the owner

1. Is the reward the Founder licence itself (refund), or something else
   ("something free from our side")?
2. Do you want the 100th to be a *paid* purchase (recommended), or do you still
   want a login-based prize, accepting that it can be gamed?
3. A bonus for the 100th licence: money back, extra time on a future product, or
   a non-cash mention?
4. Do you want a public counter on the pricing card, and where?
5. When does it end if the 100 is never reached?

## If it is built later (sketch, not a plan)

- `GET billing/offer` already carries the price and whether checkout is open. A
  `founderPlaces: { taken, total }` field would carry the counter, computed on
  the server from paid licences, and the pricing card would render only what the
  server sends.
- The reward is applied by the owner from the payment dashboard, not by code,
  until there is a reason to automate it. Money moving automatically is outside
  what a queue task may do (`docs/ORCHESTRATOR_PROTOCOL.md`).
- No change to `live_gate`, to the live flags, or to the licence rules.

Related: `docs/COMMERCIAL_LAUNCH_PLAN.md`, `docs/OWNER_ACTIONS.md`.
