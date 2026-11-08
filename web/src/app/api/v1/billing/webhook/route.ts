import { apiError, methodNotAllowed } from "../../../_json";

/**
 * Public-site path for the platform billing webhook.
 *
 * The website and the API are different hosts. This forwards one POST to
 * the API origin named by `NEXT_PUBLIC_API_BASE_URL`, at a fixed path.
 * The request does not choose the host or the path.
 *
 * The bytes and `Stripe-Signature` are copied as received. Nothing else
 * is forwarded: no cookie, no authorization, no query. Redirects are not
 * followed. A missing signature is refused before the body is forwarded.
 * The body and the upstream response are each capped, and the upstream
 * call has a deadline.
 */

export const dynamic = "force-dynamic";

export const PLATFORM_WEBHOOK_PATH = "/api/v1/billing/webhook";
export const MAX_WEBHOOK_BYTES = 1_048_576;
export const UPSTREAM_DEADLINE_MS = 10_000;

export function platformApiOrigin(
  raw = process.env.NEXT_PUBLIC_API_BASE_URL,
  production = process.env.NODE_ENV === "production",
): string | null {
  if (!raw?.trim()) return null;
  let url: URL;
  try {
    url = new URL(raw.trim());
  } catch {
    return null;
  }
  if (url.username || url.password) return null;
  if (url.protocol !== "https:" && (production || url.protocol !== "http:")) return null;
  const host = url.hostname.replace(/^\[|\]$/g, "").toLowerCase();
  if (!host || isBlockedHost(host)) return null;
  if (production && isLiteralIp(host)) return null;
  return url.origin;
}

function isLiteralIp(host: string): boolean {
  if (/^\d{1,3}(\.\d{1,3}){3}$/.test(host)) return true;
  return host.includes(":");
}

function isBlockedHost(host: string): boolean {
  if (
    host === "localhost"
    || host.endsWith(".localhost")
    || host.endsWith(".local")
    || host.endsWith(".internal")
    || host === "metadata.google.internal"
  ) {
    return true;
  }
  if (host === "::1" || host === "::") return true;
  const v4 = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(host);
  if (v4) {
    const n = v4.slice(1).map(Number);
    if (n.some((part) => part > 255)) return true;
    const [a, b] = n;
    if (a === 0 || a === 10 || a === 127) return true;
    if (a === 169 && b === 254) return true;
    if (a === 172 && b >= 16 && b <= 31) return true;
    if (a === 192 && b === 168) return true;
    if (a === 100 && b >= 64 && b <= 127) return true;
    return false;
  }
  if (host.startsWith("fe80:") || host.startsWith("fc") || host.startsWith("fd")) return true;
  return false;
}

function unavailable() {
  return apiError(
    503,
    "WEBHOOK_UNAVAILABLE",
    "The billing webhook is not configured on this site.",
  );
}

function contentLength(raw: string | null): number | "invalid" | null {
  if (raw == null || raw.trim() === "") return null;
  if (!/^\d+$/.test(raw.trim())) return "invalid";
  const n = Number(raw);
  if (!Number.isSafeInteger(n)) return "invalid";
  return n;
}

function exactBytes(raw: Uint8Array): ArrayBuffer {
  const copy = new ArrayBuffer(raw.byteLength);
  new Uint8Array(copy).set(raw);
  return copy;
}

export async function readBounded(
  body: ReadableStream<Uint8Array> | null,
  maxBytes: number,
): Promise<Uint8Array | "too-large"> {
  if (!body) return new Uint8Array(0);
  const reader = body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      if (!value?.byteLength) continue;
      total += value.byteLength;
      if (total > maxBytes) {
        await reader.cancel();
        return "too-large";
      }
      chunks.push(value);
    }
  } catch (err) {
    await reader.cancel().catch(() => undefined);
    throw err;
  }
  const out = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    out.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return out;
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

  const signature = request.headers.get("stripe-signature");
  if (!signature?.trim()) {
    return apiError(400, "BAD_SIGNATURE", "The Stripe signature is missing.");
  }

  const declared = contentLength(request.headers.get("content-length"));
  if (declared === "invalid" || (typeof declared === "number" && declared > MAX_WEBHOOK_BYTES)) {
    return apiError(413, "PAYLOAD_TOO_LARGE", "The webhook body is too large.");
  }

  let raw: Uint8Array;
  try {
    const read = await readBounded(request.body, MAX_WEBHOOK_BYTES);
    if (read === "too-large") {
      return apiError(413, "PAYLOAD_TOO_LARGE", "The webhook body is too large.");
    }
    raw = read;
  } catch {
    return apiError(400, "INTERNAL_ERROR", "The webhook body could not be read.");
  }
  const rawBytes = exactBytes(raw);

  const headers = new Headers();
  const type = request.headers.get("content-type");
  if (type) headers.set("content-type", type);
  headers.set("stripe-signature", signature);

  const signal = AbortSignal.timeout(UPSTREAM_DEADLINE_MS);
  let upstream: Response;
  try {
    upstream = await fetch(origin + PLATFORM_WEBHOOK_PATH, {
      method: "POST",
      body: rawBytes,
      headers,
      redirect: "manual",
      signal,
    });
    if (upstream.status >= 300 && upstream.status < 400) {
      return apiError(502, "INTERNAL_ERROR", "The billing service redirected the webhook.");
    }
    const upstreamLength = contentLength(upstream.headers.get("content-length"));
    if (
      upstreamLength === "invalid"
      || (typeof upstreamLength === "number" && upstreamLength > MAX_WEBHOOK_BYTES)
    ) {
      return apiError(502, "INTERNAL_ERROR", "The billing service sent a response that is too large.");
    }
    const upstreamBody = await readBounded(upstream.body, MAX_WEBHOOK_BYTES);
    if (upstreamBody === "too-large") {
      return apiError(502, "INTERNAL_ERROR", "The billing service sent a response that is too large.");
    }
    const out = new Headers();
    const upstreamType = upstream.headers.get("content-type");
    if (upstreamType) out.set("content-type", upstreamType);
    return new Response(exactBytes(upstreamBody), { status: upstream.status, headers: out });
  } catch (err) {
    const name = err instanceof Error ? err.name : "";
    if (name === "AbortError" || name === "TimeoutError") {
      return apiError(504, "UPSTREAM_TIMEOUT", "The billing service did not answer in time.");
    }
    return apiError(502, "INTERNAL_ERROR", "The billing service did not answer.");
  }
}

export const GET = () => methodNotAllowed("GET");
export const PUT = () => methodNotAllowed("PUT");
export const PATCH = () => methodNotAllowed("PATCH");
export const DELETE = () => methodNotAllowed("DELETE");
export const HEAD = () => methodNotAllowed("HEAD");
export const OPTIONS = () => methodNotAllowed("OPTIONS");
