---
name: static-landing-deploy
description: Design and deploy a static landing page or affiliate/referral page (Render static site or Netlify). Use when the user asks for a marketing page, affiliate landing page, referral link page, or to publish a static site without touching the main API/web services.
---

# Static landing / affiliate page

Adapted from the OpenMausBot `publish-to-netlify` skill (Apache-2.0): publish only when asked, never publish secrets, show the page first. Rewritten for Apex4Traders, which already ships the product on Render. Prefer a **new Render static site** over editing the production web service.

## Apex safety (mandatory)

- Never edit `.github/workflows`, the production `render.yaml`, `live_gate`, `test_platform_live_invariants.py`, or `server.js`.
- Do not add this landing page to the existing API or web service unless the user explicitly approves a scoped change — and even then, show a mockup first and still do not edit `render.yaml` yourself unless they named that file and approved the exact change.
- Never publish secrets, `.env` files, private customer data, or source maps that leak keys.
- Marketing copy: no profit, income, win-rate, or "make money" claims; no fake discounts or "was" prices; do not mention Telegram. "MT4/MT5 coming soon" only if that feature is mentioned. Include a short risk/demo disclaimer on product pages.
- Licence price is $497. Affiliate share is 30% (~$149) when describing the partner program. Do not invent other prices or discounts.
- Do not collect passwords or broker credentials on a marketing page.
- Deploy only when the user asks. Build and preview first.

## Workflow

1. **Scope.** Confirm it is a static page (landing, affiliate, waitlist, link-in-bio). If they need the signed-in app, that is not this skill.
2. **Mockup.** Write the page in a **standalone folder** (for example `apex-affiliate-page/`), not inside protected app paths. Show a preview (open `index.html` locally or serve the publish directory). Wait for approval on look and copy before deploy.
3. **Build.** Semantic HTML, one accent, readable on a phone. Real copy. Affiliate pages get a personal referral query param (for example `?ref=aditya`) and explain tracking; they do not promise a working link until the tracking page exists.
4. **Publish directory only.** Deploy the output folder (`dist/` or the site root), never the whole monorepo, never `.env`.
5. **Host.** Prefer Render Static Site. Netlify is fine if the user already uses it or asks for it. Do not sign up or spend money for them.

## Render static site (preferred)

The user creates (or approves) a **new** Static Site service in the Render dashboard, pointed at the standalone folder or a separate repo:

- Build command: e.g. `npm run build` or empty if the folder is already static.
- Publish directory: e.g. `dist` or `.`
- Environment variables: only public ones, set in the dashboard, never in git.

You may hand them a snippet like `render-static-site.example.yaml` in this skill folder as a *reference*. Do not merge it into the production `render.yaml`.

After they connect the service, a typical CLI check (if they already use the Render CLI and are logged in) is to confirm the service is live and the URL returns 200. Do not change other services.

SPA note: if the page uses client-side routes, they need a rewrite of `/*` → `/index.html`. Document it; do not silently alter production redirects.

## Netlify (alternative)

Use the Netlify CLI on the publish directory, with the token read from the environment, never typed into a file:

```sh
# Token stays in the environment. Never echo it or write it to the repo.
npx --yes netlify-cli deploy --prod --dir <publish-folder> --json
```

First deploy can be a draft (`deploy` without `--prod`) so the user can open a preview URL. Reuse an existing site id if one is already configured. Do not create a second site for the same page.

Need a form or a tiny function? Read current Netlify docs first, and say so if it may cost money. Still no secrets in published files.

## Before you call it done

- Open the URL, mobile width and desktop.
- Recheck copy against the marketing rules above.
- Tell the user the exact URL, what was deployed, and that the link is public.
