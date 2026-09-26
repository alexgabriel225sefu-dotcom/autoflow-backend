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

#### The protobuf bump is NOT IMPLEMENTABLE — tested 2026-09-26

Codex reviewed handoff #2 and decided: apply `protobuf` 3.20.1 → 3.20.2 as its
own commit. **It cannot be done inside `requirements.txt`, and I should have
known that before recommending it.**

```
$ pip install --dry-run -r requirements.txt
ERROR: Cannot install -r requirements.txt (line 34), ctrader-open-api==0.9.2
       and protobuf==3.20.2 because these package versions have conflicting
       dependencies.
ERROR: ResolutionImpossible
```

`ctrader-open-api==0.9.2` pins `protobuf==3.20.1` — an exact pin in its own
metadata — and the fix for PYSEC-2026-899 is `>=3.20.2`. **No version satisfies
both.** Adding the bump makes `pip install -r requirements.txt` fail, on the
service that runs a trading loop.

It also breaks `pip-audit -r requirements.txt`, which cannot resolve the file any
more — so the change would close one advisory and disable the tool that finds the
next one.

**Why I recommended it anyway.** The isolated venv used `pip install --no-deps`,
which installs a version without consulting the resolver. That proved the code
*works* at 3.20.2, which is a real and useful result, and it says nothing about
whether the combination can be *installed*. I tested the wrong half and reported
the conclusion as if I had tested both.

`tests/test_deploy_config.py` now asserts this collision is absent by name, with
the reason attached, so the same recommendation cannot be made again without
failing a test. Mutation: adding `protobuf==3.20.2` back kills it.

**The change is reverted.** `requirements.txt` is unmodified.

#### So PYSEC-2026-899 stays open, and here is the only way to close it

Not by bumping. The connector's `==` pin has to stop being in the way:

1. **Vendor the generated `_pb2` stubs.** They are machine-generated protobuf
   files; copying them into `apex/brokers/` and dropping `ctrader-open-api`
   removes the pin, and with it Twisted and pyOpenSSL and all five of their
   advisories. This is the recommended route and it is a small, well-defined
   piece of work.
2. **Change the build command** to install the connector with `--no-deps` and
   protobuf separately. Cheaper, but it is a deployment change, it silently
   skips whatever else the connector's metadata asks for, and it puts the
   dependency graph in a build script where nobody reads it.
3. **Accept it.** protobuf's advisories are denial-of-service via crafted
   messages, and we parse protobuf from cTrader over a connection whose
   certificate and hostname we verify — so the "untrusted input" premise
   requires an attacker who is the broker or who has broken verified TLS.

Route 1 is the one that actually ends the problem. Until somebody does it, the
honest status is: **open, understood, and not closeable by a version bump.**

#### Route 1 taken — CLOSED 2026-09-26

Codex chose vendoring. The four generated modules now live under
`apex-forex-bot/apex/ctrader_proto/` with the upstream MIT licence beside them,
`ctrader-open-api` is out of `requirements.txt`, and `protobuf` is pinned
directly. `apex/ctrader_proto/__init__.py` records the source package and
version and the exact commands to refresh the stubs.

Four files, not the three the connector imports:
`OpenApiCommonMessages_pb2` imports `OpenApiCommonModelMessages_pb2`, and
`OpenApiMessages_pb2` imports `OpenApiModelMessages_pb2`. One line changed in
each of two of them — the sibling import was `from ctrader_open_api.messages
import X` and is now `from . import X`, which cannot break under a future
relocation. Everything else, including the serialized descriptors, is
byte-identical to upstream.

**Which protobuf version, and why not 3.20.2.** Codex's instruction was the
safest installable version compatible with the vendored stubs, preferring 3.20.2
if it passed. 3.20.2 passes, and it is not the safest — with the SDK's `==` pin
gone, nothing holds protobuf in the 3.x range at all. Measured with `pip-audit`,
one version at a time, in a clean venv:

| protobuf | Stubs | Advisories still open |
|---|---|---|
| 3.20.2 | pass | PYSEC-2026-1805, PYSEC-2026-1806 |
| 3.20.3 | pass | PYSEC-2026-1805, PYSEC-2026-1806 |
| 4.25.8 | pass | PYSEC-2026-1805 |
| 5.29.5 | pass | PYSEC-2026-1805 |
| **6.33.5** | **pass** | **none** |

