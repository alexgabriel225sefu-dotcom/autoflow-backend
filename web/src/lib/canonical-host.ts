import { CANONICAL_WEB_ORIGIN } from "@/lib/supabase/redirect";

/**
 * The address the service got from the host before the product had its own
 * domain. It still answers, so people kept landing on it (and sharing it), and
 * search engines saw two copies of the same site.
 */
const OLD_HOST = "apex4traders-web.onrender.com";

/**
 * Where to send a request that arrived on the old address, or null to serve it.
 *
 * Only a page view moves (GET and HEAD): a form post or a server action
 * redirected with a new address can lose its body. The host's own health check
 * (user agent "Render/…") is never moved, so a deploy cannot be judged unhealthy
 * because the check followed a redirect.
 */
export function canonicalRedirect(input: {
  host: string | null;
  method: string;
  userAgent: string | null;
  pathname: string;
  search: string;
}): string | null {
  const host = (input.host ?? "").toLowerCase().split(":")[0];
  if (host !== OLD_HOST) return null;
  if (input.method !== "GET" && input.method !== "HEAD") return null;
  if ((input.userAgent ?? "").startsWith("Render/")) return null;
  return `${CANONICAL_WEB_ORIGIN}${input.pathname}${input.search}`;
}
