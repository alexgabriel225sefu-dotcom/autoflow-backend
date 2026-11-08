import { NextResponse, type NextRequest } from "next/server";
import { updateSession } from "@/lib/supabase/middleware";

export async function middleware(request: NextRequest) {
  if (request.nextUrl.pathname.startsWith("/api/")) {
    return NextResponse.next({ request });
  }
  return updateSession(request);
}

export const config = {
  // robots.txt and sitemap.xml are for crawlers, which have no session. Left in
  // the matcher they were answered with a redirect to /login, so a search engine
  // could not read what it may index.
  matcher: ["/((?!_next/static|_next/image|favicon.ico|robots\\.txt|sitemap\\.xml|.*\\.(?:svg|png|jpg|webp)$).*)"],
};