So 6.33.5. Stopping at 3.20.2 would have closed one advisory of three and left
the reason for vendoring unresolved. It needs Python >= 3.9; `matplotlib==3.11.1`
in the same file already requires >= 3.11 and installs in production today, so
this raises no floor.

**What the dependency tree looks like now.** `pip install -r requirements.txt`
in a clean venv resolves normally — no `ResolutionImpossible` — and installs
neither `ctrader-open-api`, `pyOpenSSL` nor `Twisted`. All 162 backend test files
pass in that venv with the SDK absent, which is the check that matters: the code
no longer depends on a package the deployment will not have.

`pip-audit` on the resulting tree:

| Package | Before | After |
|---|---|---|
| `protobuf` | 3 advisories | **none** |
| `pyOpenSSL` | 2 advisories | **not installed** |
| `Twisted` | 3 advisories | **not installed** |
| `cryptography` | 7 advisories | 7 advisories — unchanged, see below |
| `requests` | PYSEC-2026-1872, -2275 | unchanged, pre-existing |

**A consequence worth acting on separately: the cryptography ceiling is gone.**
`cryptography` was held below 43 by `pyOpenSSL==24.1.0`, which required
`cryptography<43,>=41.0.5`. pyOpenSSL is no longer in the tree, and nothing
installed now constrains `cryptography` at all — the only remaining mentions are
optional extras that are not installed (`redis[ocsp]`, `curl_cffi[dev]`,
`curl_cffi[test]`). The seven advisories need 43.0.1 through 49.0.0, which was
previously impossible and is now merely untested. **Not done here**, because
Codex's instruction for this commit was explicitly not to raise
pyOpenSSL/cryptography. It is the obvious next dependency task, and it is now
unblocked.

**What enforces this.** `tests/test_broker_tls_posture.py` no longer asks
whether the SDK's client is reached; it asserts that no module under `apex/` or
`scripts/` imports `ctrader_open_api` **at all**, in any spelling — a `_pb2`
import is as much a defect as a `Client` import now, because the package will not
be installed. Both are asserted separately, because one crashes the bot and the
other leaks broker tokens, and a red suite should say which. The vendored files
are themselves checked for SDK references, and the provenance and licence are
asserted to exist. `tests/test_deploy_config.py` now requires `protobuf` to be
pinned directly at major >= 6 and requires `pyOpenSSL`/`Twisted` to be absent,
while keeping the old collision guard for the case where the connector ever
returns.

Mutations, each restored afterwards and the suite re-run green:

| Mutation | Result |
|---|---|
| `from ctrader_open_api import Client` in the connector | **FAILS** both checks — import and client-reach |
| one `_pb2` import pointed back at the SDK | **FAILS** the import check only, as designed |
| `protobuf==3.20.2` | **FAILS** — "at a version with no open advisory against it" |
| `protobuf` pin deleted | **FAILS** two checks — unpinned, and no version |
| vendored `LICENSE` removed | **FAILS** — provenance check |
| one of the four `_pb2` modules deleted | **FAILS** — completeness check |

**Not fixed here, found while verifying:** `tests/test_hardening_final.py`
imports `yaml`, and `PyYAML` is in no requirements file — it was already
undeclared before this change. It passes in the developer container, where the
package happens to be installed, and fails in a clean venv. Test-only, no
production path, reported rather than folded into a mechanical commit.

#### The PyYAML clean-venv failure — CLOSED 2026-09-26

Fixed by removing the dependency, not declaring it. `tests/test_hardening_final.py`
now reads the CI matrix with an indentation-scoped walk into
`jobs -> <job> -> strategy -> matrix -> include`, following the precedent in
`tests/test_platform_blueprint.py`. A regex is not an option: `- name:` also
matches every step, so a whole-file match would report step names as published
images and the invariant would pass while CI built a second bot.

The parser is tested before it is trusted — five inputs it must read (including
a step named like an image, and a second job with its own matrix) and eight it
must refuse, each asserting the exception TYPE. That last part came from a
surviving mutation: checking only "did it raise" let a change that returned
`([], "")` instead of raising `KeyError` pass, because every missing-key case
still tripped the final "no entries" guard. The guard was doing all the work.

#### cryptography 42.0.8 → 50.0.1 — CLOSED 2026-09-26

**This is token encryption at rest, not the broker TLS path.** `cryptography` is
used in exactly one place, `apex/user_store.py`, for Fernet. The cTrader
connection uses stdlib `ssl` against the system OpenSSL and is unaffected by
this pin in either direction.

