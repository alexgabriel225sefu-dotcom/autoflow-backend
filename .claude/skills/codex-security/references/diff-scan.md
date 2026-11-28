# Security diff scan

Review one Git-backed change set for security regressions. Official Codex Security reviews each changed source-like file and its directly supporting code. It does **not** expand the review into a full repository audit. Deep scan is not available for a changes review.

## What to review

Resolve the change from the user request, in this order of explicitness:

- Uncommitted changes (working tree, including staged and unstaged), when they asked to review current local changes
- A single commit
- A base and head revision (branch range or pull request), when both revisions are available locally

Do not check out another branch or switch the working tree. If a requested revision is missing, ask the user to fetch it, or stop and say what is unavailable.

Confirm the intended range in the report: repository, branch, base, head, and a short summary of the change (`git log` / `git diff --stat` is enough).

## Procedure

1. List changed source-like files in the range. Skip lockfiles, generated vendor trees, and binary assets unless they clearly affect a security boundary (for example, a changed WASM sandbox or a checked-in private key).
2. Load security context ([security-context.md](security-context.md)) so the review is judged against the system's actual boundaries, not a generic checklist.
3. For each changed source file, read the diff and the directly supporting code (callees, the real enforcement point, nearby auth or tenant checks, tests that claim to cover the change). Do not wander into unrelated packages just to "be thorough".
4. Look for regressions in authentication, authorization (including tenant isolation), input handling, filesystem access, outbound network requests, secret handling, webhook verification, billing mutations, and the demo/live trading boundary.
5. A pre-existing issue that the change does not touch is out of scope for this mode. You may mention it briefly as context, but do not turn the diff review into a repository scan.
6. Validate only when a safe local check would resolve whether the change introduced the issue. Follow [validation.md](validation.md). Keep the checkout unchanged.
7. Write the scan directory using [report-format.md](report-format.md). Record the exact revision range in the manifest and report.

On Apex4Traders, a diff that touches billing, auth, tenant scoping, webhooks, or live-trading gates deserves extra attention even if the diff is small.
