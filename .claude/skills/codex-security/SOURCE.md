# Source and differences

## What this skill is

A Claude Code reconstruction of the **documented** OpenAI Codex Security product workflow:

threat model → scan (standard, deep, or diff) → evidence-backed validation / triage → patch proposal and verification.

Public documentation used (official, retrieved 2026-11-28):

- https://learn.chatgpt.com/docs/security
- https://learn.chatgpt.com/docs/security/plugin/scans
- https://learn.chatgpt.com/docs/security/plugin/deep-scans
- https://learn.chatgpt.com/docs/security/plugin/code-changes
- https://learn.chatgpt.com/docs/security/plugin/fix-findings
- https://learn.chatgpt.com/docs/security/plugin/triage-backlog
- https://learn.chatgpt.com/docs/security/threat-model
- https://developers.openai.com/codex/security
- https://developers.openai.com/blog/building-security-review-into-your-sdlc-with-codex-security

This pack is **not affiliated with OpenAI**.

## What was not copied

The official Codex plugin at
https://github.com/openai/plugins/tree/main/plugins/codex-security
is publicly visible, but its manifest sets `"license": "Proprietary"`.
Its `SKILL.md` files, references, schemas, MCP server, and workbench
code were **not** copied or ported into this pack.

The separately published `@openai/codex-security` CLI/SDK
(https://github.com/openai/codex-security, Apache 2.0) is a hosted
client. Running it requires Codex Security access and is not bundled here.

## Official Apache-2.0 skills that *were* ported

These curated skills from https://github.com/openai/skills (Apache License 2.0)
are included beside this folder, with attribution and `LICENSE.txt` retained:

- `security-threat-model`
- `security-best-practices`
- `security-ownership-map`

Each folder has an `ADAPTATIONS.md` describing Claude Code / Apex changes.

## How this differs from Codex Security

| In official Codex Security | In this Claude Code skill |
|---|---|
| Codex Security plugin, MCP tools, and desktop workbench (`get_codex_security_scan_context`, `start_codex_security_*_scan`, scan IDs, handoff tokens) | Not available. The agent follows the documented phases in these markdown files and writes a local scan directory. |
| Daybreak Defense Factory and hosted / isolated validation fleet | Not available. Validation is a safe local test or source-only evidence. |
| Official plugin `$codex-security:security-scan`, `$codex-security:deep-security-scan`, `$codex-security:security-diff-scan`, `$codex-security:triage-finding`, `$codex-security:validation`, `$codex-security:fix-finding` | One Claude Code skill, `/codex-security`, with the same mode names as documentation. |
| Deep scan: parallel Standard-scan workers, `~/.codex/codex-security/config.toml` | Sequential multi-pass reviews with modest defaults; optional project file `.claude/codex-security.toml`. No `~/.codex` config is used. |
| Recommended model `gpt-5.6-sol` with `xhigh` reasoning | Whatever model Claude Code is already running. |
| `AGENTS.md` for build and validation commands | Read `CLAUDE.md` and, if present, `AGENTS.md`. |
| Sealed workbench receipts and official plugin version metadata | A local `scan-manifest.json` with target, revisions, and artifact hashes. It is not an official Codex receipt. |
| Finding writeups may include proof-of-concept files | **Forbidden here.** Use source evidence and safe local regression tests only. |
| Conversation `fix-finding` can be authorized to edit the checkout | Always show the diff first and wait for approval. Never push. |
| `@openai/codex-security` CLI / CI examples | Not invoked by this skill. |

The workflow phases, review questions (attack path, failed control, impact, validation method, coverage), artifact names from the public docs (`report.md`, `findings.json`, `coverage.json`, `scan-manifest.json`), and triage verdicts (`confirmed`, `not_actionable`, `needs_review`) are reproduced on purpose so the output is familiar. They are not a claim of plugin compatibility.
