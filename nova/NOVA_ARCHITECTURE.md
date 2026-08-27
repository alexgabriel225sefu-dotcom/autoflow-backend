# NOVA — architecture

## The shape, and why it is this shape

```
        ┌──────────────── iPhone ────────────────┐
        │   Telegram      Shortcuts      OpenClaw │
        │   (thinking)    (acting)       (seeing) │
        └───────┬─────────────┬──────────────┬────┘
                │             │              │
            polling         HTTPS           WSS
                │             │              │
                └─────────────┼──────────────┘
                              ▼
                  ┌───────────────────────┐
                  │   NOVA Gateway        │
                  │   OpenClaw on Render  │
                  │                       │
                  │   persona · memory    │
                  │   tools  · permissions│
                  │   audit               │
                  └───────────┬───────────┘
                              │
                  ┌───────────┼───────────┐
                  ▼           ▼           ▼
                 WEB        EMAIL      APEX
              (research)   (later)   (read-only, later)
```

**One brain, three clients, and each client does what only it can.**

That division is forced by iOS, not chosen. The gateway can reason and reach
the internet but cannot touch your phone. Shortcuts can dial and message but
cannot hold a conversation. The OpenClaw app can see through the camera but
only while you are looking at it.

| Client | Role | Reliable when |
|---|---|---|
| Telegram | conversation, research, anything that is thinking | always — phone locked, app closed |
| Shortcuts | calls, messages, opening apps, voice in/out | on demand, via Siri |
| OpenClaw iOS app | camera, screen, location, voice wake | app in the foreground |

## Components

### Gateway — `nova/render.yaml`, `nova/Dockerfile`

OpenClaw `2026.7.1-2`, pinned, from `ghcr.io/openclaw/openclaw`. Verified
pullable before pinning; the image config was read directly rather than assumed:

| Property | Value | Consequence |
|---|---|---|
| `User` | `node` | already non-root, nothing to change |
| `Entrypoint` | `tini -s --` | signals propagate, so SIGTERM is a graceful shutdown |
| `Cmd` | `node openclaw.mjs gateway` | **no `--allow-unconfigured`** — which is why `dockerCommand` is required, and why `runtime: image` would have silently started the wrong thing |

Runs as a Render **web service** because it serves HTTP (dashboard, API) and
WebSocket (nodes) — a background worker has no public URL and could not accept
either.

### Configuration — `nova/config/nova.json5`

Seeded onto the disk on first boot, then owned by the disk. Carries three
things: NOVA's identity, the tool policy, and the Telegram allowlist.

Seeding rather than documenting a manual step is a security decision. The
allowlist is a control; a control that requires someone to remember it is not
in force during the window before they do.

`cp -n` never overwrites, so anything you change through the Control UI
survives every redeploy.

### Persona

Set through `agents.entries.nova.identity`. Deliberately a *manner*, not a
character: intelligent, calm, fast; concise for simple requests, thorough for
research; says plainly when it cannot do something. The brief asked for a
modern assistant rather than roleplay, and an assistant that invents
capabilities is worse than one that admits limits.

### Memory

`group:memory` on the persistent disk at `/data`. Survives redeploys and
restarts. Credentials are never written to it — see NOVA_SECURITY.

### Tools

Five permission levels mapped onto OpenClaw's profile + allow/deny + tool
groups. Full table in NOVA_SECURITY.md. The short version: web and memory are
open, messaging is gated by confirmation, filesystem and shell are denied.

## Data flow — a voice request end to end

```
"Hey Siri, NOVA"
   → Shortcuts: Dictate Text
   → POST to the gateway, Bearer <OPENCLAW_GATEWAY_TOKEN>
   → NOVA: reason → web_search / web_fetch → synthesise
   → JSON reply
   → Shortcuts: Speak Text
```

Everything crossing the network is HTTPS with a Render-issued certificate. The
token never leaves the Shortcut and Render's environment.

## Storage

| Path | Contents | Survives redeploy |
|---|---|---|
| `/data/.openclaw` | config, credentials, memory, node pairings | **yes** |
| `/data/workspace` | files NOVA works on | **yes** |
| everything else | container filesystem | no |

A redeploy replaces the container and keeps the disk. Deleting the *service*
deletes the disk with it. A disk is not a backup — see NOVA_SETUP §16.

## What is deliberately not here

- **No custom iOS app.** Xcode is macOS-only and there is no Mac. The three
  clients above are all already installable.
- **No APEX connection.** Read-only, later, through `ops_api.py` only.
- **No always-on anything.** iOS suspends background work; a design that
  depends on it would be a design that quietly does not run.

## Extending it

Adding a device later means pairing another OpenClaw node to the same gateway —
the architecture already assumes more than one. Adding a capability means
adding a tool to `tools.allow`, which is a deliberate act with a name attached,
not a side effect of an upgrade.
