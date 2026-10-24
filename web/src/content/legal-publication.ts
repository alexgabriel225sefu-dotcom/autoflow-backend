/**
 * The legal-draft version the public pages and the live gate share.
 *
 * Publication is an owner action. `A4T_LEGAL_PUBLISH` must equal
 * `LEGAL_VERSION` exactly. Any other value, including "true" or "1",
 * leaves the pages unpublished. This module never sets the variable.
 *
 * The Python switch is `apex/platform/legal_content.py`. A test fails
 * when the two version strings diverge.
 */
export const LEGAL_VERSION = "2026-10-24";
export const PUBLISH_ENV = "A4T_LEGAL_PUBLISH";
export const DRAFT_NOTICE = "DRAFT - requires legal review";

export const PLACEHOLDERS = [
  "COMPANY_NAME",
  "REGISTRATION_NUMBER",
  "ADDRESS",
  "JURISDICTION",
  "VAT",
] as const;

export function legalPublished(
  env: NodeJS.ProcessEnv | Record<string, string | undefined> = process.env,
): boolean {
  return (env[PUBLISH_ENV] ?? "").trim() === LEGAL_VERSION;
}
