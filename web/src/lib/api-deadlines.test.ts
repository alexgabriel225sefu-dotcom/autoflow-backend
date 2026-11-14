/**
 * A read that never answers must end as an error the page can show.
 *
 * SEEN ON A PHONE: several authenticated pages stayed on "Account · Loading"
 * and never restored the selected demo account. The session lookup (which can
 * wait on a storage lock held by another tab, or on a token refresh over a
 * connection that has just changed) and the request itself had no deadline, so
 * a stuck one produced a skeleton for ever — indistinguishable from "still
 * loading", and offering nothing to retry.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

let getSession: () => Promise<{ data: { session: { access_token: string } | null } }>;

vi.mock("./supabase/client", () => ({
  createClient: () => ({ auth: { getSession: () => getSession() } }),
}));

import { api, CODES, REQUEST_TIMEOUT_MS, SESSION_TIMEOUT_MS } from "./api";

beforeEach(() => {
  vi.useFakeTimers();
  getSession = async () => ({ data: { session: { access_token: "t" } } });
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

describe("the session lookup has a deadline", () => {
  it("a session that never resolves becomes AUTH_UNAVAILABLE, not a hang", async () => {
    getSession = () => new Promise(() => {});          // never settles
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    let result: Awaited<ReturnType<typeof api>> | undefined;
    void api("ctrader/status").then((r) => { result = r; });
    await vi.advanceTimersByTimeAsync(SESSION_TIMEOUT_MS - 1);
    expect(result, "answered before the deadline").toBeUndefined();
    await vi.advanceTimersByTimeAsync(1);
    expect(result).toBeDefined();
    expect(result!.ok).toBe(false);
    expect(!result!.ok && result!.code).toBe(CODES.AUTH_UNAVAILABLE);
    expect(!result!.ok && result!.message).toMatch(/could not be confirmed in time/);
    expect(fetchMock, "no request without a confirmed session").not.toHaveBeenCalled();
  });

  it("a prompt session is not delayed and sends the bearer", async () => {
    const fetchMock = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ ok: true }) }) as Response);
    vi.stubGlobal("fetch", fetchMock);
    const r = await api("me");
    expect(r.ok).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("no session at all is still AUTH_REQUIRED (sign in), not a timeout", async () => {
    getSession = async () => ({ data: { session: null } });
    const r = await api("me");
    expect(!r.ok && r.code).toBe(CODES.AUTH_REQUIRED);
  });
});

describe("the request has a deadline", () => {
  it("a request that never answers becomes a NETWORK error that says it took too long", async () => {
    vi.stubGlobal("fetch", vi.fn((_url: string, init: RequestInit) => new Promise((_res, rej) => {
      init.signal?.addEventListener("abort", () => rej(new DOMException("aborted", "AbortError")));
    })));
    let result: Awaited<ReturnType<typeof api>> | undefined;
    void api("positions").then((r) => { result = r; });
    await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS - 1);
    expect(result).toBeUndefined();
    await vi.advanceTimersByTimeAsync(1);
    expect(result).toBeDefined();
    expect(!result!.ok && result!.code).toBe(CODES.NETWORK);
    expect(!result!.ok && result!.message).toMatch(/took too long/);
  });

  it("a caller that aborts still ends the request (it is not turned into a timeout)", async () => {
    vi.stubGlobal("fetch", vi.fn((_url: string, init: RequestInit) => new Promise((_res, rej) => {
      init.signal?.addEventListener("abort", () => rej(new DOMException("aborted", "AbortError")));
    })));
    const ctl = new AbortController();
    let result: Awaited<ReturnType<typeof api>> | undefined;
    void api("positions", { signal: ctl.signal }).then((r) => { result = r; });
    await vi.advanceTimersByTimeAsync(10);
    ctl.abort();
    await vi.advanceTimersByTimeAsync(0);
    expect(result).toBeDefined();
    expect(!result!.ok && result!.message).not.toMatch(/took too long/);
  });

  it("a fast answer clears its timer", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ ok: true }) }) as Response));
    await api("me");
    expect(vi.getTimerCount()).toBe(0);
  });
});


describe("a request may be given its own deadline and its own words", () => {
  it("a close that outlasts the default is not cut at 25 s", async () => {
    vi.stubGlobal("fetch", vi.fn((_u: string, init: RequestInit) => new Promise((_res, rej) => {
      init.signal?.addEventListener("abort", () => rej(new DOMException("aborted", "AbortError")));
    })));
    let result: Awaited<ReturnType<typeof api>> | undefined;
    void api("accounts/1/positions/7/close", { method: "POST", timeoutMs: 90_000,
      timeoutMessage: "No answer yet — the close may still complete." }).then((r) => { result = r; });
    await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS + 5_000);
    expect(result, "cut at the default deadline").toBeUndefined();
    await vi.advanceTimersByTimeAsync(90_000 - REQUEST_TIMEOUT_MS);
    expect(result).toBeDefined();
    expect(!result!.ok && result!.message).toBe("No answer yet — the close may still complete.");
    expect(!result!.ok && result!.message).not.toMatch(/check your connection/);
  });
});
