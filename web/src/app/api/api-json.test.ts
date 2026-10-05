import { describe, expect, it } from "vitest";
import { apiError, methodNotAllowed, withApiJson } from "./_json";
import { GET as missing } from "./not-found";
import { GET as checkoutGet } from "./create-payment-intent/route";

async function bodyOf(response: Response) {
  return response.json() as Promise<{ ok: false; error: { code: string; message: string } }>;
}

describe("API JSON errors", () => {
  it("answers JSON for a route that does not exist", async () => {
    const response = missing();
    expect(response.status).toBe(404);
    expect(response.headers.get("content-type") ?? "").toContain("application/json");
    expect(await bodyOf(response)).toMatchObject({ ok: false, error: { code: "NOT_FOUND" } });
  });

  it("answers JSON for a wrong method", async () => {
    const response = checkoutGet();
    expect(response.status).toBe(405);
    expect(response.headers.get("content-type") ?? "").toContain("application/json");
    expect(await bodyOf(response)).toMatchObject({ ok: false, error: { code: "METHOD_NOT_ALLOWED" } });
  });

  it("answers JSON when a handler raises", async () => {
    const response = await withApiJson(() => {
      throw new Error("boom with internals");
    });
    expect(response.status).toBe(500);
    expect(response.headers.get("content-type") ?? "").toContain("application/json");
    const body = await bodyOf(response);
    expect(body).toMatchObject({ ok: false, error: { code: "INTERNAL_ERROR" } });
    expect(JSON.stringify(body)).not.toContain("boom with internals");
  });

  it("uses the same error envelope helper everywhere", async () => {
    const response = apiError(401, "AUTH_REQUIRED", "Sign in required.");
    expect(response.status).toBe(401);
    expect(await bodyOf(response)).toEqual({ ok: false, error: { code: "AUTH_REQUIRED", message: "Sign in required." } });
  });

  it("keeps wrong-method responses on the shared helper", async () => {
    const response = methodNotAllowed("POST");
    expect(response.status).toBe(405);
    expect(await bodyOf(response)).toMatchObject({ ok: false, error: { code: "METHOD_NOT_ALLOWED" } });
  });
});
