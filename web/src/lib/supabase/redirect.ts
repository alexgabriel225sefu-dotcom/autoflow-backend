/**
 * Auth links must return to the public product, not whichever preview host
 * happened to send the request.
 *
 * Two kinds of origin keep their own address instead of being rewritten:
 * local development, and the product's own hosts. The sign-in uses PKCE, and
 * the code verifier lives in a cookie on the host that STARTED the flow. A
 * Google sign-in begun on the onrender address and sent back to www arrives
 * without its verifier and fails, so only an origin nobody owns (a preview
 * deployment) is rewritten to the public one.
 *
 * Emailed links (sign-up confirmation, password reset) are requested through
 * the implicit client and need no verifier, because the inbox is usually
 * opened in another browser than the one that asked.
 */
export const CANONICAL_WEB_ORIGIN = "https://www.apex4traders.com";

const PRODUCT_HOSTS = new Set([
  "www.apex4traders.com",
  "apex4traders.com",
  "apex4traders-web.onrender.com",
]);

function isLocalOrigin(origin: string) {
  try {
    const url = new URL(origin);
    return (url.hostname === "localhost" || url.hostname === "127.0.0.1")
      && (url.protocol === "http:" || url.protocol === "https:");
  } catch {
    return false;
  }
}

function isProductOrigin(origin: string) {
  try {
    const url = new URL(origin);
    return url.protocol === "https:" && PRODUCT_HOSTS.has(url.hostname);
  } catch {
    return false;
  }
}

export function canonicalWebOrigin(origin: string) {
  return isLocalOrigin(origin) || isProductOrigin(origin)
    ? new URL(origin).origin
    : CANONICAL_WEB_ORIGIN;
}

export function authCallbackUrl(
  origin: string,
  options: { next?: string | null; recovery?: boolean } = {},
) {
  const url = new URL("/auth/callback", canonicalWebOrigin(origin));
  if (options.recovery) url.searchParams.set("mode", "recovery");
  if (options.next) url.searchParams.set("next", options.next);
  return url.toString();
}
