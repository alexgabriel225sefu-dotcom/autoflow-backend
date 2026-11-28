---
name: frontend-conventions
description: Apply frontend conventions when adding or changing UI — components, styles, copy, routes, hooks, API calls from the client, loading and error states, or onboarding. Use when the user asks to build, restyle, or fix a screen in the web app.
---

# Frontend conventions

Generic UI rules inspired by OpenHands frontend-development practice (MIT, Copyright © 2025 OpenHands contributors). Rewritten for a typical React/TypeScript (or similar) web app. Ignore any Canvas/OpenHands-specific file names; follow *this* repo's structure.

## Apex safety (mandatory)

- Never edit `.github/workflows`, `render.yaml`, `live_gate`, or `test_platform_live_invariants.py`.
- Never add a control that enables live trading, places an order, or hides the demo/live distinction.
- Label demo data clearly. Do not show real-looking account numbers, emails, or balances in mocks.
- Marketing or in-app copy: no profit, income, or win-rate claims; no fake discounts; do not mention Telegram. "MT4/MT5 coming soon" only when that feature is in view.
- For any visually large change, show a mockup (screenshot, HTML, or simple frame) and wait for approval before editing many files.
- Never commit secrets or put API keys in frontend code. Public env vars are only the ones this repo already prefixes as public.

## Workflow

1. Read an existing nearby screen and match its patterns: file layout, component library, tokens, typography, spacing, and how it talks to the API.
2. **Plan first** if the work adds a route, changes navigation, or spans more than a couple of components. List files you will touch, then wait if the change is large.
3. Implement the smallest vertical slice: UI + existing API client + loading / empty / error states.
4. Add focused behavioral coverage for the invariant you changed (what the user sees or what gets sent), not a snapshot of the whole page unless the repo already does that.
5. Check the happy path and one failure path (API error, empty list, unauthorized).

## Conventions

- **State has one owner.** Durable state lives in the store, query cache, or URL that already owns it. Do not mirror that store into component state that can drift.
- **Typed clients.** Use the project's API client or hooks. Do not scatter raw `fetch` calls if a client exists. Share types with the backend when the repo already does.
- **Lazy boundaries.** Preserve route-level code splitting. Do not import a heavy leaf through a barrel file if the repo avoids that.
- **Async UI.** Every request has loading, empty, and error UI. Buttons that submit are disabled while pending and say what failed.
- **Copy.** Real words, not lorem. Short. Same voice as the rest of the product.
- **Access and layout.** Visible focus, labels on inputs, contrast at least 4.5:1. Must work at a narrow width without sideways page scroll. Prefer the typography and spacing scale already in the design tokens.
- **Do not** invent a new design system, add a UI library, or restyle the whole app unless the user asked.
- **i18n.** If the app already localizes strings, add new copy the same way. Do not hard-code a second language system.

## Demo vs live

The UI may explain risk limits and journaled decisions. It must never imply a trade was profitable, recommend a market, or silently switch a user to live execution.
