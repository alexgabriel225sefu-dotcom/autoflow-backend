# Deep security scan

Official Codex Security deep scans run multiple independent standard scans over the same repository or folder and merge their findings. Workers can run in parallel, exchange leads, and stop after consecutive scans add nothing new or after a configured time or run limit.

**This Claude Code reconstruction cannot start official deep-scan workers, the workbench, or `~/.codex/codex-security/config.toml`.** It approximates the documented loop with **sequential** independent passes in one conversation.

Deep scan is not available for a diff or PR review. Use `diff-scan` instead.

## Before you start

Warn the user that a deep scan costs more time and tokens than a standard scan. Prefer a completed standard scan first if the scope or threat model is still unclear.

Default limits here are **stricter than Codex defaults** (official docs default to up to 40 discovery runs, 4 parallel workers, and a long time cap) so a Claude Code session stays usable. Honor a user-supplied budget when they give one.

Optional project config: `.claude/codex-security.toml` (do not read or write `~/.codex/...`).

```toml
[deep_scan]
# Sequential passes in this reconstruction (not official parallel workers).
max_discovery_runs = 4
stop_after_no_new = 2
max_time_hours = 2
```

If that file is absent, use the defaults above.

## Procedure

1. Resolve the same authorized target and scope as a standard scan. Reuse an existing threat model and `SECURITY.md`.
2. Confirm the limits with the user if the requested scope is the entire monorepo or they asked for an "exhaustive" run that would exceed the defaults.
3. Run pass 1 as a complete standard scan ([standard-scan.md](standard-scan.md)), including validation of distinct broken controls. Checkpoint candidates into the scan directory as they arrive.
4. For each later pass, start a fresh review of the same source. Give yourself the titles and locations already reported so you look for *new* issues and missed paths, not a rewrite of the same list. You may use earlier leads (suspicious entry points, weak boundaries) as hints, then re-check the current code.
5. Merge findings by location and issue, not by wording. Keep independently vulnerable instances. Drop a later candidate only when the earlier evidence still holds against the current code.
6. Stop when `stop_after_no_new` consecutive completed passes add no new accepted finding, or when `max_discovery_runs` or the time limit is reached.
7. Finalize one combined `report.md` that includes every accepted finding, which pass first reported it, coverage, and whether the run stopped because it was complete, hit a limit, or was interrupted. A pass count or a stub manifest is not a finished deep scan.
8. Distinguish "several passes completed, zero findings" from "the time or pass limit was hit before coverage was complete".

If a pass is interrupted, keep completed findings separate from unconfirmed candidates and say that coverage is incomplete. An empty list in that situation does not mean the code is clean.
