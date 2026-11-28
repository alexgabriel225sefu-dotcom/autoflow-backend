---
name: second-opinion-review
description: Ask a second model for a review-only critique of a local diff or PR, via LiteLLM or any OpenAI-compatible API. Use when the user wants another opinion, a code review, a design critique, or a ship/no-ship read before merging.
---

# Second-opinion review

Idea adapted from the grok-build-plugin-cc review/critique flow (Apache-2.0): a *review-only* pass that challenges the change, not a silent auto-fix. The helper and prompt in this folder were written for this pack; they are not the plugin's bridge scripts.

This skill does not apply patches. It reports findings and stops, unless the user then asks you to fix something.

## Apex safety (mandatory)

- Never edit `.github/workflows`, `render.yaml`, `live_gate`, or `test_platform_live_invariants.py` as part of this review.
- **Redact before upload.** Strip API keys, tokens, `.env` values, cookies, private customer data, and webhook signing secrets from the diff and from any logs you attach. If a hunk is only a secret, drop it and note that it was omitted.
- Keys live in environment variables only. Never hard-code a key, never write one into this skill, and never echo it in chat.
- Do not enable live trading or place orders in order to "verify" a finding.
- Treat findings about live-trading gates, tenant isolation, Stripe webhooks, and secret handling as blocking until the user decides otherwise.

## When to run it

After a non-trivial change is in the working tree or on a branch, or when the user asks for a second model to review. Skip typo-only diffs unless they asked anyway.

## Collect the change

```sh
# Working tree (staged + unstaged + short list of untracked names, not their contents if they may be secrets)
git status --short --untracked-files=all
git diff --cached
git diff

# Or vs a base branch
git diff main...HEAD
```

Do not include `node_modules`, build output, lockfile-only noise, or binary files. Cap the payload: if the diff is huge, review by directory or ask which area to focus on. Untracked files may contain secrets — list names, include contents only when you have checked them.

## Call another model

Prefer this order:

1. An OpenAI-compatible endpoint you already have (LiteLLM proxy, OpenAI, xAI, Anthropic-compatible gateway, etc.).
2. The helper `review.mjs` in this skill folder.

Environment (set in the shell, not in git):

| Variable | Role |
|---|---|
| `REVIEW_API_KEY` | Bearer token (required) |
| `REVIEW_API_BASE` | Default `https://api.openai.com/v1`. For LiteLLM proxy, the proxy base ending in `/v1` |
| `REVIEW_MODEL` | Default `gpt-4.1`. Use whatever the user named |

```sh
# From the repo root, after writing a redacted diff to /tmp/review.diff
node /path/to/.claude/skills/second-opinion-review/review.mjs \
  --diff /tmp/review.diff \
  --prompt /path/to/.claude/skills/second-opinion-review/review-prompt.md
```

If `review.mjs` is not convenient, a single HTTPS chat-completions call with the same prompt + diff is enough. Do not install a new LLM SDK unless the user wants LiteLLM itself.

LiteLLM one-liner (optional, if `litellm` is already installed):

```python
import os
from pathlib import Path
from litellm import completion
# API keys still come from the environment (OPENAI_API_KEY, etc.). Never hard-code them.
resp = completion(
    model=os.environ.get("REVIEW_MODEL", "gpt-4.1"),
    messages=[{"role": "user", "content": Path("review-prompt.md").read_text() + "\n\n" + Path("/tmp/review.diff").read_text()}],
)
print(resp.choices[0].message.content)
```

## How to brief the reviewer

Use `review-prompt.md` as the system/user preamble. Add:

- What the change is supposed to do (two sentences).
- The redacted diff and, if useful, a few nearby file paths as context.
- Any focus area the user named (billing, RLS, UI, …).

Ask for material findings only: what can go wrong, why this path is vulnerable, impact, and a concrete fix. No style nits. For Apex, weight these surfaces heavily:

- Live-trading gates and any path that could place a real order
- Tenant isolation / RLS and cross-user reads
- Stripe webhooks, idempotency, refunds, and fulfillment
- Auth, session, and secret leakage (logs, frontend, git)
- Idempotent retries, partial failure, migrations

## After the reply

- Show the findings to the user in full, or a faithful structured summary if the model returned JSON.
- Do **not** start fixing issues in the same turn unless they asked you to apply the review.
- If the second model invents files or line numbers, say you could not verify them before treating them as real.
