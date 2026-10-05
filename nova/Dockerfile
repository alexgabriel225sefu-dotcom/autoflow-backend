# NOVA gateway — the official OpenClaw image, pinned, plus one seed file.
#
# WHY A DOCKERFILE when a prebuilt image needs no build: Render's blueprint
# spec states `dockerCommand` works only with `runtime: docker` and has no
# effect under `runtime: image`. The gateway must start with
# `--allow-unconfigured`, and the image's own CMD is
# `["node","openclaw.mjs","gateway"]` WITHOUT that flag — verified by reading
# the image config from ghcr, not assumed. So `runtime: image` would silently
# start the wrong command.
#
# Tag verified pullable before pinning: an anonymous manifest request for
# 2026.7.1-2 returned HTTP 200. It is the stable release, not a beta.
FROM ghcr.io/openclaw/openclaw:2026.7.1-2

# The seed config. It is COPIED here, never read from here at runtime: OpenClaw
# writes to its config atomically, so the live file has to sit on the
# persistent disk. The start command copies this into place ONLY IF the disk
# has no config yet (see render.yaml). That matters for security rather than
# convenience — the Telegram allowlist ships in this file, so the very first
# boot is already restricted instead of waiting for a manual step.
COPY config/nova.json5 /seed/nova.json5

# Verified from the image config, deliberately NOT overridden:
#   User       = "node"            -> already non-root
#   Entrypoint = ["tini","-s","--"] -> signals reach the process, so Render's
#                                      SIGTERM produces a graceful shutdown
# Changing USER here would risk the /data disk becoming unwritable.
