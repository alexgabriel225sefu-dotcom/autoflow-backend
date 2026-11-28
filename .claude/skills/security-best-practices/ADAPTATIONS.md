# Adaptations

This folder is a derivative work of OpenAI's Apache-2.0 curated skill
`security-best-practices` from https://github.com/openai/skills
(commit `49f948faa9258a0c61caceaf225e179651397431`).

Changes from upstream:

- Added provenance and Apex4Traders / Claude Code safety rules (read-only default, no secret printing, protected paths, no live trading, diffs need approval, no exploit PoCs).
- In the Fixes section, require a proposed diff and explicit approval before editing, committing, or pushing.
- Replaced the phrase "reviewed by codex" with "reviewed by this skill".
- Left reference guidance, report format, and workflow otherwise unchanged.
