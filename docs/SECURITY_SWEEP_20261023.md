# Security sweep — 2026-10-23

Scope: `claude/apex4traders-platform-v1` at `be71810`. This is a read-only
security review plus the explicitly authorised release documentation change.
No live order, payment, checkout, Telegram, or production data path was
changed.

## API authorization matrix

The transport mounts `apex.platform.api.handle` at `/api/v1/`. Every route not
listed as public below calls `_authenticate`; money-moving actions additionally
request `fresh=True` and pass through the existing server gate.

| Route | Auth / fresh session | Ownership and validation | Rate-limit class | Error boundary |
|---|---|---|---|---|
| `POST billing/webhook` | Public; provider signature required | Stripe signature is verified before parsing/acting | webhook bucket | provider errors are translated |
| `GET billing/offer` | Public | Read-only server offer | default/public | JSON envelope |
| `POST waitlist` | Public | Email is validated and only the submitted record is stored | waitlist bucket | provider result is redacted |
| `GET ctrader/callback` | Public browser redirect | Parks callback state only; completion requires the authenticated POST | callback bucket | JSON envelope |
| `POST ctrader/connect` | Authenticated, verified email | User id comes from verified token | control bucket | link errors carry diagnostic id |
| `POST ctrader/complete` | Fresh authenticated session, verified email | Nonce is looked up under the token user | control bucket | link errors carry diagnostic id |
| `POST ctrader/select` | Authenticated | cTrader link record owns the selectable account id | control bucket | link errors are coded |
| `POST ctrader/disconnect` | Fresh authenticated session | Disconnect is keyed by token user | control bucket | link errors are coded |
| `GET ctrader/status` | Authenticated | Token user only | default | JSON envelope |
| `GET accounts` | Authenticated | Token user only | default | JSON envelope |
| `GET accounts/{ctid}` | Authenticated | ctid must be in the caller's link record | default | broker read status envelope |
| `GET accounts/{ctid}/positions` | Authenticated | ctid binding is checked before broker construction | default | no empty success on read failure |
| `GET accounts/{ctid}/orders` | Authenticated | ctid binding is checked before broker construction | default | no empty success on read failure |
| `GET accounts/{ctid}/candles` | Authenticated | ctid binding and query validation happen before broker read | default | invalid input is 400 |
| `GET positions`, `GET orders` | Authenticated | Selected account is read from the caller's link | default | broker read status envelope |
| `GET automation` | Authenticated | State is keyed by token user | default | JSON envelope |
| `POST automation/{start,pause,resume,stop}` | Fresh authenticated session; start/resume also verified email | Server resolves rule/account; no request user id | control bucket | coded refusal envelope |
| `GET approvals` | Authenticated | Pending proposal keyed by token user | default | JSON envelope |
| `POST approvals/{approve,reject}` | Fresh authenticated; approve also verified email | Proposal and account are keyed by token user | default (tightening recommended) | coded refusal envelope |
| `GET notifications` | Authenticated | Query is scoped to token user | default | JSON envelope |
| `POST notifications/read-all`, `POST notifications/{id}/read` | Authenticated | Notification id is resolved under token user | control/default | JSON envelope |
| `GET journal`, `GET journal/{id}` | Authenticated | Journal lookup is scoped to token user | default | JSON envelope |
| `GET system/status`, `GET me`, `GET strategies`, `GET conditions` | Authenticated | Token user / static registry | default | JSON envelope |
| `GET rules`, `POST rules`, `GET/PUT rules/{id}` | Authenticated | Store key includes token user; body cannot choose owner | default/control | ownership violation is 500, not data |
| `GET rules/{id}/versions/{n}` | Authenticated | Version lookup is scoped to token user | default | JSON envelope |
| `POST rules/{id}/{validate,activate,pause,resume,archive,version,preview}` | Authenticated; action helper applies fresh auth where required | Rule store enforces owner | control bucket | coded rule errors |
| `POST billing/checkout` | Fresh authenticated | Disabled by release gates; no payment intent is created | control bucket | 503 while disabled |

Unknown routes and wrong methods return JSON `NOT_FOUND` / `METHOD_NOT_ALLOWED`.
The API wrapper catches unhandled exceptions and does not return stack traces.

## Findings

_As reported at the time of the sweep, against `be71810`. The "Reported only" status and the missing-file notes below are resolved in the Resolution section at the end._

