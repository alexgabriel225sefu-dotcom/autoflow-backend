# Apex4Traders — deployment readiness

What exists on the hosting account today, what has to exist before this
platform can serve anyone, and every environment variable it needs — as names
and placeholders only.

**Assessed at:** `e057ffb16` + this commit, against the live Render account
on 2026-09-25.

**No deployment was created or changed.** Creating a service is an owner
decision with a cost attached, and this document exists so that decision can
be made from facts rather than from a guess.

---

## 1. The finding that matters most

**There is no Render service for this platform.** Not a misconfigured one —
none.

The account holds three services, and all three deploy branch
`claude/arcads-external-api-gExX7`:

| Service | Root dir | Start command | What it is |
|---|---|---|---|
| `autoflow-backend-2` | `apex-forex-bot` | `python main.py` | The **legacy Telegram forex bot**. Live, auto-deploys on commit. |
| `autoflow-backend-1` | `ruflo-mcp` | `python server.py` | The MCP server. Live, auto-deploys. |
| `aicashsystem` | *(repo root)* | `node server.js` | The old sales site. **Suspended** by the owner. |

Consequences, stated plainly:

1. **Nothing deploys `claude/apex4traders-platform-v1`.** Every commit in the
   platform's history — including the phases E–J work — is unreachable from
   any URL.
2. **Nothing deploys `web/` at all.** There is no service whose root
   directory is the Next.js client, so the front end has never been built or
   served by the hosting account.
3. `autoflow-backend-2` runs `apex-forex-bot/main.py`, which starts the
   Telegram bot. The platform API is mounted *inside* that process
   (`apex/bot.py` → `/api/v1/`), so on the deploy branch the platform API is
   reachable at that service's URL — but from the **bot's** branch, not from
   the platform's.

### What this means for a fix landed on the platform branch

A change committed to `claude/apex4traders-platform-v1` **does not reach
production**. This is not hypothetical: the Fernet-token masking added to
`apex/redact.py` (commit `b95dff0e6`) protects the legacy bot's logs too, and
it is not live, because it is on the wrong branch for the service that runs
that bot.

That is a decision for the owner — either the platform gets its own services,
or the platform branch is merged into the deploy branch after review. Both are
outside what may be done without approval.

## 2. What a platform deployment needs

Two services, because the two halves have different runtimes and different
secrets.

### Service 1 — platform API (Python)

| | |
|---|---|
| Root directory | `apex-forex-bot` |
| Build | `pip install -r requirements.txt` |
| Start | `python main.py` |
| Health check path | `/healthz` |
| Region | Must match the Redis/Upstash region |

`/healthz` is the correct probe target and `/readyz` is **not**: readiness
touches dependencies, and pointing a restart probe at it turns a backend
degradation into every container restarting at once. `/readyz` is for the
traffic gate. See `docs/PRODUCTION_RUNBOOK.md` §4.

### Service 2 — web client (Node)

| | |
|---|---|
| Root directory | `web` |
| Build | `npm ci && npm run build` |
| Start | `npm run start` |
| Health check path | `/` |

`npm ci` rather than `npm install`: the lockfile is the reviewed dependency
set, and `install` may resolve something else.

**The repository root has its own `package.json` and `package-lock.json`** for
the legacy Express site. Turbopack detects a workspace root by looking for a
lockfile and walking upwards, so it would infer the repository root and widen
module resolution to include the other product. `web/next.config.ts` now names
`turbopack.root` explicitly; `src/lib/deps.test.ts` asserts it stays named.

## 3. Environment variables

Names and placeholders only. Every value is the owner's to supply, and none
has a default in code — see `docs/PRODUCTION_RUNBOOK.md` §1 for what each one
does and `apex/platform/health.py` for what `/readyz` refuses without.

### Platform API

```
APP_ENV=production
PRODUCT=forex
TOKEN_ENCRYPTION_KEY=<fernet-key>
SUPABASE_URL=<https://PROJECT.supabase.co>
SUPABASE_ANON_KEY=<anon-key>
CTRADER_CLIENT_ID=<client-id>
CTRADER_CLIENT_SECRET=<client-secret>
CTRADER_REDIRECT_URI=<https://DOMAIN/api/v1/ctrader/callback>
REDIS_URL=<redis://...>
# or, for Upstash:
# UPSTASH_REDIS_REST_URL=<https://...>
# UPSTASH_REDIS_REST_TOKEN=<token>
```

