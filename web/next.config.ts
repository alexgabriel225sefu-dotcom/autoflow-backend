import path from "node:path";
import type { NextConfig } from "next";

/**
 * WHY `turbopack.root` IS SET EXPLICITLY
 *
 * This repository holds two products. The root carries its own package.json
 * and package-lock.json for the legacy Express sales site; this directory
 * carries the Next.js client's own. Turbopack walks upwards looking for a
 * workspace root, finds the root lockfile, and infers the repository root
 * rather than this directory — which changes how modules resolve and what the
 * build traces into its output.
 *
 * Next 16 warns about exactly this. Naming the root removes the ambiguity
 * instead of depending on which lockfile the inference happens to reach
 * first, and it does so without touching the other product's files.
 */

/**
 * Origin of an absolute URL, or null when the variable is unset or not a URL.
 *
 * The API base and the Supabase URL are build/runtime configuration, not
 * constants. A header list that hard-coded one project would be wrong for the
 * next one, and a header list that dropped an unknown origin would block the
 * calls the app actually makes.
 */
function originOf(raw: string | undefined): string | null {
  if (!raw) return null;
  try {
    const url = new URL(raw);
    if (url.protocol !== "http:" && url.protocol !== "https:") return null;
    return url.origin;
  } catch {
    return null;
  }
}

/**
 * Enforcing Content-Security-Policy.
 *
 * What this app actually loads, checked against the source rather than guessed:
 * - scripts and styles are same-origin, plus one inline script in the root
 *   layout (the no-flash theme script) and the style tag next/font emits.
 *   Without 'unsafe-inline' that script does not run. There is no nonce
 *   middleware, so 'unsafe-inline' is the policy that matches the pages.
 * - next/font self-hosts Geist. No fonts.googleapis.com request at runtime.
 * - lightweight-charts is bundled and draws on a canvas. It does not load a
 *   script, a worker, or a frame from anywhere else.
 * - Supabase auth (session refresh, Google sign-in URL) is a fetch to the
 *   project host, plus a websocket on the same host. Standard projects are
 *   *.supabase.co; a custom domain is added from NEXT_PUBLIC_SUPABASE_URL
 *   when that variable is present.
 * - The backend may live on another origin (NEXT_PUBLIC_API_BASE_URL). Same
 *   origin when the variable is empty, which 'self' already covers. Next
 *   records this header list at build time, the same moment it inlines
 *   NEXT_PUBLIC_* into the client, so a production build has to see those
 *   variables or connect-src will not name the API host. *.supabase.co is
 *   always listed, so a standard Supabase project is reachable either way.
 * - Stripe checkout is a top-level navigation (window.location.assign) to
 *   buy.stripe.com or checkout.stripe.com. form-action lists those hosts so
 *   a form submission to the same pages is allowed too. The navigation itself
 *   is not a form submit and is not blocked by this policy.
 * - Google sign-in leaves the page for Supabase, which redirects to Google.
 *   That is a top-level navigation, not a framed or fetched Google document.
 *
 * 'unsafe-eval' is added only outside production. next dev uses it for the
 * refresh runtime; the production bundle does not.
 *
 * upgrade-insecure-requests is production-only. In local http dev it would
 * rewrite the API (often http://127.0.0.1) to https and break it.
 *
 * frame-ancestors 'none' is paired with X-Frame-Options: DENY. The page
 * embeds no iframes of its own (frame-src 'none'); the privacy copy says so
 * and content.test.ts checks it.
 */
export function contentSecurityPolicy(): string {
  const connect = new Set<string>([
    "'self'",
    "https://*.supabase.co",
    "wss://*.supabase.co",
  ]);
  const supabase = originOf(process.env.NEXT_PUBLIC_SUPABASE_URL);
  if (supabase) connect.add(supabase);
  const api = originOf(process.env.NEXT_PUBLIC_API_BASE_URL);
  if (api) {
    connect.add(api);
    if (api.startsWith("https://")) connect.add("wss://" + api.slice("https://".length));
    else if (api.startsWith("http://")) connect.add("ws://" + api.slice("http://".length));
  }

  const script = ["'self'", "'unsafe-inline'"];
  if (process.env.NODE_ENV !== "production") script.push("'unsafe-eval'");

  const directives = [
    "default-src 'self'",
    `script-src ${script.join(" ")}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self'",
    `connect-src ${[...connect].join(" ")}`,
    "frame-src 'none'",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'self' https://buy.stripe.com https://checkout.stripe.com",
    "frame-ancestors 'none'",
  ];
  if (process.env.NODE_ENV === "production") {
    directives.push("upgrade-insecure-requests");
  }
  return directives.join("; ");
}

const PERMISSIONS_POLICY = [
  "accelerometer=()",
  "camera=()",
  "geolocation=()",
  "gyroscope=()",
  "magnetometer=()",
  "microphone=()",
  "payment=()",
  "usb=()",
].join(", ");

const nextConfig: NextConfig = {
  turbopack: {
    root: path.resolve(__dirname),
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          {
            // Two years, subdomains included. Not preload: preload is a
            // one-way submission for the whole domain and belongs to whoever
            // owns the domain, not to this config file. Browsers ignore this
            // header on plain http, so local dev does not pin itself to https.
            key: "Strict-Transport-Security",
            value: "max-age=63072000; includeSubDomains",
          },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: PERMISSIONS_POLICY },
          { key: "Content-Security-Policy", value: contentSecurityPolicy() },
        ],
      },
    ];
  },
};

export default nextConfig;