| Severity | Location | Scenario | Status |
|---|---|---|---|
| P1 | `apex-forex-bot/apex/platform/broker_read.py:74,85,91,108` | A connector/link exception whose detail contains a URL, header or token can be copied into the response because `_scrub` only removes the known access token. | Reported only; the branch does not contain the authorised `automation._safe_cause` helper. |
| P1 | `apex-forex-bot/apex/platform/api.py:286,305,321,342,426,590` | Several typed exception handlers return `e.detail`/`str(e)` directly. A provider or store exception can expose internal paths or credential-shaped values to a client. | Reported only; requires the missing safe-cause contract to avoid changing existing public error semantics blindly. |
| P1 | `apex-forex-bot/apex/platform/emergency.py:124-145` | `state()` places the raw exception type and message in `storeError`; an authenticated system-status caller can receive a backend error string. | Reported only. |
| P2 | `apex-forex-bot/apex/ownership.py:97-157` | The requested shutdown re-acquire race could not be reproduced because this branch has no `begin_shutdown` flag or shutdown-aware claim API. `release_all()` can release while a heartbeat is between its read and claim. | Reported only; exact fix needs the newer ownership contract. |
| P2 | Missing paths | `position_close.py`, `emergency_stop.py`, and `live_pilot.py` named by the supplied review brief do not exist on this base. Their claimed controls cannot be reviewed or tested on this branch. | Reported only; branch/commit mismatch. |
| P2 | `apex-forex-bot/apex/platform/api.py:395-439` | Checkout remains correctly disabled and the webhook is signature-gated; no live payment path was found. | Verified by code and existing tests. |

No IDOR path was found in the reviewed API routes: account, rule, journal,
notification and automation state are resolved from the verified user id, and
the cTrader read path refuses a requested account that does not match the
stored connection.

## Dependency and secret checks

- `npm audit --offline --json`: 0 advisories in the local lockfile snapshot.
- `pip-audit`: unavailable on this host (`pip_audit` is not installed), so the
  Python advisory set is unverified in this run.
- Targeted secret-shape scan: no repository secret found; matches were only
  documentation examples and scanner reference material.
- Gitleaks/trufflehog were not installed; a complete history scan is therefore
  unverified.

## Independent review coverage

The supplied `live_pilot.py` path and the newer `position_close.py` path are not
present on the requested base commit. The existing `live_execution.py` is
wired behind the release switch and the live invariant suite remains
unchanged; no claim is made that the absent pilot guard was reviewed.

## Resolution (follow-up on this branch)

The branch was brought current by merging `claude/fix-low-findings` (which
contains `claude/apex4traders-platform-v1`). That resolves the "branch mismatch"
findings: `position_close.py`, `emergency_stop.py`, `live_pilot.py` and the
shutdown-aware ownership contract come from approved upstream commits (PRs #16,
#17 and #18) and were not re-created here.

| Finding | Resolution | Regression test |
|---|---|---|
| P1 `broker_read.py` `_scrub` | Redacts by shape through `redact.scrub_for_client` (refresh tokens, app secrets, bearer headers, quoted dumps, token-like runs, base64 padding); error codes survive. | `test_error_redaction_paths.py` [4], `test_review_low_findings.py` [1] |
| P1 `api.py` typed handlers | Every typed handler (auth, store, link, licence, entitlement, automation, halt, preview, waitlist, approval, close, bad request) answers through `safe_errors.message`, which is `scrub_for_client` plus URL, host and filesystem-path shapes. Codes, statuses and diagnostic ids are unchanged. | `test_error_redaction_paths.py` [1], [2] - one named check per handler |
| P1 `emergency.py` `state()` | `storeError` is now `STORE_UNREACHABLE (<ExceptionClass>)`; the message goes only to the scrubbed log. The halt refusal built from it carries the same string. | `test_error_redaction_paths.py` [3] |
| P2 ownership race | Present upstream (`begin_shutdown`, lock shared with `release_all`); covered by `test_platform_shutdown_release.py`. | upstream |
| P2 missing modules | Branch mismatch, resolved by the merge above. | upstream |
| Live invariant: `apex/gates.py` "additional module" | Not an extra path. `gates.authorize_order` is the single gate; it is the one engine module outside `apex/platform/` that names `live_execution` and no platform module imports it. The check compares POSIX-style paths; a checkout that predates the separator normalisation (commit `eca3c6e6c` upstream) reports `apex\\gates.py` on Windows and the expected module itself shows up as the mismatch. The expectation is unchanged and not relaxed. | `test_platform_live_invariants.py` [1c] |

Mutation proof: each handler's redaction was removed in turn and the matching
named check failed (for example `AuthFailed: no URL, host, path, header or token
in the answer`, `waitlist: refusal text is redacted`, `storeError carries no
message from the store`); the file was restored after each.
