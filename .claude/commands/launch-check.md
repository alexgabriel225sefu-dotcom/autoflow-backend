---
description: Pre-launch readiness check for Apex4Traders (launch 10 November). Read-only; reports what is done and what is missing.
---

Run a read-only launch readiness check and answer the owner in Romanian: a table
of item, status (gata / lipseste / nu am putut citi) and who acts (Claude / owner).
Never change env vars, flip live or checkout flags, deploy or merge while doing it.
Do not guess: if something cannot be read, say so.

Check, in this order:

1. **Build and deploys** — CI green on the head of `claude/apex4traders-platform-v1`;
   web `srv-das11tfavr4c738irjv0` and API `srv-das11onlk1mc73dtj1fg` live on the
   same commit (Render workspace `tea-d7i5tnaqqhas738sjhf0`); `/healthz` answers.
2. **Errors** — API logs for the last 24h: Traceback, ERROR, KeyError, ForwardWatcher
   (one single-term query each).
3. **Accounts and email** — domain bought and pointed at the web service; a
   `support@` mailbox exists; custom SMTP set in Supabase (mails must not come from
   "Supabase Auth"); Google sign-in either enabled in Supabase or its button hidden.
4. **Payments** — Stripe account activated; webhook configured; checkout flags set
   by the owner; the "I tried the free demo" checkbox text approved by the lawyer.
5. **Legal** — terms, refund and tax texts reviewed by the lawyer and published
   (`A4T_LEGAL_PUBLISH`); contact address filled in the footer and legal pages.
6. **Trial rules** — demo is free for 14 days and then stops for everyone
   (`plans.TRIAL_DAYS`, `entitlement.TRIAL_EXPIRED_MESSAGE`).
7. **Live safety** — `python3 apex-forex-bot/scripts/live_preflight.py <user-id>`
   passes; kill switches and Emergency stop work; XAUUSD SL/TP check (#69) done;
   live flags are still off unless the owner turned them on deliberately.
8. **Marketing** — videos ready; Meta ad account separate from the personal one;
   ad copy carries the risk warning and no profit promise.

End with the three most important missing items and the date count to 10 November.
