import { NextResponse, type NextRequest } from "next/server";
import { updateSession } from "@/lib/supabase/middleware";
import { canonicalRedirect } from "@/lib/canonical-host";

export async function middleware(request: NextRequest) {
  if (request.nextUrl.pathname.startsWith("/api/")) {
    return NextResponse.next({ request });
  }
  // One public address. A visitor on the old host is moved before anything
  // else, so a sign-in always starts and ends on the same host (the PKCE
  // verifier lives in a cookie of the host that started it).
  const moved = canonicalRedirect({
    host: request.headers.get("host"),
    method: request.method,
    userAgent: request.headers.get("user-agent"),
    pathname: request.nextUrl.pathname,
    search: request.nextUrl.search,
  });
  if (moved) return NextResponse.redirect(moved, 308);
  return updateSession(request);
}

export const config = {
  // robots.txt and sitemap.xml are for crawlers, which have no session. Left in
  // the matcher they were answered with a redirect to /login, so a search engine
  // could not read what it may index.
  matcher: ["/((?!_next/static|_next/image|favicon.ico|robots\\.txt|sitemap\\.xml|.*\\.(?:svg|png|jpg|webp)$).*)"],
};