Optional, with defaults in code: `RL_A4T_*_PER_MIN`, `RATE_LIMIT_STORE`,
`A4T_PLAN`, `A4T_LICENCE_DAYS`.

### Web client

```
NEXT_PUBLIC_SUPABASE_URL=<https://PROJECT.supabase.co>
NEXT_PUBLIC_SUPABASE_ANON_KEY=<anon-key>
NEXT_PUBLIC_API_BASE_URL=<https://API-DOMAIN>   # empty means same origin
```

### Must NOT be set

```
LIVE_TRADING_ENABLED           # no execution path exists behind it
APEX_ALLOW_LIVE_ACCOUNTS       # would let a live account be selected
ALLOW_LOCAL_BACKEND_DEV        # makes a per-container store acceptable
ALLOW_PLAINTEXT_DEV_STORAGE    # stores broker tokens unencrypted
A4T_CHECKOUT_ENABLED           # no approved price exists
```

`/readyz` **fails** in production if any of the first four is set, and
`entitlement.live_execution_enabled()` returns `False` unconditionally, so the
first one cannot enable anything even if it is set. Both are tested.

### Never on the web service

Anything prefixed `NEXT_PUBLIC_` is compiled into the browser bundle. So
`STRIPE_SECRET_KEY`, `SUPABASE_SERVICE_KEY`, `TOKEN_ENCRYPTION_KEY`,
`CTRADER_CLIENT_SECRET` and the Upstash token must never appear on the web
service at all, prefixed or not — the web client has no code path that needs
any of them.

## 4. Verified by reading the account

| Check | Result |
|---|---|
| Services deploying the platform branch | **none** |
| Services deploying `web/` | **none** |
| Auto-deploy on the bot's service | on, trigger `commit` |
| Region of the two live services | `oregon` |
| Plan | `starter` on both live services |
| IP allow list | `0.0.0.0/0` (everywhere) on both |
| Health check path configured | **empty on all three services** |
| Suspended | `aicashsystem`, by the owner |

**Health check path is empty on every service**, including the live bot. The
bot's own plain-text `/health` exists and answers, but nothing is configured
to probe it, so Render has no signal to restart on and a hung process stays in
rotation. Fixing that on the bot's service is a change to the **other**
product's deployment and is left to the owner.

## 5. What could not be verified, and why

| Item | Why not |
|---|---|
| Environment variable **values** | Never read. The write tool is deliberately built so existing values are not pulled into an agent's context, and reading them would put secrets in a transcript. Only names are checked, against the code. |
| Supabase project (**X3**) | No project reachable from here; the local harness stands in for GoTrue. |
| Redis / Upstash (**X2**) | Not provisioned. Locally the store runs in `ALLOW_LOCAL_BACKEND_DEV` mode, which production must not use. |
| Registered OAuth redirect URI (**X4**) | Set in the cTrader portal, which this session cannot see. cTrader compares byte for byte. |
| HTTPS and domain (**X6**) | No platform service exists to attach one to. |
| Monitoring (**X7**) | Not provisioned. `/healthz` and `/readyz` exist and are tested; nothing scrapes them. |
| `/readyz` answering from a real instance | Requires item 1 of §2. |

None of these is code that is missing. Each is infrastructure or a credential.

## 6. Dependency audit, 2026-09-25

`npm audit` in `web/` reported **7 vulnerabilities: 1 critical, 5 high, 1
moderate**, and the critical one was in the framework itself.

| Advisory | Severity | Why it mattered here |
|---|---|---|
| GHSA-p293-qw3h-jr36 | **critical** | Unauthenticated RCE, path traversal, Windows-hosted servers |
| GHSA-2xp9-vwfh-vxw4 | **critical** | Unauthenticated RCE in the Image Optimization API via AVIF |
| GHSA-6gpp-xcg3-4w24 | high | **Middleware / proxy bypass in App Router.** This app enforces authentication in middleware, so here it is an authentication bypass, not a generic framework issue |
| GHSA-89xv-2m56-2m9x | high | SSRF in Server Actions on custom servers |
| GHSA-m99w-x7hq-7vfj | high | DoS in Server Actions |
| GHSA-68g3-v927-f742 | moderate | Cache confusion of response bodies between requests |
| brace-expansion, browserslist, js-yaml, baseline-browser-mapping | high / moderate | Build-chain DoS |