Unblocked by the vendoring commit: the ceiling was `pyOpenSSL==24.1.0` requiring
`cryptography<43,>=41.0.5`, and pyOpenSSL left the tree with the SDK.

**Which version.** Measured one version at a time in a clean venv, with the
production requirements installed first so the resolver saw the real tree:

| cryptography | Fernet vectors | `pip check` | Advisories still open |
|---|---|---|---|
| 42.0.8 (old pin) | pass | clean | 7 |
| 43.0.1 | pass | clean | 6 |
| 44.0.1 | pass | clean | 6 |
| 46.0.6 | pass | clean | 5 |
| 48.0.1 | pass | clean | 3 |
| 49.0.0 | pass | clean | 1 — PYSEC-2026-3552, fixed in 50.0.0 |
| **50.0.0** | **pass** | **clean** | **none** |
| **50.0.1** | **pass** | **clean** | **none** |

50.0.0 is the floor that clears the last finding; **50.0.1** is the current patch
on that line and was taken, since it clears the same set and 50.0.0 offers
nothing over it. Nothing installed constrains `cryptography` any more — the only
remaining mentions are extras that are not installed (`redis[ocsp]`,
`curl_cffi[dev]`, `curl_cffi[test]`).

Note this supersedes one row of the earlier compatibility matrix. "pyOpenSSL 26 +
cryptography 50 → BROKEN (`AttributeError: module 'lib' has no attribute
'GEN_EMAIL'`)" was a *pyOpenSSL* incompatibility. pyOpenSSL is gone, so
cryptography 50 is testable on its own, and it passes.

**Fernet backwards compatibility, which is the risk that matters.** Broker
ciphertexts live in Redis and are not re-encrypted on deploy. A bump where the
new version encrypts and decrypts perfectly while stored tokens stop opening
would show up as every connected client losing their broker connection at once,
with `decrypt_value` correctly returning `""` rather than handing out
ciphertext — so the logs would say a secret was "treated as absent" and nothing
would say why. Round-tripping on the installed version cannot detect that.

So `tests/test_fernet_compat.py` freezes four ciphertexts **minted under
42.0.8** into the repository and opens them on whatever version is installed:
through raw Fernet, through `user_store.decrypt_value` with the `enc:` prefix,
and through `_decrypt_sensitive` on a whole record. It also asserts a tampered
token is still rejected (a version that decrypted everything would pass every
other check), that `user_store` turns that rejection into absence rather than
returning ciphertext, and that a pre-existing `TOKEN_ENCRYPTION_KEY` still
loads. The vectors are synthetic — a key generated for that file, plaintexts
ending in `SAMPLEONLY`, the synthetic account id `1000000001` — and the file says
so at the top, because they look exactly like the thing nobody should commit.

Run across versions, same frozen vectors: 42.0.8 → 4/4 decrypt, 49.0.0 → 4/4,
50.0.1 → 4/4. Only the advisory-floor assertion distinguishes them, which is what
it is there for.

**Verification.** `pip install -r requirements.txt` in a clean venv, `pip check`
clean, **163/163 backend test files pass in that venv** with neither
ctrader-open-api, pyOpenSSL, Twisted nor PyYAML installed. Mutations: corrupting
one frozen vector fails three checks; making `decrypt_value` return ciphertext
instead of `""` on failure fails four.

**pip-audit on the requirements set is now clean except `requests`:**

| Package | State |
|---|---|
| `cryptography` | **no advisory** (was 7) |
| `protobuf` | **no advisory** (was 3) |
| `pyOpenSSL`, `Twisted` | **not installed** (were 5 between them) |
| `requests` 2.32.3 | PYSEC-2026-1872 (needs 2.32.4), PYSEC-2026-2275 (needs 2.33.0) |
| `setuptools` | build environment only, not in requirements.txt |

`requests` is the next dependency candidate and is out of scope here.

**Observation, not a change:** `ctrader_accounts` is not in
`user_store._SENSITIVE_FIELDS`, so the account list — which contains
`ctidTraderAccountId` values — is stored at rest in plaintext while the tokens
beside it are encrypted. Not touched in a dependency commit; recorded for a
decision.

#### requests 2.32.3 → 2.34.2 — CLOSED 2026-09-26

