/**
 * Auth links must return to the public product, not whichever preview host
 * happened to send the request. Local development is the only exception.
 */
export const CANONICAL_WEB_ORIGIN = "https://www.apex4traders.com";

function isLocalOrigin(origin: string) {
  try {
    const url = new URL(origin);
    return (url.hostname === "localhost" || url.hostname === "127.0.0.1")
      && (url.protocol === "http:" || url.protocol === "https:");
  } catch {
    return false;
  }
}

export function canonicalWebOrigin(origin: string) {
  return isLocalOrigin(origin) ? new URL(origin).origin : CANONICAL_WEB_ORIGIN;
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
