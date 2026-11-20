/**
 * Trustpilot TrustBox settings. Nothing is shown until all three are set, so a
 * page can never display stars that Trustpilot has not issued.
 *
 * The two ids come from the TrustBox snippet in the Trustpilot business account
 * (Integrations, TrustBox). They are public identifiers (they sit in the page
 * markup of every site that embeds the widget), so NEXT_PUBLIC_ is correct, and
 * they are inlined at build time: change them, then redeploy.
 *
 *   NEXT_PUBLIC_TRUSTPILOT_BUSINESSUNIT_ID   data-businessunit-id
 *   NEXT_PUBLIC_TRUSTPILOT_TEMPLATE_ID       data-template-id (the widget type)
 *   NEXT_PUBLIC_TRUSTPILOT_DOMAIN            the domain the profile is claimed for
 *                                            (defaults to apex4traders.com)
 */
export const TRUSTPILOT_SCRIPT_HOST = "https://widget.trustpilot.com";
export const TRUSTPILOT_SCRIPT_URL = `${TRUSTPILOT_SCRIPT_HOST}/bootstrap/v5/tp.widget.bootstrap.min.js`;

export type TrustpilotConfig = {
  businessUnitId: string;
  templateId: string;
  /** The public profile, where people read the reviews. */
  profileUrl: string;
  /** Where a customer writes one. */
  reviewUrl: string;
};

const ID = /^[a-z0-9]{8,40}$/i;

function domainOf(env: Record<string, string | undefined>): string {
  return (env.NEXT_PUBLIC_TRUSTPILOT_DOMAIN?.trim() || "apex4traders.com")
    .replace(/^https?:\/\//, "")
    .replace(/\/.*$/, "");
}

/**
 * The two public Trustpilot pages for the domain. They need no id, no plan and
 * no script: a plain link. "profileUrl" is where people read the reviews,
 * "reviewUrl" is where a customer writes one.
 */
export function trustpilotLinks(
  env: Record<string, string | undefined> = process.env,
): { profileUrl: string; reviewUrl: string } {
  const domain = domainOf(env);
  return {
    profileUrl: `https://www.trustpilot.com/review/${domain}`,
    reviewUrl: `https://www.trustpilot.com/evaluate/${domain}`,
  };
}

export function trustpilotConfig(
  env: Record<string, string | undefined> = process.env,
): TrustpilotConfig | null {
  const businessUnitId = env.NEXT_PUBLIC_TRUSTPILOT_BUSINESSUNIT_ID?.trim() ?? "";
  const templateId = env.NEXT_PUBLIC_TRUSTPILOT_TEMPLATE_ID?.trim() ?? "";
  if (!ID.test(businessUnitId) || !ID.test(templateId)) return null;
  return { businessUnitId, templateId, ...trustpilotLinks(env) };
}
