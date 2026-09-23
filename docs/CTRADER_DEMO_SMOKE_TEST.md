# cTrader demo smoke test

Closing blocker **X1**: proving the connected path works against a real
broker, rather than against the stubs that have stood in for one so far.

**Demo accounts only.** Nothing in this document is a step towards live
trading, and the script refuses to run against anything that is not a demo
account — twice, from two different sources.

---

## 1. Why this exists

Every connected screen in this product has been exercised in its *not
connected* state, which is the correct state to audit because it is what a new
client sees. What has never been exercised is the other one: an account with a
balance in it, positions with data in them, a chart with real bars, a preview
judged on live candles.

`docs/RELEASE_READINESS.md` records that as blocker X1, and it is the reason
the private-beta verdict is NOT YET rather than ready. Gates 1, 2 and 12 all
close together when this passes, and they do not close any other way.

A test cannot do it, because it needs a credential that belongs on a
deployment and not in a repository. So the work goes to the credentials.

## 2. What you need

| | |
|---|---|
| A cTrader **demo** account | With at least one instrument you can chart |
| A cTrader Open API application | `CTRADER_CLIENT_ID`, `CTRADER_CLIENT_SECRET` |
| A registered redirect URI | Byte-for-byte equal to `CTRADER_REDIRECT_URI` (blocker X4) |
| A Supabase project | For sign-up and sign-in (blocker X3) |
| The deployment's `TOKEN_ENCRYPTION_KEY` | The stored token cannot be decrypted without it |

Run this where those live — the deployment's shell — not on a laptop with a
copy of them.

## 3. The manual walk-through

In this order. Stop at the first failure and record it; a later step passing
after an earlier one failed does not mean the earlier one was unimportant.

1. **Sign up**, receive the confirmation e-mail, confirm, sign in.
2. **Connect** the demo account through OAuth. Confirm that the callback URL
   in the browser's address bar carries only a nonce — no `code`, no token —
   and that the link completes as the signed-in user.
3. **Select** the demo account. If the cTrader login also has a live account,
   confirm it is rendered disabled and labelled not available, and that
   selecting it is impossible rather than merely discouraged.
4. **Check the badge.** It must read `DEMO`. `GET /api/v1/me` carries the same
   verdict under `execution`.
5. **Confirm the reads carry data**: balance, positions, orders. An empty
   list here is a fact and is fine; a *missing* one is not — the screen must
   say which it is.
6. **Confirm the chart** renders real bars, and that its bar count and latest
   timestamp match what cTrader's own chart shows for the same symbol and
   timeframe. This is the step that catches a timeframe or timezone error,
   and nothing else does.
7. **Build a rule**, validate it, **preview** it on real bars, and read the
   verdict. Confirm every condition in the explanation names its own value.
8. **Activate** it, then **start** automation. Confirm the journal records
   evaluations — including the ones that place nothing, which are the
   majority and the ones most easily mistaken for the system being broken.
9. **Pause, resume, stop.** Confirm each is reflected in the status strip.
10. **Disconnect.** Confirm every read returns to *not connected* and no
    screen keeps showing the last data it had.
11. **Repeat 1–10 on a phone.**

Record the result, the date and the **masked** account number (last three
digits) in `docs/RELEASE_READINESS.md`. Do not paste a full account number, a
token, or a screenshot containing either.

## 4. The script

`apex-forex-bot/scripts/smoke_ctrader_demo.py` automates steps 4–7's read
side. It does not replace the walk-through — it cannot click anything, and
the OAuth flow, the UI states and the phone are the parts most likely to be
wrong.

```bash
export SMOKE_CONFIRM_DEMO_ONLY=yes
export SMOKE_USER_ID=<the Supabase user id>
export SMOKE_SYMBOL=EURUSD          # optional
export SMOKE_TIMEFRAME=M15          # optional
export SMOKE_RULE_ID=<a ruleDocId>  # optional — also previews it on real bars
cd apex-forex-bot && python3 scripts/smoke_ctrader_demo.py
```

| Exit | Meaning |
|---|---|
| 0 | Every step passed against a real demo account |
| 1 | A step failed — the connected path is not working. Do not record X1 as closed |
| 2 | It refused to start, and said why. Nothing was contacted |

### What it refuses

- Without `SMOKE_CONFIRM_DEMO_ONLY=yes`. It talks to a real broker account,
  so it will not start until an operator has said so in as many words.
- Without `SMOKE_USER_ID` or `TOKEN_ENCRYPTION_KEY`, naming whichever is
  missing.
- If the platform reports that live execution is enabled. This script's
  read-only guarantee assumes a release that cannot place a live order, and
  it stops rather than assuming.
- If the selected account's mode is not `demo` — **whatever the environment
  says**. The environment's opinion and the stored link record are two
  separate statements, and both have to agree.

### What it cannot do

It imports no execution module, no broker library and no automation code, and
calls `place_order`, `close_position`, `amend_sltp`, `force_trade` and the
order gates nowhere. `tests/test_smoke_harness.py` reads the script's source
and asserts all of that, because a comment promising it is worth nothing.

### Secrets

`apex.redact` is installed over stdout and stderr before any other import, so
even a traceback from inside a broker library is scrubbed on the way out.
Account numbers are masked to their last three digits — an account number is
not a credential, but it does identify a person, and this output ends up in
issues.

Writing this harness turned up a real gap: the runbook has told operators to
grep logs for `gAAAAA…` since before the redactor masked that shape. It does
now, and `tests/test_log_redaction.py` covers it.

## 5. What a pass and a failure each mean

A pass closes gates 1, 2 and 12 in `docs/RELEASE_READINESS.md` and moves the
private-beta verdict from NOT YET to BETA READY, provided X3 and X4 are also
in place.

A failure is information, not a setback: it is the first time this path has
been real, and everything it finds is something that would otherwise have
been found by a client. Record what failed rather than re-running until it
passes.
