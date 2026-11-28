import { createClient } from "./client";
import { safeNext } from "./middleware";

/** The login URL that returns here, and that is not bounced back to the app. */
export function reauthUrl(pathname: string, search: string): string {
  const next = safeNext(`${pathname}${search}`);
  return `/login?reauth=1&next=${encodeURIComponent(next)}`;
}

/**
 * Removes the session cookies this page can reach.
 *
 * The server can see a session in these cookies (that is why the page opened)
 * while the browser client reports none, and then a plain link to /login is
 * sent straight back to the dashboard: the visitor loops between two screens
 * that each say the other is right. Deleting them here is what breaks it.
 */
export function clearSessionCookies(): void {
  if (typeof document === "undefined") return;
  for (const part of document.cookie.split(";")) {
    const name = part.split("=")[0]?.trim();
    if (name && name.startsWith("sb-")) {
      document.cookie = `${name}=; Max-Age=0; path=/`;
    }
  }
}

/** Ends whatever is left of the local session and opens the sign-in page. */
export async function signInAgain(): Promise<void> {
  try {
    await createClient().auth.signOut({ scope: "local" });
  } catch {
    // The session may already be gone; the cookies are cleared below anyway.
  }
  clearSessionCookies();
  window.location.assign(reauthUrl(window.location.pathname, window.location.search));
}
