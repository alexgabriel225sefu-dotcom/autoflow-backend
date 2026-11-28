# Adaptations

This folder is a derivative work of OpenAI's Apache-2.0 curated skill
`security-threat-model` from https://github.com/openai/skills
(commit `49f948faa9258a0c61caceaf225e179651397431`).

Changes from upstream:

- Added provenance and Apex4Traders / Claude Code safety rules.
- Added a note to also consider `docs/security/threat-model.md` (the path official Codex Security documentation recommends), plus `CLAUDE.md` / `AGENTS.md` / `SECURITY.md` as context, and never to embed secret values.
- Left the threat-model workflow, references, and output contract otherwise unchanged.
