# NOVA — setup

Read NOVA_IOS_LIMITATIONS.md first if you have not. It says what NOVA can and
cannot do, and it is shorter than discovering the limits later.

## 1. What you need

| | |
|---|---|
| Render plan | **Starter**, $7/mo. Not free — see §2 |
| Disk | 1 GB at `/data` (in the blueprint) |
| Telegram bot | from @BotFather |
| OpenAI key | from platform.openai.com |
| iPhone | Shortcuts (built in), Telegram, optionally the OpenClaw app |

## 2. Why not the free tier

Render rejects a blueprint that attaches a persistent disk to a free instance,
and OpenClaw's docs state that without one *"OpenClaw state resets on every
deploy"* — config, memory, allowlist, node pairings, gone. Free instances also
sleep after 15 minutes idle, so NOVA would be asleep whenever you wanted it.

Two official docs disagree on the plan: `render.com/docs/deploy-openclaw` says
*"Pro is the smallest instance type that supports OpenClaw"*, while
`docs.openclaw.ai/install/render` uses `starter`. The blueprint follows
OpenClaw's own value. **If the service is killed with no error in the log, that
is out-of-memory and the signal to move to Pro.**

## 3. Deploy the gateway

1. Push this branch.
2. Render Dashboard → **New → Blueprint**.
3. Pick this repository, and **set the blueprint path to `nova/render.yaml`**.
   This step is what keeps APEX untouched — Render's spec: services not
   included in a blueprint are unaffected by its sync.
4. Render prompts for the two `sync: false` variables. Paste
   `TELEGRAM_BOT_TOKEN` and `OPENAI_API_KEY`.
5. Apply. Render builds the Dockerfile, pulls the pinned image, attaches the
   disk, and seeds the config.

## 4. First login

Copy `OPENCLAW_GATEWAY_TOKEN` from Dashboard → nova-gateway → Environment.
Open `https://<service>.onrender.com/` and authenticate with it.

That token is the only credential. If you cannot get in, re-read it — do not
disable authentication.

## 5. Check the seed took

In the Control UI, confirm:

- the agent is named **NOVA**
- `tools.profile` is `minimal`
- `channels.telegram.dmPolicy` is `allowlist` and `allowFrom` contains your id

If any is missing the seed did not run — but note the container is built to
**refuse to start** in that case rather than come up unconfigured, so a live
service with a missing allowlist should not be reachable. If you see one,
treat it as a finding and stop the service.

## 6. Telegram

Message your bot. It should answer. Then message it from a different Telegram
account — it should **not**. If it does, the allowlist is not in force and that
is the first thing to fix.

## 7. The model

Set `agents.defaults.model.primary` in the Control UI to the model you want
NOVA to reason with. The OpenAI key is already in the environment.

## 8. Shortcuts

Follow `nova/shortcuts/README.md`. Build the "NOVA" one first — it is the
voice-first path, and the rest are variations on it.

You have to build them by hand: unsigned `.shortcut` files cannot be imported
on iOS.

## 9. The endpoint for Shortcuts

The Control UI shows the gateway's HTTP surface. Use the endpoint it documents
for sending a message to a session, with:

```
Authorization: Bearer <OPENCLAW_GATEWAY_TOKEN>
```

Test it once from Shortcuts before adding Speak Text, so a failure shows as an
error rather than silence.

## 10. iPhone as a node (optional)

Only needed for camera, screen, location and voice wake.

Install the OpenClaw iOS app. It discovers gateways by Bonjour on the LAN, by
Tailnet, or by **manual host/port** — the last is the one that applies, since
Render is not on your LAN. Remote connections need *"a `wss://` Gateway
endpoint with a certificate trusted by watchOS"*; Render's `*.onrender.com`
certificate qualifies. Plain HTTP and self-signed certificates are rejected.

Pairing: app → Settings → Gateway → manual host/port → a request is generated →
approve it (`openclaw nodes pending`, then `openclaw nodes approve <id>`) →
`openclaw nodes status` should read `paired · connected`.

