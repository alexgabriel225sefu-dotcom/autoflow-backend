import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("./supabase/client", () => ({
  createClient: () => ({
    auth: { getSession: async () => ({ data: { session: { access_token: "tok" } } }) },
  }),
}));

import { deleteAccount, ENDPOINT_NOT_DEPLOYED, exportAccount } from "./api";

function reply(status: number, body: unknown) {
  return Promise.resolve({
    ok: status >= 200 && status < 300, status, json: async () => body,
  } as Response);
}

afterEach(() => vi.unstubAllGlobals());

describe("exportAccount", () => {
  it("GETs account/export with the bearer and returns the payload", async () => {
    const f = vi.fn(() => reply(200, { ok: true, exportedAt: "2026-10-29T10:00:00Z", data: { rules: [1] } }));
    vi.stubGlobal("fetch", f);
    const r = await exportAccount();
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toMatch(/\/api\/v1\/account\/export$/);
    expect(init.method).toBe("GET");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok");
    expect(r.ok && r.data.exportedAt).toBe("2026-10-29T10:00:00Z");
  });

  it("refuses a success whose data is missing", async () => {
    vi.stubGlobal("fetch", vi.fn(() => reply(200, { ok: true, exportedAt: "x" })));
    const r = await exportAccount();
    expect(r.ok).toBe(false);
  });

  it.each([404, 501])("treats %s as not deployed yet, calmly", async (status) => {
    vi.stubGlobal("fetch", vi.fn(() => reply(status, { ok: false, error: { code: "NOT_FOUND", message: "no" } })));
    const r = await exportAccount();
    expect(r.ok).toBe(false);
    if (!r.ok) {
      expect(r.code).toBe(ENDPOINT_NOT_DEPLOYED);
      expect(r.message).toMatch(/not available on this server yet/);
      expect(r.message).toMatch(/nothing was changed/i);
    }
  });

  it("leaves other failures alone", async () => {
    vi.stubGlobal("fetch", vi.fn(() => reply(503, { ok: false, error: { code: "STORE_UNAVAILABLE", message: "down" } })));
    const r = await exportAccount();
    expect(!r.ok && r.code).toBe("STORE_UNAVAILABLE");
  });
});

describe("deleteAccount", () => {
  it("sends DELETE with the confirm body exactly", async () => {
    const f = vi.fn(() => reply(200, { ok: true, deleted: { rules: 2 }, authUserDeleted: true }));
    vi.stubGlobal("fetch", f);
    const r = await deleteAccount("DELETE");
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toMatch(/\/api\/v1\/account$/);
    expect(init.method).toBe("DELETE");
    expect(JSON.parse(init.body as string)).toEqual({ confirm: "DELETE" });
    expect(r.ok && r.data.deleted).toEqual({ rules: 2 });
    expect(r.ok && r.data.authUserDeleted).toBe(true);
  });

  it("reports a missing endpoint calmly and a refusal as itself", async () => {
    vi.stubGlobal("fetch", vi.fn(() => reply(404, {})));
    const a = await deleteAccount("DELETE");
    expect(!a.ok && a.code).toBe(ENDPOINT_NOT_DEPLOYED);
    vi.stubGlobal("fetch", vi.fn(() => reply(400, { ok: false, error: { code: "CONFIRM_REQUIRED", message: "type DELETE" } })));
    const b = await deleteAccount("nope");
    expect(!b.ok && b.code).toBe("CONFIRM_REQUIRED");
  });
});