Fixed by `next` 16.2.7 → **16.3.6** (not a major bump) plus `npm audit fix`
for the build chain. Result: **0 vulnerabilities**. 175 web tests pass, build
clean, lint 0 errors.

`src/lib/deps.test.ts` pins the floor offline so a later `npm install` cannot
walk back under it, and names the advisories as the reason. `npm audit` itself
needs the network and belongs in release verification, not a unit suite.

### Python dependencies — audited, and blocked by the broker connector

`pip-audit -r requirements.txt` on 2026-09-25 found advisories in four
packages. **None can be raised**, and the reason is structural rather than
neglect:

```
ctrader-open-api==0.9.2  hard-pins  pyOpenSSL==24.1.0
                                    Twisted==24.3.0
                                    protobuf==3.20.1
pyOpenSSL==24.1.0        requires   cryptography<43,>=41.0.5
```

Those are `==` pins inside the connector's own metadata, not our choices. So
`cryptography` cannot go past 42.x while `ctrader-open-api==0.9.2` is in the
tree, and **0.9.2 is the newest release that exists** — 0.9.3 was published and
then yanked by the maintainer, so there is no upgrade path through the registry.

| Package | Installed | Advisories | Fix needs |
|---|---|---|---|
| `cryptography` | 42.0.8 | PYSEC-2026-35, -1284, -2141, -3553, -3554; GHSA-h4gh-qq45-vh27, GHSA-537c-gmf6-5ccf | 43.0.1 → 49.0.0 |
| `protobuf` | 3.20.1 | PYSEC-2026-899, -1805, -1806 | 3.20.2 → 6.33.5 |
| `pyOpenSSL` | 24.1.0 | PYSEC-2026-2268, -2269 | 26.0.0 |
| `Twisted` | 24.3.0 | PYSEC-2024-75, PYSEC-2026-160, -1992 | 24.7.0 → 26.4.0 |

#### CORRECTION to the 2026-09-25 assessment

That assessment said the real exposure was "the TLS session to cTrader" via
pyOpenSSL. **That was wrong**, and the conclusion changes with it.

`apex/brokers/ctrader.py` does not use the SDK's client. It opens its own
socket:

```python
ctx = ssl.create_default_context()      # CERT_REQUIRED, check_hostname=True
raw = socket.create_connection((_HOST[self.env], _PORT), timeout=15)
self._sock = ctx.wrap_socket(raw, server_hostname=_HOST[self.env])
```

That is the **standard library's** TLS against the **system** OpenSSL (3.0.13
here), not the copy bundled in the `cryptography` wheel, and it verifies the
certificate and the hostname. The module docstring says it reuses "only the
protobuf message definitions" from the SDK — load-bearing, not stylistic.

So pyOpenSSL and Twisted are **not on our TLS path at all**. They are pulled in
because `ctrader_open_api/__init__.py` eagerly does `from .client import
Client`, so importing any submodule — even a generated `_pb2` one — drags in
Twisted. Verified by removing both packages: every protobuf import then fails
on `ModuleNotFoundError: twisted`.

#### What each advisory actually reaches

| Package | On a path we execute? | Why |
|---|---|---|
| `cryptography` | Fernet only | One import, `user_store.py`. AES-CBC + HMAC. No TLS, no certificate parsing. |
| `protobuf` | **yes** | We parse broker messages with it. |
| `pyOpenSSL` | **no** | Only the SDK's unused `Client` uses it. |
| `Twisted` | **no** | Same. |

Of cryptography's seven advisories, four are X.509 chain / DNS-constraint
verification and EC public-key loading — code this repository never calls. Three
are bugs in the wheel's bundled OpenSSL, which Fernet does use, for symmetric
encryption with no certificate handling.

protobuf's three are denial-of-service via crafted messages. We parse protobuf
from cTrader over a verified TLS connection, so the "untrusted input" premise is
weak — an attacker would have to be the broker or break verified TLS. It is
still the only category on a path we execute.

#### A separate finding: the SDK's own client does not verify anything

Measured on the installed version. `ctrader_open_api.Client` connects with
`clientFromString(reactor, f"ssl:{host}:{port}")`, and Twisted's bare `ssl:`
string with no trust root produces:

```
trustRoot           = None
verify              = False
OpenSSL verify mode = VERIFY_NONE
```

