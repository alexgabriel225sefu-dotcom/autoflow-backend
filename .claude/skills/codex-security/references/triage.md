# Triage existing findings

Official Codex Security backlog triage reviews existing findings against the current repository with **read-only static analysis**. Each finding is an unproven claim. This mode does not search for new vulnerabilities, does not modify the repository, and does not implement fixes.

## Inputs

Accept one finding or a list, in the order supplied, from:

- Pasted text, SARIF, a CVE or GHSA, an advisory, a scanner ticket, a bug-bounty report, or a previous `findings.json` / `report.md`
- A local artifact path

Do not merge or drop findings that look like duplicates. Keep one result per input so the source stays traceable.

Official Codex can also import Jira, Linear, or GitHub code-scanning / Dependabot / advisory findings through connectors. This reconstruction has no those official connectors. If the user provides URLs or exported files, use only what is already readable in the workspace or what they paste. Do not scrape a ticket system or use someone else's credentials.

## Procedure

1. Bind the repository and load `SECURITY.md` plus the threat model ([security-context.md](security-context.md)).
2. For each input finding, extract the claim, affected locations, and preconditions. Inspect the current source for evidence that supports or defeats it. Do not execute the product.
3. Assign exactly one verdict:

| Verdict | Meaning |
|---|---|
| `confirmed` | Repository evidence shows the vulnerable path is reachable under the stated preconditions and crosses a supported security boundary. |
| `not_actionable` | Evidence rules the claim out (unaffected version, unreachable path, effective guard, or non-shipped surface). |
| `needs_review` | Evidence is not enough, because something is missing, ambiguous, runtime-dependent, environment-dependent, or policy-dependent. |

4. Rank `confirmed` and `needs_review` items separately. Include rationale, affected code, attacker prerequisites, and open questions.
5. Write a triage record into the scan directory (or a `triage.md` plus `triage.json` beside it). Do not change source tickets.

## Next steps (do not auto-start them)

- `confirmed`: after a person accepts the finding, offer `fix-finding`.
- `needs_review`: if a safe local test could resolve the proof gap, offer `validate`. If the gap is product policy or deployment context, ask the open questions instead.
- `not_actionable`: keep the evidence with the record.
