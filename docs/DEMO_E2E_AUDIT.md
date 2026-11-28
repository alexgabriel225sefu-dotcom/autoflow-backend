# Demo client journey — end-to-end audit

Session on `cursor/demo-e2e-audit-37c1`, code tip `f17921fc9`.

This is a client-code audit. **Real SMTP was not run. Real cTrader OAuth was not run. No browser was opened at 390×844 or 1440×900, and there are no screenshots.** A step is `works` only when existing or new automated tests cover it and it does not depend on a live integration. A live integration that was not exercised is `broken-needs-owner` or unverified, not `works`.

| Step | Status | Evidence |
|---|---|---|
| Sign up + email confirmation | fixed (client); live mail **broken-needs-owner** | `web/src/app/signup/page.tsx` sends the visitor to `/dashboard` when `signUp` already returns a session, and otherwise keeps “Check your email” without saying whether the address exists (`signup/page.test.tsx`). `/auth/callback` exchanges `?code=` via `exchangeCodeForSession`, shows `error` / `error_description`, and only then routes (`callback/page.test.tsx`). `/auth/confirm` no longer calls a signed-out visitor “not confirmed yet” (`confirm/page.test.tsx`). No confirmation email was sent. The owner must configure Supabase SMTP and walk a real inbox. |
| Onboarding / unverified gate | fixed (client); live mail unverified | When `me` says `emailVerified === false`, the shell shows that connecting cTrader and activating a rule are refused, with a link to `/settings` (`shell.tsx`, `shell.test.tsx`). The notice is absent while loading and when the field is missing. Settings can call `auth.resend({ type: 'signup', ... emailRedirectTo: origin + '/auth/callback' })` (`settings/page.test.tsx`). The resend was not delivered to a real inbox. |
| Connect cTrader OAuth | fixed (client cancel + cache); real OAuth **broken-needs-owner** | Cancel calls `remember(null)`, so `sessionStorage` key `a4t.ctrader.pending` is removed and step 1 (“Connect cTrader”) is offered again (`connect/page.test.tsx`). A successful `complete()` reloads every broker view. No browser was sent through cTrader. The owner must complete a demo OAuth round on the real broker. |
| Accounts honest states | fixed | A failed `ctrader/status` on Settings is an `ErrorNotice` with retry, not a spinner (`settings/page.test.tsx`). An empty connected list says “Connected, but cTrader returned no accounts.” (`accounts/page.tsx`). Not checked against a live cTrader account list. |
| Create a rule with named conditions and an automation level | works (existing tests) | Rule form and summary were not changed. `npm test` ran the existing rules/new and rule-form suites. No new rule was saved in a browser. |
| Preview | unverified in a browser | Existing preview tests ran as part of `npm test`. This session did not open the preview screen or a broker chart. |
| Start / pause / stop | works (existing tests) | Dashboard control tests passed, including the stop sentence. No loop was started against a broker. |
| Approvals | works (existing tests) | Pending-approval coverage remains in the web suite. No approval was accepted in a browser. |
| Journal | works (existing tests) | Journal page tests passed. No live journal row was read from a broker session. |
| Notifications | fixed | A failed mark-one or mark-all sets an error and does not reload (`notifications/page.test.tsx`). |
| Emergency stop | works (existing tests) | Dashboard tests still open “Stop only” and “Stop and close positions” on a demo selection and hide the control on a live selection. The control was not pressed against a broker. |
| Settings | fixed | Broker error, confirmation resend, and failed sign-out are covered in `settings/page.test.tsx`. |
| Sign out | fixed | Shell and settings stay put and show the message when `signOut` returns an error (`shell.test.tsx`, `settings/page.test.tsx`). A successful sign-out still goes to `/login`. |
| Mobile 390 and desktop 1440 | fixed (CSS rule only); viewports **unverified** | Under `max-width: 720px`, `.seg` wraps and `.tbl-kv td` can break long ids (`globals.css`, asserted in `shell.test.tsx`). Desktop `.seg` stays `inline-flex`. **Pages were not rendered at 390×844 or 1440×900. No screenshots.** |

## What the owner still has to do

1. Send a real confirmation email (Supabase SMTP) and open the link. The client now exchanges the code; the mail provider was not exercised.
2. Complete a real cTrader **demo** OAuth, select an account, and confirm the status strip, positions, and orders follow that account.
3. Look at the app at 390×844 and 1440×900. The wrap rule is in CSS and in a source test only.
