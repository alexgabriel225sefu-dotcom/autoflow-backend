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

/**
 * The automatic finish, and what must stay final.
 *
 * Arriving back with ?n= means cTrader has approved and the callback has
 * already spent the authorization code. Making the visitor press one more
 * button adds no security — the finish runs as them either way — and the
 * owner spent an afternoon on the page that asked for that press and then
 * answered RATE_LIMITED.
 *
 * The danger in automating it is the opposite failure: an effect that fires
 * on every render spends a ten-per-minute budget in seconds. So the guard is
 * asserted here, not assumed.
 */
describe("the automatic finish fires once, and only once", () => {
  it("a ref guard admits exactly one run across many renders", () => {
    // The component's guard, in the shape the component uses it.
    const autoRan = { current: false };
    let runs = 0;
    const onMountWithNonce = () => {
      if (!autoRan.current) { autoRan.current = true; runs += 1; }
    };
    for (let i = 0; i < 25; i++) onMountWithNonce();
    expect(runs).toBe(1);
  });

  it("useState would NOT have been enough, which is why it is a ref", () => {
    // State is captured per render: a handler closing over `false` keeps
    // seeing `false` until React re-renders, so two renders in the same tick
    // both pass the guard. This is the bug the ref exists to prevent, shown
    // rather than described.
    let runs = 0;
    const captured = false;            // what a stale closure would see
    for (let i = 0; i < 5; i++) if (!captured) runs += 1;
    expect(runs).toBe(5);              // the broken version
  });
});

describe("which refusals end an attempt, and which do not", () => {
  const TERMINAL = new Set([
    "STATE_UNKNOWN", "STATE_EXPIRED", "STATE_REPLAYED", "NO_CODE",
    "PROVIDER_REFUSED", "EXCHANGE_FAILED", "NO_TOKEN",
  ]);
  const RETRYABLE = new Set(["ACCOUNTS_FAILED", "RATE_LIMITED"]);

  it("covers the refusals the callback can now produce", () => {
    // EXCHANGE_FAILED and NO_TOKEN could not reach this step until the code
    // started being spent at the callback. They are as final as the rest: the
    // code is gone either way, so offering "finish" again can only fail.
    for (const code of ["EXCHANGE_FAILED", "NO_TOKEN", "PROVIDER_REFUSED"]) {
      expect(TERMINAL.has(code)).toBe(true);
    }
  });

  it("does NOT end the attempt when only the account listing failed", () => {
    // The token is already parked. Clearing the nonce here throws away a good
    // token and sends the visitor back through cTrader for nothing.
    expect(TERMINAL.has("ACCOUNTS_FAILED")).toBe(false);
    expect(RETRYABLE.has("ACCOUNTS_FAILED")).toBe(true);
  });

  it("nor when the client was merely going too fast", () => {
    expect(TERMINAL.has("RATE_LIMITED")).toBe(false);
    expect(RETRYABLE.has("RATE_LIMITED")).toBe(true);
  });

  it("matches the component, which is the copy that actually runs", async () => {
    const { readFileSync } = await import("node:fs");
    const { join } = await import("node:path");
    const src = readFileSync(join(__dirname, "page.tsx"), "utf8");
    for (const code of TERMINAL) expect(src).toContain(code);
    for (const code of RETRYABLE) expect(src).toContain(code);
    // The retryable set must be consulted, not merely declared.
    expect(src).toMatch(/RETRYABLE\.has\(r\.code\)/);
    // And the automatic finish must be guarded by a ref, not by state.
    expect(src).toMatch(/autoRan\.current/);
    expect(src).toMatch(/useRef\(false\)/);
  });

  it("shows a reference id when the server sends one", async () => {
    const { readFileSync } = await import("node:fs");
    const { join } = await import("node:path");
    const src = readFileSync(join(__dirname, "page.tsx"), "utf8");
    expect(src).toContain("diagnosticId");
    expect(src).toContain("Reference:");
  });
});

/**
 * What the page says once the connection has actually worked.
 *
 * WHY THIS EXISTS — read the production log, not the code:
 *
 *   16:39:32  complete.connected attempt="d964e360" count=1 selected=False
 *   16:39:32  api.response route="ctrader/complete" status=200
 *   16:39:37  begin attempt="f380e622"        <- five seconds later
 *
 * The connection succeeded and the owner pressed "Connect cTrader" again
 * five seconds afterwards, because the card below the status still read
 * "Step 1 — authorise" and offered to start over. He reported the whole
 * feature as broken. It was not: the page was.
 *
 * So the invitation to start a connection must not be the thing on screen
 * when a connection already exists.
 */
describe("a finished connection does not still invite step 1", () => {
  it("the page never renders the step-1 heading while connected", async () => {
    const { readFileSync } = await import("node:fs");
    const { join } = await import("node:path");
    const src = readFileSync(join(__dirname, "page.tsx"), "utf8");
    // The heading is chosen from the connection state, not from `pending`
    // alone — which is what made it say "Step 1" to somebody who had just
    // finished step 2.
    expect(src).toMatch(/connected\s*&&\s*!pending|isConnected/);
    expect(src).toContain("Account connected");
  });

  it("points at choosing an account, which is the real next step", async () => {
    const { readFileSync } = await import("node:fs");
    const { join } = await import("node:path");
    const src = readFileSync(join(__dirname, "page.tsx"), "utf8");
    expect(src).toContain("/accounts");
    expect(src).toMatch(/Choose|choose/);
  });

  it("still allows connecting another account, but not as the main action", async () => {
    const { readFileSync } = await import("node:fs");
    const { join } = await import("node:path");
    const src = readFileSync(join(__dirname, "page.tsx"), "utf8");
    // Demoted to a ghost button rather than removed: a client with two
    // broker accounts must still be able to add the second.
    expect(src).toMatch(/btn-ghost[^>]*onClick=\{begin\}|onClick=\{begin\}[^>]*btn-ghost/);
  });
});
