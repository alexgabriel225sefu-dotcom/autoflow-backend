import { apiError, methodNotAllowed } from "../../../_json";

/**
 * Public-site path for the platform billing webhook.
 *
 * The website and the API are different hosts. `www.apex4traders.com/api/*`
 * is this Next app. Until this route existed, that path was the catch-all
 * 404, not the Python handler. Stripe must not be pointed at a 404.
 *
 * This forwards one POST. It does not enable checkout or live trading.
 * The bytes and `Stripe-Signature` are copied as received. Nothing else
 * from the request is forwarded: no cookie, no authorization, no query.
 */

export const dynamic = "force-dynamic";

export const PLATFORM_WEBHOOK_PATH = "/api/v1/billing/webhook";

export function platformApiOrigin(
  raw = process.env.NEXT_PUBLIC_API_BASE_URL,
): string | null {
  if (!raw?.trim()) return null;
  try {
    const url = new URL(raw.trim());
    if (url.protocol !== "https:" && url.protocol !== "http:") return null;
    return url.origin;
  } catch {
    return null;
  }
}

function unavailable() {
  return apiError(
    503,
    "WEBHOOK_UNAVAILABLE",
    "The billing webhook is not configured on this site.",
  );
}

export async function POST(request: Request) {
  const origin = platformApiOrigin();
  let here = "";
  try {
    here = new URL(request.url).origin;
  } catch {
    here = "";
  }
  if (!origin || (here && origin === here)) return unavailable();

  const raw = await request.arrayBuffer();
  const headers = new Headers();
  const type = request.headers.get("content-type");
  if (type) headers.set("content-type", type);
  const signature = request.headers.get("stripe-signature");
  if (signature) headers.set("stripe-signature", signature);

  let upstream: Response;
  try {
    upstream = await fetch(origin + PLATFORM_WEBHOOK_PATH, {
      method: "POST",
      body: raw,
      headers,
      redirect: "manual",
    });
  } catch {
    return apiError(502, "INTERNAL_ERROR", "The billing service did not answer.");
  }
  if (upstream.status >= 300 && upstream.status < 400) {
    return apiError(502, "INTERNAL_ERROR", "The billing service redirected the webhook.");
  }
  const out = new Headers();
  const upstreamType = upstream.headers.get("content-type");
  if (upstreamType) out.set("content-type", upstreamType);
  return new Response(await upstream.arrayBuffer(), {
    status: upstream.status,
    headers: out,
  });
}

export const GET = () => methodNotAllowed("GET");
export const PUT = () => methodNotAllowed("PUT");
export const PATCH = () => methodNotAllowed("PATCH");
export const DELETE = () => methodNotAllowed("DELETE");
export const HEAD = () => methodNotAllowed("HEAD");
export const OPTIONS = () => methodNotAllowed("OPTIONS");
