# Apex4Traders — beta configuration

How to stand up the **private demo beta** and, just as importantly, what the
beta deliberately cannot do.

**Live trading is not implemented.** Nothing in this document enables it, and
no combination of the variables below turns it on. The only supported setting
is off; `/readyz` refuses readiness if anything sets `LIVE_TRADING_ENABLED`,
because the flag would promise an execution path that does not exist.

---

## 1. What the beta is

| | |
|---|---|
| **Who** | Invited testers, on a non-public URL |
| **Broker accounts** | cTrader **demo** accounts only |
| **Money at risk** | None. `automation.start` refuses any account whose mode is not `demo` |
| **Price** | Demo access is free. Checkout is disabled |
| **Paid plan** | Intended later, to unlock live-account automation. Not built, not priced, not sold |

`GET /api/v1/me` carries an `execution` block with the server's own verdict:
the account mode, the entitlement, whether this client may automate, and the
badge to render. The UI renders it rather than recombining a licence state
with an account mode, so there is one decision and not two.

The product copy says the same thing in the same words: *demo accounts are
free; real-money account access will be a paid plan, and live execution is not
enabled in this release.* If the UI and this document ever disagree, one of
them is a bug.

## 2. Environment for a beta deployment

Start from §1 of `docs/PRODUCTION_RUNBOOK.md`, which is the full table. The
beta-specific part is what is **off**:

```
A4T_CHECKOUT_ENABLED        # unset. Checkout answers 503 and the UI says so
A4T_PRICE_MINOR             # unset. There is no approved price
A4T_CURRENCY                # unset
A4T_SKU                     # unset
A4T_STRIPE_WEBHOOK_SECRET   # unset unless a payment test is deliberately being run
LIVE_TRADING_ENABLED        # unset, and must stay unset
```

and what must be **on**, even for a beta with five testers:

```
APP_ENV=production
TOKEN_ENCRYPTION_KEY=<Fernet key>
REDIS_URL or UPSTASH_REDIS_REST_URL + UPSTASH_REDIS_REST_TOKEN
SUPABASE_URL, SUPABASE_ANON_KEY
CTRADER_CLIENT_ID, CTRADER_CLIENT_SECRET, CTRADER_REDIRECT_URI
PRODUCT=forex
```

A beta is a deployment. The development opt-ins
(`ALLOW_LOCAL_BACKEND_DEV`, `ALLOW_PLAINTEXT_DEV_STORAGE`) are for a laptop;
with `APP_ENV=production` set, `/readyz` fails if either is on, and the store
refuses to start if either is needed.

## 3. Verifying the deployment

```
GET /healthz   -> 200 {"ok": true, "status": "ok", "uptimeSec": …}
GET /readyz    -> 200 with "status": "ok"
```

`/readyz` answers **503** with a `failed` list naming each check that refused.
Read the list rather than guessing: every check carries a sentence saying what
is wrong and what it costs.

| Check | Beta expectation |
|---|---|
| `supabase` | `ok` |
| `encryption` | `ok` |
| `shared_store` | `ok` — `degraded` means no Redis, which is not acceptable for a deployment |
| `rate_limit_store` | `ok` — `fail` means counters are per process, so N instances means N times the limit |
| `ctrader_oauth` | `ok` |
| `billing` | `skipped` — correct while checkout is off |
| `dev_flags` | `ok` |
| `live_trading` | `ok`, meaning disabled |

Authenticated operators can read the same checks plus this release's
capabilities at `GET /api/v1/system/status`.

Neither endpoint returns a secret, a key, a token, or the value of any
environment variable. A check names the *variable* when one is missing, which
is what an operator needs, and never its content.
`tests/test_platform_health.py` asserts this against sentinel values in every
state the module can reach.

## 4. Onboarding a beta tester

1. The tester signs up and confirms their e-mail through Supabase.
2. **Nothing else.** Demo access is free and automatic:
   `apex/platform/entitlement.py` treats a client with no licence record as
   `free_demo`, which is enough to build, activate and run a rule on a demo
   account. No manual grant is needed to onboard a tester.
3. The tester connects a cTrader **demo** account through OAuth.
4. They select the demo account. A live account, if their cTrader login has
   one, is rendered disabled and labelled not available.
5. They build, validate, preview and activate a rule, then start automation.

## 5. What a tester must be told, in writing

- This is a demo-only beta. No real money is traded, and there is no path in
  this release by which it could be.
- Their cTrader tokens are held encrypted by the platform and can be removed
  at any time with *Disconnect*. Disconnecting removes our copy; revoking the
  application inside cTrader is a separate action they should also take.
- There is no charge, no card, and no checkout.
- Results from a demo account are not evidence of results on a live one, and
  nothing in the product claims otherwise.

## 6. Known limitations of the beta

| Limitation | Where it is recorded |
|---|---|
| Paid access is defined but sells nothing; `paid_live` unlocks no live path in this release | `apex/platform/entitlement.py` |
| The connected path has never been exercised against a real broker | blocker **X1** in `docs/RELEASE_READINESS.md` |
| An active rule cannot be edited; editing must create a new version | `docs/LAUNCH_QA_REPORT.md` |
| No volume and no indicator overlay on the chart | `docs/LAUNCH_QA_REPORT.md` |
| Several rule fields are recorded but not enforced by the engine | labelled at the input in the rule builder |
| Webhook idempotency is weaker without Redis | `docs/PRODUCTION_RUNBOOK.md` §2 |

## 7. Ending the beta

There is no destructive teardown to perform, and none should be invented.
To stop serving a tester: revoke their licence
(`docs/MANUAL_LICENCE_OPERATIONS.md`). A withdrawal outranks the free tier —
it is the one thing that still blocks demo automation — and it takes effect
on their next authenticated request. Their rules, journal and encrypted broker link remain
until they disconnect or the records are deliberately removed.
