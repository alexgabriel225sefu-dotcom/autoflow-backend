# Fix and verify a finding

Official Codex Security flow: start from **one** finding whose evidence a person accepts; generate a patch without changing the checkout; review the diff; apply only after acceptance; verify the original issue and legitimate behavior; record any verification gap. A generated or applied patch is not yet a verified fix. Verification does not automatically close the finding.

**Apex / Claude Code rule:** always show the diff and wait for explicit approval before editing the checkout. Never push. Never use this mode to sneak in unprotected-file edits.

## Procedure

1. Load the finding (ID and report path, plus any reproducer or validation command the user supplied). Re-read the current code. Confirm the issue is still present. If the intended security policy is unclear, ask before choosing a fix.
2. **Generate a patch artifact** in the scan directory (`patches/<finding-id>.diff` and a short `patches/<finding-id>.md` that explains the change). Do not modify the product checkout in this step.
3. Keep the change focused. No unrelated refactors, no weakened controls, no drive-by cleanups. Prefer a regression test that fails on the current code and would pass after the fix, written as a safe test, not an exploit payload.
4. Show the user the diff and the test plan. Wait.
5. Only after approval, apply the exact approved patch (or a revision they requested). Still do not edit `.github/workflows`, `render.yaml`, `server.js`, `.claude`, `live_gate`, or `test_platform_live_invariants.py` unless the approval named that file.
6. **Verify:**
   - The original failing check or regression test fails on the unfixed code (or you record why that could not be shown) and passes after the fix.
   - Legitimate behavior still works, including nearby tests.
   - Nearby bypasses were considered.
7. Record commands, results, and any remaining proof gap next to the patch. Leave the finding open if verification is incomplete.
8. Do not open a PR, commit, or push unless the user explicitly asked for that exact action after reviewing the verified diff.

If a reliable test cannot be created safely, say so and record what remains unverified. Do not "verify" a fix only by rereading the patch.
