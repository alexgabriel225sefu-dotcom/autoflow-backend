import { afterEach, describe, expect, it, vi } from "vitest";
import { POST, GET, MAX_WEBHOOK_BYTES, platformApiOrigin, readBounded } from "./route";

const RAW = new TextEncoder().encode('{"id":"evt_test","type":"checkout.session.completed"}');

function request(url = "https://www.apex4traders.com/api/v1/billing/webhook") {
  return new Request(url, {
    method: "POST",
    body: RAW,
    headers: {
      "content-type": "application/json",
      "stripe-signature": "t=1,v1=abc",
      cookie: "session=secret",
      authorization: "Bearer should-not-forward",
    },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  delete process.env.NEXT_PUBLIC_API_BASE_URL;
});

describe("public billing webhook route", () => {
  it("does not invent an API origin", () => {
    expect(platformApiOrigin("")).toBeNull();
    expect(platformApiOrigin("not a url")).toBeNull();
    expect(platformApiOrigin("https://apex4traders-api.onrender.com/ignored"))
      .toBe("https://apex4traders-api.onrender.com");
  });

  it("answers JSON 503 when the API origin is unset, not an HTML page", async () => {
    const response = await POST(request());
    expect(response.status).toBe(503);
    expect(response.headers.get("content-type") ?? "").toContain("application/json");
    const body = await response.json();
    expect(body).toMatchObject({ ok: false, error: { code: "WEBHOOK_UNAVAILABLE" } });
  });

  it("refuses to proxy to itself", async () => {
    process.env.NEXT_PUBLIC_API_BASE_URL = "https://www.apex4traders.com";
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const response = await POST(request());
    expect(response.status).toBe(503);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("forwards the raw body and Stripe signature only", async () => {
    process.env.NEXT_PUBLIC_API_BASE_URL = "https://apex4traders-api.onrender.com";
    const fetchSpy = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(
      async () => new Response(JSON.stringify({ ok: true, handled: false }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchSpy);
    const response = await POST(request());
    expect(response.status).toBe(200);
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const url = fetchSpy.mock.calls[0][0];
    const init = fetchSpy.mock.calls[0][1];
    if (!init?.body) throw new Error("the forward call has no body");
    expect(url).toBe("https://apex4traders-api.onrender.com/api/v1/billing/webhook");
    expect(init.method).toBe("POST");
    expect(init.redirect).toBe("manual");
    expect(init.signal).toBeInstanceOf(AbortSignal);
    const forwarded = new Uint8Array(init.body as ArrayBuffer);
    expect(Array.from(forwarded)).toEqual(Array.from(RAW));
    const headers = init.headers as Headers;
    expect(headers.get("stripe-signature")).toBe("t=1,v1=abc");
    expect(headers.get("content-type")).toBe("application/json");
    expect(headers.get("cookie")).toBeNull();
    expect(headers.get("authorization")).toBeNull();
    expect(await response.json()).toEqual({ ok: true, handled: false });
  });

  it("does not follow a redirect from the API", async () => {
    process.env.NEXT_PUBLIC_API_BASE_URL = "https://apex4traders-api.onrender.com";
    vi.stubGlobal("fetch", vi.fn(async () => new Response(null, {
      status: 302,
      headers: { location: "https://www.apex4traders.com/" },
    })));
    const response = await POST(request());
    expect(response.status).toBe(502);
    const body = await response.json();
    expect(body.error.code).toBe("INTERNAL_ERROR");
    expect(JSON.stringify(body)).not.toContain("www.apex4traders.com/");
  });

  it("rejects a private or malformed origin before any forward", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    for (const raw of [
      "https://127.0.0.1",
      "https://10.1.2.3",
      "http://169.254.169.254",
      "https://localhost",
      "https://user:secret@apex4traders-api.onrender.com",
      "not a url",
    ]) {
      process.env.NEXT_PUBLIC_API_BASE_URL = raw;
      const response = await POST(request());
      expect(response.status).toBe(503);
    }
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("requires https for a public origin when this process is production", () => {
    expect(platformApiOrigin("http://apex4traders-api.onrender.com", true)).toBeNull();
    expect(platformApiOrigin("https://apex4traders-api.onrender.com", true))
      .toBe("https://apex4traders-api.onrender.com");
    expect(platformApiOrigin("https://10.1.2.3", true)).toBeNull();
  });

  it("refuses a missing signature before reading or forwarding", async () => {
    process.env.NEXT_PUBLIC_API_BASE_URL = "https://apex4traders-api.onrender.com";
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const response = await POST(new Request(
      "https://www.apex4traders.com/api/v1/billing/webhook",
      {
        method: "POST",
        body: RAW,
        headers: { "content-length": String(MAX_WEBHOOK_BYTES + 50) },
      },
    ));
    expect(response.status).toBe(400);
    expect((await response.json()).error.code).toBe("BAD_SIGNATURE");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("refuses a body larger than the cap before forwarding", async () => {
    process.env.NEXT_PUBLIC_API_BASE_URL = "https://apex4traders-api.onrender.com";
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const response = await POST(new Request(
      "https://www.apex4traders.com/api/v1/billing/webhook",
      {
        method: "POST",
        body: RAW,
        headers: {
          "stripe-signature": "t=1,v1=abc",
          "content-length": String(MAX_WEBHOOK_BYTES + 1),
        },
      },
    ));
    expect(response.status).toBe(413);
    expect((await response.json()).error.code).toBe("PAYLOAD_TOO_LARGE");
    expect(fetchSpy).not.toHaveBeenCalled();
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new Uint8Array(8));
        controller.enqueue(new Uint8Array(8));
        controller.close();
      },
    });
    expect(await readBounded(stream, 10)).toBe("too-large");
  });

  it("stops when the API does not answer within the deadline", async () => {
    process.env.NEXT_PUBLIC_API_BASE_URL = "https://apex4traders-api.onrender.com";
    const fetchSpy = vi.fn(async (_url: string, init?: RequestInit) => {
      expect(init?.signal).toBeInstanceOf(AbortSignal);
      const err = new Error("timed out");
      err.name = "TimeoutError";
      throw err;
    });
    vi.stubGlobal("fetch", fetchSpy);
    const response = await POST(request());
    expect(response.status).toBe(504);
    expect((await response.json()).error.code).toBe("UPSTREAM_TIMEOUT");
  });

  it("does not return an upstream body over the cap", async () => {
    process.env.NEXT_PUBLIC_API_BASE_URL = "https://apex4traders-api.onrender.com";
    vi.stubGlobal("fetch", vi.fn(async () => new Response(new Uint8Array(64), {
      status: 200,
      headers: { "content-type": "application/json", "content-length": String(MAX_WEBHOOK_BYTES + 1) },
    })));
    const response = await POST(request());
    expect(response.status).toBe(502);
    const body = await response.json();
    expect(body.error.code).toBe("INTERNAL_ERROR");
    expect(JSON.stringify(body).length).toBeLessThan(500);
  });

  it("GET is JSON 405, not the homepage", async () => {
    const response = GET();
    expect(response.status).toBe(405);
    expect(response.headers.get("content-type") ?? "").toContain("application/json");
    expect((await response.json()).error.code).toBe("METHOD_NOT_ALLOWED");
  });
});
