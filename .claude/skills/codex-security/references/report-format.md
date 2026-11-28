# Scan report format

Official Codex Security docs describe a complete scan directory whose portable entry point is `report.md`, kept together with structured artifacts. This reconstruction uses the same file names and the field names documented in the public guides so reports feel familiar. It is **not** an official plugin export and is not guaranteed to validate against a proprietary schema.

## Directory

Create a new directory and write only there:

```
security-scans/<YYYYMMDD-HHMMSS>-<mode>/
  report.md
  findings.json
  coverage.json
  scan-manifest.json
  findings/<finding-id>/report.md    # only when a finding needs a longer writeup
  hardening/                          # optional structural guidance, if requested
  patches/                            # only for fix-finding
  triage.md / triage.json             # only for triage
```

Do not commit this directory unless the user asked. Never include secret values, `.env` contents, or raw credentials. Source excerpts must be short and redacted.

`mode` is one of `standard`, `deep`, `diff`, `triage`, `validate`, `fix`.

## `report.md`

Markdown, written for a reviewer. Include:

1. Target, revision (and base/head for a diff), scope, mode, start time (Europe/Bucharest when reporting to the user), and a one-paragraph summary.
2. Threat-model and policy sources actually used, plus key assumptions.
3. Findings table, ordered by severity then confidence, with ID, title, severity, confidence, path, and short impact.
4. For each finding: attack path, failed control, supported impact, validation method (source analysis, safe local test, or both), evidence with file paths and line numbers, remediation guidance, and unresolved questions.
5. Coverage: what was reviewed, deferred, or excluded, and why. Outstanding proof gaps.
6. A clear statement if the run is incomplete.

## `findings.json`

A JSON object with a `findings` array. Each item should include at least the fields named in the official public CLI/docs examples:

```json
{
  "findings": [
    {
      "findingId": "F-001",
      "occurrenceId": "F-001-1",
      "title": "Short specific title",
      "severity": { "level": "high" },
      "confidence": { "level": "high" },
      "locations": [
        { "path": "src/example.ts", "startLine": 42, "endLine": 58 }
      ],
      "attackPath": "Who can send what, to which entry point, reaching which operation.",
      "failedControl": "The check that should have blocked this.",
      "impact": "Concrete impact on a specific asset.",
      "validationMethod": "source-analysis",
      "remediation": "Focused guidance, not a generic slogan.",
      "unresolvedQuestions": [],
      "status": "open"
    }
  ]
}
```

`findingId` identifies the issue; `occurrenceId` identifies this occurrence in this scan. Severity and confidence levels: `critical`, `high`, `medium`, `low`.

## `coverage.json`

Record in-scope surfaces, reviewed files or components, deferred areas, explicit exclusions, and a `complete` boolean (false if the review was interrupted or hit a limit before source review finished).

## `scan-manifest.json`

A local receipt, not an official Codex sealed manifest. Include: mode, target path, git revisions, scope, policy files read, start/end time, model name if known, limits used (for a deep scan), and SHA-256 hashes of `report.md`, `findings.json`, and `coverage.json`.
