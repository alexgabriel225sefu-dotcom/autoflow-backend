import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

/** Paths a signed-out visitor may see. Everything else needs a session. */
export const PUBLIC_PATHS = [
  "/", "/login", "/signup", "/auth/confirm", "/auth/reset",
  "/auth/callback", "/terms", "/privacy",
];

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
    // Where they were headed, so signing in does not dump them on a
    // dashboard when they clicked a link to their journal.
    to.searchParams.set("next", pathname);
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