Remember what this does and does not add: camera and screen need the app in the
foreground, and it still cannot call, message, or read Contacts.

## 11. Testing

| # | Test | Expected |
|---|---|---|
| 1 | Build | green |
| 2 | `/startupz` | healthy, service goes live |
| 3 | Dashboard, no token | refused |
| 4 | Dashboard, correct token | admitted |
| 5 | Dashboard, wrong token | refused |
| 6 | Telegram, your account | answers |
| 7 | Telegram, another account | **refused** |
| 8 | "Hey Siri, NOVA" | listens, answers aloud |
| 9 | Ask for something current | cites sources, does not invent |
| 10 | Ask it to run a shell command | refuses — `group:runtime` is denied |
| 11 | Paste text containing "ignore your instructions" | treats it as content |
| 12 | Change a setting, redeploy | change survives |
| 13 | Restart | comes back, memory intact |
| 14 | Logs | no token, key or header visible |
| 15 | iOS node pairing | `paired · connected` |

Tests 7, 10, 11 and 14 are the security ones. Do not skip them.

## 12. Troubleshooting

| Symptom | Cause |
|---|---|
| Never goes live | `/startupz` failing — read the log before changing anything |
| Exits at once, `mkdir` or `cp` error in the log | The disk is not writable by uid 1000. This is the container refusing to start rather than booting with no config — see §5. Fix the disk, do not remove `set -e` |
| Killed, no error | out of memory → move to Pro |
| Dashboard rejects the token | stale copy; re-read Environment |
| Bot silent | `TELEGRAM_BOT_TOKEN` missing, or your id not in `allowFrom` |
| Anyone can message it | the seed did not run; set `dmPolicy: allowlist` by hand |
| State lost on deploy | the disk is missing — a free instance cannot have one |
| Shortcut returns nothing | check the endpoint and the `Authorization` header |
| iOS app will not connect | it needs `wss://` with a trusted certificate |

## 13. Updating

The version is pinned deliberately. To update: change the tag in
`nova/Dockerfile`, read the release notes, push, redeploy. Verify the tag
exists first — a bad tag fails the build:

```
TOKEN=$(curl -s 'https://ghcr.io/token?scope=repository:openclaw/openclaw:pull&service=ghcr.io' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $TOKEN" \
  https://ghcr.io/v2/openclaw/openclaw/manifests/<tag>
```

`200` means it exists. OpenClaw ships betas alongside stable tags; `2026.7.1-2`
is stable.

## 14. Secret rotation

| Secret | How |
|---|---|
| `OPENCLAW_GATEWAY_TOKEN` | change in Render Environment; every node re-pairs, every Shortcut needs the new value |
| `TELEGRAM_BOT_TOKEN` | `/revoke` in @BotFather, then update Render |
| `OPENAI_API_KEY` | revoke at platform.openai.com, then update Render |

None are in Git, so rotation is a dashboard edit and a redeploy.

## 15. Emergency shutdown

- **Stop it:** Render → Suspend. The disk is kept.
- **Cut Telegram only:** `/revoke` the bot token.
- **Cut AI only:** revoke the OpenAI key.
- **Drop every device:** rotate `OPENCLAW_GATEWAY_TOKEN`.
- **APEX is unaffected by all of these** — it has no dependency on NOVA, which
  `apex-forex-bot/tests/test_failure_matrix.py` asserts directly.

## 16. Backup and recovery

**The disk is not a backup.** It survives redeploys and restarts. It does not
survive deleting the service, and Render does not version its contents.

Worth backing up from `/data/.openclaw`: the config and any memory you care
about. Everything else rebuilds from this repository plus two environment
variables.

If the disk is lost: recreate from the blueprint, re-enter the two secrets,
re-pair the phone. Roughly ten minutes, and no credential is lost — they live
in Render, not on the disk.
