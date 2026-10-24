/**
 * The API client's job is to keep failure and emptiness apart.
 *
 * Every check below is one way a screen could end up telling a client
 * something reassuring about an account nobody actually reached.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const session = { access_token: "test-token" };
let sessionValue: { access_token: string } | null = session;

vi.mock("./supabase/client", () => ({
  createClient: () => ({
    auth: { getSession: async () => ({ data: { session: sessionValue } }) },
  }),
}));

import { api, CODES } from "./api";

function reply(status: number, body: unknown) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response);
}

describe("api()", () => {
  beforeEach(() => { sessionValue = session; });
  afterEach(() => { vi.restoreAllMocks(); });

  it("sends the Supabase token as a bearer and nothing else", async () => {
    const fetchMock = vi.fn(() => reply(200, { ok: true, user: { userId: "u" } }));
    vi.stubGlobal("fetch", fetchMock);
    await api("me");
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer test-token");
    expect(JSON.stringify(headers)).not.toContain("Cookie");
  });

  it("refuses before the network when there is no session", async () => {
    sessionValue = null;
    const fetchMock = vi.fn(() => reply(200, { ok: true }));
    vi.stubGlobal("fetch", fetchMock);
    const r = await api("me");
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.code).toBe(CODES.AUTH_REQUIRED);
    // The point: an unauthenticated read must not reach the backend at all.
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each([
    [401, "AUTH_REQUIRED"],
    [403, "FORBIDDEN"],
    [404, "NOT_FOUND"],
    [409, "ALREADY_RUNNING"],
    [422, "INSUFFICIENT_DATA"],
    [501, "UNSUPPORTED"],
    [503, "AUTH_UNAVAILABLE"],
  ])("maps HTTP %i to its backend code", async (status, code) => {
    vi.stubGlobal("fetch", () => reply(status, {
      ok: false, error: { code, message: "nope" },
    }));
    const r = await api("anything");
    expect(r.ok).toBe(false);
    if (!r.ok) {
      expect(r.status).toBe(status);
      expect(r.code).toBe(code);
    }
  });

  it("treats a network failure as its own code, never as empty data", async () => {
    vi.stubGlobal("fetch", () => Promise.reject(new Error("offline")));
    const r = await api<{ positions: [] }>("positions");
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.code).toBe(CODES.NETWORK);
    // Nothing a caller could read as "no positions".
    expect((r as { data?: unknown }).data).toBeUndefined();
  });

  it("treats ok:false in a 200 body as a failure", async () => {
    // The backend answers 200 with ok:false on some refusals; taking the
    // HTTP status alone would render that as success.
    vi.stubGlobal("fetch", () => reply(200, {
      ok: false, error: { code: "LICENCE_REQUIRED", message: "no licence", licenceState: "none" },
    }));
    const r = await api("rules/x/activate", { method: "POST" });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.licenceState).toBe("none");
  });

  it("carries validation problems through so a form can show them", async () => {
    vi.stubGlobal("fetch", () => reply(422, {
      ok: false,
      error: { code: "RULE_INVALID", message: "invalid", problems: ["symbols: required"] },
    }));
    const r = await api("rules/x/activate", { method: "POST" });
    if (!r.ok) expect(r.problems).toEqual(["symbols: required"]);
    else throw new Error("should have failed");
  });
});