Also unblocked by the vendoring, which was not noticed at the time:
`ctrader-open-api==0.9.2` pinned `requests==2.32.3` **exactly**, alongside
protobuf, pyOpenSSL and Twisted. So this bump was equally impossible before, and
the vendoring freed three pins, not two.

| requests | Call shapes | `pip check` | Advisories still open |
|---|---|---|---|
| 2.32.3 (old pin) | pass | clean | PYSEC-2026-1872, PYSEC-2026-2275 |
| 2.32.4 | pass | clean | PYSEC-2026-2275 |
| **2.33.0** | **pass** | **clean** | **none** |
| 2.33.1 | pass | clean | none |
| **2.34.2** | **pass** | **clean** | **none** |

- `PYSEC-2026-1872` — `.netrc` credential leak via malicious URLs. Fixed 2.32.4.
- `PYSEC-2026-2275` / CVE-2026-25645 — `requests.utils.extract_zipped_paths`
  uses a predictable temp filename. Fixed 2.33.0. This repository never calls
  `requests.utils`, so it did not affect us in practice.

2.33.0 is the floor that clears both; **2.34.2** was taken as the current
release. Its changes over 2.33 are inline typing (replacing typeshed — no
runtime effect here) plus two runtime *fixes*: non-greedy `no_proxy` matching,
and no longer stripping duplicate leading slashes in paths, the latter complete
only with `urllib3 >= 2.7.0`, and 2.8.0 is what installs. Needs Python >= 3.10;
`matplotlib==3.11.1` already requires >= 3.11.

**How the call paths were exercised.** Every one of the 15 modules that imports
`requests` uses the plain module-level API — no `Session`, no `HTTPAdapter`, no
`verify=`, no `cert=`, no `proxies=`, no custom auth, no streaming — which is
the most stable part of the surface. A probe drove each shape actually used
against a local HTTP server on every candidate version: `get(params=)`,
`get(headers=)`, `post(json=)`, `post(data=)`, `post(data=, files=)`, the
response attributes the code reads (`status_code`, `ok`, `text`, `headers`,
`.json()`), a 503 returning rather than raising, `raise_for_status` raising when
asked, a timeout raising `Timeout`, a refused connection raising
`ConnectionError`, both being `OSError` subclasses as the broker code assumes,
and `Session.verify` defaulting to `True`. Identical on all five versions.

The 18 existing tests around those paths pass, and
`tests/test_ctrader_oauth_http.py` is new — the OAuth token helpers had no
coverage at all, and writing it is what surfaced the credential leak below.

`tests/test_deploy_config.py` now asserts floors for both raised pins, each with
its advisory attached. Mutations: `requests==2.32.3`, `requests==2.32.4` and
`cryptography==49.0.0` each fail one check.

#### A credential leak found while doing it — FIXED 2026-09-26

Not a test artifact, and it is the **application-wide** secret, not one
client's. cTrader's `/apps/token` reads its parameters from the **query
string**, so the URL of every token request contains `client_secret` —  the
credential behind every client's broker connection — plus either the
authorization code or that client's refresh token. `requests` puts the full URL
into the message of the `HTTPError` that `raise_for_status()` produces, and into
its `ConnectionError` and `Timeout` messages. `_token_request` let those escape,
and a failed token refresh is exactly the kind of event that gets logged.
Measured on a 401 before the fix:

```
401 Client Error: Unauthorized for url: .../apps/token?grant_type=
authorization_code&code=<code>&redirect_uri=...&client_id=...&
client_secret=<the application secret>
```

`apex/brokers/ctrader.py` now checks the status by hand, and replaces every
`requests` exception with one naming the class of failure and nothing else — no
URL, and no response body either, since a token endpoint can echo what was
sent. Each raise uses `from None`, because a rewritten message is worth nothing
while the original chains onto the traceback, and the traceback is what a log
captures. `apex/redact.py` masks credential-bearing query parameters as defence
in depth for the next place somebody prints a URL.

Pinned by `tests/test_ctrader_oauth_http.py`, which asserts the absence of the
secret, the code and the refresh token from the message **and the full formatted
traceback**, on HTTP errors and on a refused connection. Six mutations kill it,
including restoring `raise_for_status` (11 checks) and passing requests' own
message through (3 checks, with the leak visible in the output).

#### Dependency state after all four commits

`pip-audit` against `requirements.txt`, in a clean venv:

| Package | Pin | Advisories |
|---|---|---|
| `requests` | 2.34.2 | none |
| `cryptography` | 50.0.1 | none |
| `protobuf` | 6.33.5 | none |
| `redis` | 8.1.0 | none |
| `python-dotenv` | 1.2.2 | none |
| `yfinance` | 1.6.0 | none |
| `matplotlib` | 3.11.1 | none |
| `ctrader-open-api`, `pyOpenSSL`, `Twisted`, `PyYAML` | — | not installed |

**Every pinned package is advisory-free.** The one remaining `pip-audit`
finding is `setuptools` (PYSEC-2026-3447), which is build-environment only and
not in `requirements.txt`. `pip check` reports no broken requirements, and
164/164 backend test files passed in that venv at the time.

#### `ctrader_accounts` encrypted at rest — DONE 2026-09-26

The observation recorded above, now acted on. **The decision was not the obvious
one**, and the reason matters more than the outcome.

**Adding the field to `_SENSITIVE_FIELDS` does nothing.** `_encrypt_sensitive`
only touches `isinstance(val, str)`, and `ctrader_accounts` holds a *list* of
`{"ctid": <int>, "live": <bool>}`. The name would have sat in a set called
"sensitive fields" while the data stayed in the clear — a change that reads as a
fix and is not one, which is worse than the honest status quo. Measured before
writing anything: adding the name left the value byte-for-byte unchanged.

So there is a second set, `_SENSITIVE_JSON_FIELDS`, encrypted as a JSON payload:
`json.dumps` → Fernet → `enc:<token>` on write, and the inverse on read, so the
four modules that read the field keep receiving the list they always did.

**Backwards compatibility.** A record written before this change holds a real
list, which is by definition "not a string starting with `enc:`", so it passes
through untouched — and the next save of that record encrypts it. That is the
common case until every record has been rewritten once, and it is asserted
directly: a hand-written legacy file, bypassing `save()`, loads correctly, is
accepted by the real reader (`ui_state._accounts`), gives the right count, and is
encrypted on the following save.

**An unopenable value reads as absent, never as itself.** Callers do
`for a in (u.get("ctrader_accounts") or [])`, so handing back the ciphertext
string would walk its characters and "find" accounts that do not exist. A
corrupted token, a truncated one, a non-token and a payload that decrypts but is
not JSON all become `None`, which `or []` turns into no accounts, with a log line
naming the field and not echoing the ciphertext.

**An empty list is deliberately not encrypted**, so "this client has no accounts"
stays distinguishable from "the list could not be read".

**The compare-and-set path is unaffected.** `ctrader_accounts` is in
`CRITICAL_FIELDS`, and Fernet ciphertext is non-deterministic, so a per-field
value comparison would see a change on every write. It does not do that: the CAS
compares a record version counter, not field values.

**WHAT IS DELIBERATELY NOT ENCRYPTED, AND SO WHAT THIS DOES NOT BUY.**
`ctrader_account_id` — the currently selected account — holds the same identifier
and stays in plaintext. It is a *selector*: compared against this list to render
the account switcher, displayed in roughly fourteen places, stored as an int.
That is exactly the "used as a key or index" case that must not be encrypted
without auditing every caller. So the protection is **partial**: the full set of
a client's accounts and which of them trade real money stop being readable at
rest; the one they have selected does not. The reason is written next to the set
in `user_store.py`, and a test asserts that it is written there — a silent
omission and a considered decision look identical in a diff otherwise.

Pinned by `tests/test_accounts_at_rest.py`. Mutations, each restored and re-run
green:

| Mutation | Result |
|---|---|
| the no-op "fix": move the field to `_SENSITIVE_FIELDS` | **fails 13 checks** |
| decrypt returns the ciphertext instead of `None` | fails 13 |
| skip the JSON decode, returning the decrypted string | fails 5 |
| encrypt the empty list too | fails 1 |
| legacy plaintext clobbered instead of passing through | fails 6 |

Verified: 165/165 backend test files pass, in the container and in a clean venv.

#### Decision, and it is recorded rather than defaulted

~~**Recommended minimal change: `protobuf==3.20.1` → `3.20.2`.**~~
**Withdrawn.** See the section above: it makes `pip install -r
requirements.txt` fail with ResolutionImpossible. The recommendation was made
from a `--no-deps` install, which proves the code works at that version and
proves nothing about whether it can be installed.

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
