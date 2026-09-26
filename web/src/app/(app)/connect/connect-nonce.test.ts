/**
 * The pending nonce survives the tab reload that mobile OAuth guarantees.
 *
 * WHY THIS FILE EXISTS
 *
 * Step 1 of connecting a broker account opens cTrader in a new tab. On a phone,
 * iOS discards the JS state of the backgrounded tab under memory pressure and
 * reloads it when you come back. The nonce lived in React state only, so the
 * page came back showing "Step 1" with no way to finish, the visitor pressed
 * Connect again, and the only visible result was RATE_LIMITED from the oauth
 * bucket — ten requests a minute, easily spent by a page that keeps offering
 * the wrong button.
 *
 * The flow was unfinishable on mobile, and it was found on the first real
 * connection attempt rather than by any test, which is why these exist now.
 *
 * The original code deliberately did NOT persist the nonce, reasoning that a
 * stale one "would invite a completion attempt against an attempt that is long
 * gone". That concern is real, so it is handled rather than traded away: the
 * stored value carries the time it was issued and is ignored past the server's
 * own PENDING_TTL_S. Both halves are asserted below — it must survive a reload,
 * and it must NOT survive past the window.
 */
import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";

const NONCE_KEY = "a4t.ctrader.pending";
const NONCE_TTL_MS = 900_000;

/** The page's own helpers, kept in step with the component by the last test. */
function loadNonce(): string | null {
  try {
    const raw = sessionStorage.getItem(NONCE_KEY);
    if (!raw) return null;
    const { nonce, at } = JSON.parse(raw) as { nonce?: string; at?: number };
    if (!nonce || !at || Date.now() - at > NONCE_TTL_MS) {
      sessionStorage.removeItem(NONCE_KEY);
      return null;
    }
    return nonce;
  } catch {
    return null;
  }
}

function saveNonce(nonce: string | null) {
  try {
    if (nonce === null) sessionStorage.removeItem(NONCE_KEY);
    else sessionStorage.setItem(NONCE_KEY, JSON.stringify({ nonce, at: Date.now() }));
  } catch { /* storage unavailable */ }
}

const NONCE = "rIeFVSuL7_7GOW5NvO5Kuj75X3LmGAABsMcig3kKcbI";

beforeEach(() => {
  sessionStorage.clear();
  vi.useRealTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("the nonce survives what mobile OAuth actually does", () => {
  it("is still there after the tab reloads", () => {
    saveNonce(NONCE);
    // A reload keeps sessionStorage and loses every variable. loadNonce() is
    // what runs on mount, so calling it IS the reload for this purpose.
    expect(loadNonce()).toBe(NONCE);
  });

  it("round-trips a realistic nonce byte for byte", () => {
    // Base64url: the `_` and `-` must not be mangled by the JSON round trip.
    saveNonce(NONCE);
    expect(loadNonce()).toBe(NONCE);
    expect(loadNonce()).toContain("_");
  });

  it("is cleared when the flow finishes, so the page stops offering step 2", () => {
    saveNonce(NONCE);
    saveNonce(null);
    expect(loadNonce()).toBeNull();
    expect(sessionStorage.getItem(NONCE_KEY)).toBeNull();
  });
});

describe("but it does not outlive the server's own window", () => {
  it("is ignored once older than PENDING_TTL_S", () => {
    // Exactly the concern the original comment raised. The server would refuse
    // it with STATE_EXPIRED; the page must not offer the button at all.
    const now = Date.now();
    sessionStorage.setItem(NONCE_KEY, JSON.stringify({
      nonce: NONCE, at: now - NONCE_TTL_MS - 1000,
    }));
    vi.spyOn(Date, "now").mockReturnValue(now);
    expect(loadNonce()).toBeNull();
  });

  it("and is removed from storage when it expires, not merely hidden", () => {
    const now = Date.now();
    sessionStorage.setItem(NONCE_KEY, JSON.stringify({
      nonce: NONCE, at: now - NONCE_TTL_MS - 1000,
    }));
    vi.spyOn(Date, "now").mockReturnValue(now);
    loadNonce();
    expect(sessionStorage.getItem(NONCE_KEY)).toBeNull();
  });

  it("is still valid one second inside the window", () => {
    const now = Date.now();
    sessionStorage.setItem(NONCE_KEY, JSON.stringify({
      nonce: NONCE, at: now - NONCE_TTL_MS + 1000,
    }));
    vi.spyOn(Date, "now").mockReturnValue(now);
    expect(loadNonce()).toBe(NONCE);
  });
});

describe("a broken or hostile stored value never breaks the page", () => {
  for (const [label, raw] of [
    ["not JSON", "{{{"],
    ["JSON but not an object", '"just a string"'],
    ["an object with no nonce", '{"at":1}'],
    ["an object with no timestamp", `{"nonce":"${NONCE}"}`],
    ["an empty nonce", '{"nonce":"","at":9999999999999}'],
    ["null", "null"],
  ] as const) {
    it(`returns null for ${label} rather than throwing`, () => {
      sessionStorage.setItem(NONCE_KEY, raw);
      expect(() => loadNonce()).not.toThrow();
      expect(loadNonce()).toBeNull();
    });
  }

  it("survives sessionStorage throwing outright", () => {
    // Private windows and "block all cookies" make the accessor itself throw.
    const spy = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("access denied");
    });
    expect(() => loadNonce()).not.toThrow();
    expect(loadNonce()).toBeNull();
    spy.mockRestore();

    const spy2 = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("access denied");
    });
    expect(() => saveNonce(NONCE)).not.toThrow();
    spy2.mockRestore();
  });
});

describe("the page and this test do not drift apart", () => {
  // The helpers above are copies. A copy that silently stops matching the
  // component is a test that passes while the product is broken, so the
  // constants and the shape are checked against the source.
  it("uses the same storage key and TTL as the component", async () => {
    const { readFileSync } = await import("node:fs");
    const { join } = await import("node:path");
    const src = readFileSync(
      join(__dirname, "page.tsx"), "utf8");
    expect(src).toContain(`"${NONCE_KEY}"`);
    expect(src).toContain("900_000");
    expect(src).toContain("sessionStorage");
    // localStorage would outlive the tab, which is the lifetime the original
    // comment correctly refused. Matched as a CALL, not as the word: the
    // component's comment explains why localStorage is not used, and a naive
    // substring check fails on that explanation. (It did.)
    expect(src).not.toMatch(/\blocalStorage\s*\.\s*(get|set|remove)Item/);
  });

  it("clears the nonce on a terminal refusal, not just on success", () => {
    // Without this the page offers "finish here" for ever against an attempt
    // the server has already rejected.
    const src = require("node:fs").readFileSync(
      require("node:path").join(__dirname, "page.tsx"), "utf8");
    for (const code of ["STATE_UNKNOWN", "STATE_EXPIRED", "STATE_REPLAYED"]) {
      expect(src).toContain(code);
    }
    expect(src).toMatch(/TERMINAL\.has\(r\.code\)/);
  });
});