A client that does not verify its peer accepts any certificate, and this
connection carries a broker access token. **We do not use that class**, which is
why this is a finding about the library rather than an incident. Nothing was
enforcing that we keep not using it, so
`apex-forex-bot/tests/test_broker_tls_posture.py` now does: it asserts our
connector builds a verifying context and passes `server_hostname`, that nothing
weakens verification anywhere in the module, that no module imports or
references the SDK's `Client`, and that every SDK import is a `_pb2` module.
Four mutations against it were killed, including "somebody switches to the
SDK's client".

#### Isolated compatibility test — what can actually be raised

Run in a throwaway venv, exercising exactly what the connector depends on: the
protobuf message classes, a round-trip through `ProtoMessage` framing with the
same length prefix, a trendbars request, a heartbeat, the stdlib TLS context and
a Fernet round-trip.

| Combination | Result |
|---|---|
| Baseline: protobuf 3.20.1, pyOpenSSL 24.1.0, cryptography 42.0.8 | all pass |
| **protobuf 3.20.2** (patch; closes PYSEC-2026-899) | **all pass** |
| + pyOpenSSL 26.0.0 + cryptography 50.0.1 | **BROKEN** — `AttributeError: module 'lib' has no attribute 'GEN_EMAIL'`; pyOpenSSL 26 requires `cryptography<47` |
| + pyOpenSSL 26.0.0 + **cryptography 46.0.7** | all pass, Fernet round-trips, key format unchanged |
| pyOpenSSL and Twisted removed entirely | **BROKEN** — the SDK's `__init__` needs Twisted |

The third row is the reason this was tested rather than applied. A bump to the
newest cryptography, which is what "fix the advisory" reads like, produces an
import error — in the TLS stack of a process that is trading.

`pip check` reports only the connector's `==` pins being violated. Nothing else
breaks.

#### Decision, and it is recorded rather than defaulted

**Recommended minimal change: `protobuf==3.20.1` → `3.20.2`.** One patch
version, tested above, and it closes the only advisory on a code path this
product executes.

**Not applied here.** `requirements.txt` is the live Telegram bot's dependency
file, and changing it alters that bot's next build. This branch is not deployed,
so committing it would be latent rather than immediate — which is worse, not
better, because it would take effect whenever the branches converge, without
anybody deciding to. That is an owner and Codex call.

**Not recommended:** raising pyOpenSSL and cryptography. They are not on a path
we execute, the benefit is hygiene, and the change touches the TLS stack of a
running trading process to fix advisories in code it never reaches.

**The real fix, for later:** the dependency on Twisted and pyOpenSSL exists only
because the SDK's `__init__.py` imports its client eagerly. Vendoring the
generated `_pb2` modules — they are machine-generated protobuf stubs — removes
Twisted, pyOpenSSL and their advisories entirely, and is a small, well-defined
piece of work rather than "replace the connector".

#### Real handshake: NOT verified, and why

`scripts/check_ctrader_tls.py` performs it with no credential: DNS, TCP 5035,
then a handshake with `CERT_REQUIRED` and `check_hostname`, printing the issuer
and the SANs, and closing before any application message.

It **cannot run in the development container.** cTrader's Open API is raw TLS
carrying protobuf on TCP 5035, and this environment permits only HTTPS through
an inspecting proxy. The proxy accepts `CONNECT demo.ctraderapi.com:5035` and
then resets the TLS layer, because it cannot speak a protocol that is not HTTP.
Measured: `ConnectionResetError` during `wrap_socket`, and a plain
`TimeoutError` without the proxy.

DNS resolves, so the host is real. Exit code 2 is reserved for exactly this, so
a network answer is never reported as a TLS one. Run it on the deployment host.

Doing nothing is a decision too, and it should be a recorded one rather than a
default.

## 7. Order of operations, when the owner decides to proceed

1. Owner: provision Supabase (X3), Redis/Upstash (X2).
2. Owner: register the production redirect URI in the cTrader portal (X4) and
   supply the client id and secret.
3. Owner: decide whether the platform gets its own Render services or the
   branch is merged after review (§1).
4. Engineering: create the two services from §2 with the variables from §3,
   on a **non-public** URL.
5. Together: confirm `GET /readyz` answers 200 with `"status": "ok"`.
6. Together: work through `docs/CTRADER_DEMO_SMOKE_TEST.md` on a real demo
   account — this is blocker **X1** and it is what the release verdict turns
   on.
7. Re-assess `docs/RELEASE_READINESS.md`.

Steps 1–3 are the critical path and none of them is engineering work.
