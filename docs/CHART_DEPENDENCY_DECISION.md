# Chart dependency — the decision and how it was reached

**Current decision (revisited 2026-10-22): `lightweight-charts@5.2.1`, pinned
exactly.** The first decision, below, was "no charting dependency"; it is kept
as written because its reasoning is what the revisit answers.

## Why it was revisited

The first decision named its own exit: *"The reason to revisit is streaming:
live updating bars, multiple panes, or tens of thousands of candles. At that
point `lightweight-charts` is the right answer."* The brief changed to ask for
exactly that: a chart that updates its last bar in place every 5 seconds,
overlays, and an RSI in a pane of its own. `series.update`, panes and price
lines are the library's real strengths, and the hand-built SVG would have had
to re-create all three.

## What was re-checked on the version actually installed (5.2.1)

| Claim | Result |
|---|---|
| Licence | Apache-2.0 (`npm view lightweight-charts@5.2.1 license`) |
| Published | 2026-08-12, ten weeks before the pin |
| Network in the production bundle | `fetch(`, `XMLHttpRequest`, `sendBeacon`, `WebSocket`, `EventSource`, `importScripts`: **0 occurrences** |
| Remote image or script loaded | None. The one `new Image` is the optional image-watermark feature, which this app does not use. The attribution logo is an inline SVG link. |
| Transitive dependency | `fancy-canvas@2.1.0` (the library's own helper; the only package added besides it) |
| Shipped, gzipped | 60,245 B for the chunk, loaded only by `/dashboard` and `/rules/[id]` |
| Imports in Node (prerender) | Yes: `next build` prerenders both routes with it imported |

## How each reason against it was answered

1. **The NOTICE file is not in the npm package.** *Still true.* The 5.2.1
   tarball has ten files and no NOTICE. Nothing has been written from memory
   to stand in for it. What is done: the library's own `attributionLogo` is
   left on (its README names that as satisfying the link requirement, and a
   test pins it on), and the chart carries a visible text link to
   tradingview.com. **The NOTICE text itself is not reproduced and remains an
   item for the owner**; it has to come from TradingView's repository at the
   `v5.2.1` tag or from TradingView, not from this codebase.
2. **It lengthens the legal launch checklist.** *Accepted.* The owner has to
   confirm the attribution above before launch. This is the same kind of item
   as L1–L10 in `LEGAL_LAUNCH_BLOCKERS.md` and has the same consequence if
   left: the site would be using third-party code on terms nobody confirmed.
3. **What is needed is small.** *No longer true*; see above.

**A disclosure to be aware of:** the attribution logo is a link to
`tradingview.com` that, **when clicked**, carries `utm_source=<host><path>` of
the page it was clicked on. On the rule page that path includes the rule's id.
Nothing is sent until someone clicks. If that is not acceptable, set
`attributionLogo: false` in `price-chart.tsx` and rely on the text link, which
carries no path; the owner decides whether that still meets the licence.

## Indicators: the second reason, and what changed

The first decision also refused indicators, because "an EMA computed in the
browser would be a second implementation of something the evaluator already
computes, and the two would disagree at the edges." That risk is real and is
**not removed** by this revisit. It is accepted for SMA, EMA and RSI(14) on
these terms:

- every indicator is labelled **computed**, on the chart legend and beside the
  control, with the sentence "Computed in your browser from the bars shown.
  These are not the rule engine's values.";
- the functions are pure and live in `indicators.ts`, with their seeding
  conventions written at the top, and are tested against numbers worked out by
  hand;
- nothing is claimed to match the rule engine or another platform. EMA and RSI
  both have several seeding conventions in use; these are SMA-seeded EMA and
  Wilder RSI.

If a verdict on screen and a line on the chart ever disagree, the verdict is
the one that is right. If that proves confusing, the better fix is still the
one the first decision named: have the evaluator return the series it used and
draw that.

## What "live" means, and does not

The page asks for the bars every 5 seconds, not at all while the tab is
hidden. The platform serves them from the broker through a shared candle cache
(`apex/candle_cache.py`, 60 s by default, capped at a quarter of the bar
period), and the response carries no fetched-at time. So the newest bar can
trail the broker by up to the cache lifetime and the browser cannot tell. The
chart says when **this browser** last got an answer ("Last synced"), marks it
**stale** after 30 seconds or on a failed read, and states the cache. It does
not say "real time", and it must not be changed to.

The candles route is limited to 30 requests a minute per user
(`RL_A4T_CANDLES_PER_MIN`). One chart at 5 seconds uses 12. Two tabs open on a
chart use 24; a third would be refused.

---

# The original decision (superseded, kept for the reasoning)

**Decision: no charting dependency. The chart is drawn as inline SVG.**

This was not a preference. Two candidates were installed and measured, and the
measurements are below.

## What was required of a candidate

1. A permissive licence with no obligation the owner would have to satisfy on
   the live site.
2. A bundle cost proportionate to one read-only view.
3. Works with server rendering — nothing touching `window` at module scope.
4. Sends nothing anywhere. This view renders a client's broker data.
5. No vendor logo or trademark on a product page, unless the licence makes it
   unavoidable.

## What was measured

| | `lightweight-charts@5.2.1` | `recharts@3.10.1` | inline SVG |
|---|---|---|---|
| Licence | Apache-2.0 | MIT | — |
| Unpacked | 3.1 MB | 7.5 MB | 0 |
| Shipped, gzipped | **60.6 KB** | larger | **0** |
| `fetch` / `XHR` / `WebSocket` / `sendBeacon` in the bundle | **0 occurrences** | not measured | 0 |
| Imports cleanly in Node with no DOM | yes | — | n/a |
| Vendor trademark in the bundle | **yes** — `attributionLogo`, `tradingview.com` | no | no |

`lightweight-charts` is a good library. It is permissively licensed, it is
compact, and it makes no network calls — that was verified against the shipped
production bundle, not taken from the README.

## Why it was still not chosen

Its README states the obligation plainly:

> You shall add the "attribution notice" from the NOTICE file and a link to
> <https://www.tradingview.com/> to the page of your website or mobile
> application that is available to your users.
>
> You can use the `attributionLogo` chart option for displaying an appropriate
> link ... which will satisfy the link requirement.

So the logo is **one way** to satisfy the requirement, not the requirement
itself — the brief's "no TradingView logo unless the legal integration
requires it" could have been honoured by turning `attributionLogo` off and
placing the notice in text.

Three things decided against it anyway:

1. **The NOTICE file is not in the npm package.** Only `LICENSE` and
   `README.md` ship. Satisfying the obligation correctly means reproducing
   attribution text taken from somewhere other than the artefact being
   installed. Writing an attribution notice from memory is exactly the kind of
   thing this product does not do.
2. **It adds a legal obligation to a launch checklist that already has legal
   blockers.** `docs/LEGAL_LAUNCH_BLOCKERS.md` exists because the owner has to
   confirm entity, jurisdiction, contact and refunds. Adding "and confirm a
   third-party attribution notice is correctly reproduced" makes that list
   longer for a view that renders about two hundred rectangles.
3. **What is actually needed is small.** Read-only candlesticks, an OHLC
   readout, markers for an evaluated bar, and four states for when there is
   nothing to draw. None of that needs a charting engine, and none of the
   library's real strengths — streaming updates, multiple panes, a large
   series API — is used by this view.

`recharts` was ruled out on size and on fit: it is a general charting library
for dashboards, and a financial candlestick is not one of its primitives.

## What was built instead

`web/src/components/chart/candles.tsx`. Inline SVG, no dependency, no network
of its own. It receives candles that the page fetched from
`GET /api/v1/accounts/{ctid}/candles` and draws them.

Deliberate limits, stated rather than worked around:

- **No volume.** `broker_read._shape()` keeps `open`, `high`, `low`, `close`
  and `time` and nothing else, so the platform has no volume to draw. The
  chart says so instead of drawing a flat row of bars that would look like
  data.
- **No indicators.** An EMA computed in the browser would be a second
  implementation of something the evaluator already computes, and the two
  would disagree at the edges — on the first bars, on a gap, on a different
  rounding. A chart that disagrees with the verdict beside it is worse than a
  chart without a line. If indicator overlays are wanted, the evaluator should
  return the series it used, and the chart should draw that.

## If this is revisited

The reason to revisit is streaming: live updating bars, multiple panes, or
tens of thousands of candles. At that point `lightweight-charts` is the right
answer, the obligation is a paragraph of text and a link, and this document
should be updated rather than deleted.
