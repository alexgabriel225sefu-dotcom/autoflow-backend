# Chart dependency — the decision and how it was reached

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
