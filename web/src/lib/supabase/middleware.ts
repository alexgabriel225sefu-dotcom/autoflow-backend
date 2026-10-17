import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

/**
 * Paths a signed-out visitor may see. Everything else needs a session.
 *
 * Deny by default: a route added under `(app)/` is protected because it is
 * absent from this list, not because anything was remembered.
 *
 * `/configurator` is here because it is the return URL the PREVIOUS checkout
 * used. Somebody following an old link from an old receipt has no session on
 * this platform and never will, so gating it sends them to a login wall for an
 * account they do not have — which is the exact 404-equivalent the page was
 * kept to avoid. It is static, makes no authenticated call, and states no
 * licence state of its own.
 */
export const PUBLIC_PATHS = [
  "/", "/login", "/signup", "/auth/confirm", "/auth/reset",
  "/auth/callback", "/terms", "/privacy", "/configurator",
];

/**
 * The only place a post-login redirect target is decided.
 *
 * Two jobs, and they pull against each other. It must keep the QUERY STRING:
 * the cTrader callback returns people to /connect?n=<nonce> in a fresh tab
 * whose sessionStorage is empty, so that parameter is the only record of
 * which attempt they just approved — drop it and they come back to a page
 * offering to start over.
 *
 * And it must refuse to leave this origin. The value reaches here from the
 * address bar, and the login page navigates to whatever it is handed, so
 * anything that is not a same-origin path is a redirect somebody else chose.
 * "Starts with a slash" is not that check: "//evil.example" satisfies it and
 * is a protocol-relative URL to another site.
 */
export function safeNext(value: string | null | undefined): string {
  const raw = (value ?? "").trim();
  if (!raw.startsWith("/")) return "/dashboard";
  // Protocol-relative ("//host") and the backslash spelling browsers also
  // accept ("/\\host").
  if (raw.startsWith("//") || raw.startsWith("/\\")) return "/dashboard";
  return raw;
}

/**
 * The exact string that goes into `next=`.
 *
 * Pulled out of the middleware so it can be tested without standing up a
 * NextRequest and a Supabase client. That is not tidiness: the version that
 * dropped the query string passed every test of safeNext(), because the
 * dropping happened at the call site rather than inside it. A mutation put
 * the bug back and nothing failed.
 */
export function nextTarget(pathname: string, search: string | undefined): string {
  return safeNext(`${pathname}${search ?? ""}`);
}

export function isPublic(pathname: string) {
  return PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}

/**
 * Route protection, and the refreshed session cookie.
 *
 * THIS IS CONVENIENCE, NOT AUTHORISATION. It keeps a signed-out visitor from
 * loading a dashboard that would only fill with 401s — nothing more. Every
 * endpoint behind it re-verifies the session against Supabase and checks
 * ownership server-side, because a redirect is something a client controls
 * and a gate is not.
 */
export async function updateSession(request: NextRequest) {
  let response = NextResponse.next({ request });
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !key) return response;

  const supabase = createServerClient(url, key, {
    cookies: {
      getAll: () => request.cookies.getAll(),
      setAll: (cookies) => {
        cookies.forEach(({ name, value }) => request.cookies.set(name, value));
        response = NextResponse.next({ request });
        cookies.forEach(({ name, value, options }) =>
          response.cookies.set(name, value, options));
      },
    },
  });

  const { data: { user } } = await supabase.auth.getUser();
  const { pathname } = request.nextUrl;

  if (!user && !isPublic(pathname)) {
    const to = request.nextUrl.clone();
    to.pathname = "/login";
    // Where they were headed, INCLUDING the query: a broker-link nonce lives
    // there and nowhere else once the flow has moved to a new tab.
    to.search = "";
    to.searchParams.set("next", nextTarget(pathname, request.nextUrl.search));
    return NextResponse.redirect(to);
  }
  if (user && (pathname === "/login" || pathname === "/signup")) {
    const to = request.nextUrl.clone();
    to.pathname = "/dashboard";
    to.search = "";
    return NextResponse.redirect(to);
  }
  return response;
}
