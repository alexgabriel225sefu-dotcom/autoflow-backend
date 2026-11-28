---
name: admin-metrics-dashboard
description: Build an internal admin or metrics dashboard (KPI tiles, charts, a detail table) from aggregated product data such as licence sales, affiliate referrals, or demo signups. Use when the user asks for a dashboard, KPI page, sales/metrics view, or an internal admin chart.
---

# Admin / metrics dashboard

Design rules adapted from the OpenMausBot `data-dashboards` skill (Apache-2.0). This version is for a **local or internal** HTML/JS page or an authenticated admin route in the app. It does not use OpenMausBot page tools.

## Apex safety (mandatory)

- Never edit `.github/workflows`, `render.yaml`, `live_gate`, or `test_platform_live_invariants.py`.
- **Aggregate first.** Ship one row per day and dimension, not raw events or customer lists.
- Never put PII, emails, card data, broker account IDs, API keys, or individual order payloads on the page. A published or deployed dashboard is visible to anyone who can open it.
- Read-only queries. Do not use a service-role key in frontend code. Prefer a pre-exported CSV/Parquet or an existing authenticated admin API.
- Show a mockup and the query/export plan before you point anything at production Supabase. Wait for approval if you need a new backend route.
- Do not chart trading P&L, win rates, or "income" in a way that could be reused as a marketing claim. This is an internal ops view.
- Never commit secrets. Sample files must be clearly labeled sample data.

## When to use a standalone page vs an app route

| The user wants | Build |
|---|---|
| A quick look at a CSV they already have | Standalone page from `template.html` in this skill folder |
| A lasting admin view inside the product | An authenticated admin route, matching existing app UI, still using the design rules below |
| A public marketing page | Stop. Use `static-landing-deploy` instead, with no private metrics |

## Standalone page

1. Copy `template.html` from this skill folder to a working directory as `index.html`.
2. Put aggregated data beside it as `data.csv` (or embed a small CSV in the `embedded-data` script tag for a single-file preview).
3. Edit `CONFIG`, `QUERIES` / column names, KPI labels, and chart titles. Keep pinned CDN versions (no `@latest`).
4. Open locally (`python3 -m http.server` in that folder). Check light numbers against a direct query.
5. Do not deploy unless the user asked, and only after you have stripped anything sensitive.

Suggested Apex metrics (aggregates only): licences sold, refunds, affiliate referrals and commission owed, demo signups, activation (demo started), Stripe fulfillment failures (counts, not payloads).

## Data

- Dates as `YYYY-MM-DD`. Cast sums and counts to ordinary numbers.
- Keep the file small (a few MB at most; prefer under 1 MB).
- Filter values go into queries only through safe escaping or bound parameters, never string-pasted raw.
- Check one or two KPI numbers against the source before handing the page over.

## Design

- **Layout:** title + one or two filters; 3–5 KPI tiles; one full-width main chart; 1–2 supporting charts; a detail table; a source line (where the data came from, the date range, when it was refreshed).
- **One question per chart.** The heading is the question; a short note under it is the answer, computed from the data.
- Bars for category comparison (horizontal if labels are long); lines for change over time; a single number is a KPI tile, not a chart. No 3D, no dual y-axes, no pies with more than 3 slices.
- Bars start at zero. Do not crop an axis to dramatize a change.
- Label values at bar tips or line ends. One accent color for what matters, muted for the rest. Green/red mean good/bad only when paired with words or arrows, never color alone.
- Format numbers with `Intl` (compact on KPIs and axes, full in tables).
- Works at 360 px wide: stack columns, no sideways page scroll (a wide table may scroll inside its own box).
- Loading and error states. Each chart has an `aria-label` and a data table (tooltips are extra, not the only place a number appears).

## Before you hand it over

Look at it wide and narrow. Confirm it is obviously internal or sample data. Say how the export stays up to date, if at all.
