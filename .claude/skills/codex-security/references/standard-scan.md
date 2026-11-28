# Standard security scan

Default single-pass audit of the current source of a repository or a selected folder. For a PR, commit, branch, or working-tree change, use `diff-scan`. For an explicitly requested deep or multi-pass audit, use `deep-scan`.

## Procedure

1. Bind target and scope. If the user named a folder, that folder is the target and the scope is its contents. Record branch, HEAD, and any user context. Do not switch revisions.
2. Load security context ([security-context.md](security-context.md)). If there is no threat model, draft a short working one before looking for vulnerabilities.
3. Keep the checkout read-only. Mapping, discovery, and validation must not edit product files. Write only into the new `security-scans/...` directory.
4. Map the in-scope system: components, data stores, entry points, and trust boundaries, with evidence. Separate runtime code from CI, dev tooling, tests, and examples.
5. Start from code that accepts untrusted input or exercises authority. Follow it to the operation it controls. Check the real enforcement point, its callers, and the strongest evidence that the suspected attack is blocked. For an exposed credential, the relevant path is who can read it and what access it grants.
6. Hunt for realistic, exploitable issues, including:
   - authentication or authorization bypass
   - cross-tenant or cross-user access
   - sensitive state change without correct enforcement
   - unsafe parsing, deserialization, or upload handling
   - secret or credential exposure
   - injection or command execution from untrusted input
   - server-side request forgery and unsafe outbound network use
   - filesystem or path traversal
   - webhook or callback forgery (including unsigned Stripe or platform webhooks)
   - sandbox or trust-boundary escape
7. For each candidate, identify the claimed attacker input, security boundary, relevant control, sensitive operation, and preconditions. Collect evidence that supports or defeats the claim. Preserve independently vulnerable instances.
8. Validate only when a safe local check would resolve a real uncertainty. Follow [validation.md](validation.md). Source analysis alone can support a finding. Do not treat "no runtime PoC" as "not a finding" when the code path is clear.
9. Calibrate severity and confidence honestly. Illustrative severity (adjust with `SECURITY.md` and product context):
   - **Critical:** pre-auth RCE, auth bypass that yields broad access, cross-tenant access, theft of production keys or tokens, live-trading enablement from an untrusted path
   - **High:** single-tenant unauthorized mutation (including billing), serious secret exposure, unsafe parsing that reaches a privileged service
   - **Medium:** targeted denial of service of a critical component, partial data exposure, rate-limit bypass with measurable impact
   - **Low:** low-sensitivity info leaks, issues that need unlikely preconditions
10. Write the scan directory using [report-format.md](report-format.md). The report must include every accepted finding, coverage (reviewed, deferred, excluded), and unresolved questions. Distinguish a completed audit with zero findings from an incomplete review.
11. Stop. Offer `fix-finding` only for findings the user accepts. Do not start editing.

## Honesty rules

- Do not invent components, controls, or deployments you did not see in the repo or in confirmed user context.
- Lack of TLS on a local dev server is usually not a finding (the official best-practices guidance makes the same point).
- "Best practice" style nits that are not exploitable belong in `security-best-practices` or in a hardening note, not as Critical/High vulnerabilities.
