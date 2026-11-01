/**
 * The status strip's one rule: never claim a state it does not have.
 *
 * This component was untested, and on 2026-10-02 it showed the owner's phone
 * "no cTrader account is connected" for the only account in the system — an
 * account whose link record was intact. The lie came from the API (a store
 * read that failed answered as an empty record, since fixed), but the strip
 * had its own, quieter version of the same bug: a failed read and a read
 * still in flight both arrived as a null payload, so an API error rendered
 * the loading shimmer for ever.
 *
 * Both are states the strip must not invent. The tests below assert the
 * three-way distinction — answered / still asking / could not ask — for both
 * the account chip and the automation chip, which is the one that says
 * whether something is placing orders.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StatusBar } from "./status-bar";
import type { ApiError, AutomationState, CtraderStatus, Me } from "@/lib/api";

const DOWN: ApiError = {
  ok: false, status: 503, code: "STORE_UNAVAILABLE",
  message: "upstash GET failed: ReadTimeout",
};

const CONNECTED: CtraderStatus = {
  connected: true, accounts: [], liveAllowed: false,
  selected: { ctid: "47765456", mode: "demo" },
} as unknown as CtraderStatus;

const NOTHING: CtraderStatus = {
  connected: false, accounts: [], selected: null, liveAllowed: false,
} as unknown as CtraderStatus;

const STOPPED = { state: "stopped" } as unknown as AutomationState;
const ME = { licence: { state: "active" } } as unknown as Me;

function strip(ct: unknown, auto: unknown = { ok: true, data: STOPPED }) {
  render(<StatusBar me={{ ok: true, data: ME }} ct={ct as never} auto={auto as never} />);
  return screen.getByRole("status");
}

describe("the account chip", () => {
  it("shows the account when the API answered with one", () => {
    expect(strip({ ok: true, data: CONNECTED }).textContent)
      .toContain("47765456");
  });

  it("says not connected only when the API said so", () => {
    expect(strip({ ok: true, data: NOTHING }).textContent)
      .toContain("Not connected");
  });

  it("says Unknown — not 'not connected' — when the read failed", () => {
    const text = strip(DOWN).textContent ?? "";
    expect(text).toContain("Unknown");
    // The whole point. A 503 must never render as a claim about the account.
    expect(text).not.toContain("Not connected");
    expect(text).not.toContain("47765456");
  });

  it("and a read still in flight is not Unknown either", () => {
    // null is "we have not asked yet", which is a shimmer, not a verdict.
    expect(strip(null).textContent ?? "").not.toContain("Unknown");
  });
});

describe("the automation chip", () => {
  it("reports the state the API gave", () => {
    expect(strip({ ok: true, data: CONNECTED }, { ok: true, data: STOPPED })
      .textContent).toContain("STOPPED");
  });

  it("says Unknown when it could not be read, never STOPPED", () => {
    const text = strip({ ok: true, data: CONNECTED }, DOWN).textContent ?? "";
    expect(text).toContain("Unknown");
    // Reading a failed automation query as "stopped" is the dangerous
    // direction: it tells the operator nothing is running when something
    // may well be.
    expect(text).not.toContain("STOPPED");
  });
});

/**
 * RUNNING is the same word for all three engine levels, and they differ by
 * whether a setup becomes an order. At Signals Only the loop places nothing by
 * design — so RUNNING on its own tells a client the opposite of what is true,
 * and this strip is where they read it.
 */
describe("the level chip, which says what RUNNING means", () => {
  const RUNNING_SIGNALS = {
    state: "running", ruleDocId: "r1", mode: "demo", startedAt: 1,
    level: "signals", levelLabel: "Signals Only",
    levelBlurb: "I tell you about every setup I find and place nothing.",
    levelExecutes: false,
  } as unknown as AutomationState;

  const RUNNING_FULL = {
    state: "running", ruleDocId: "r1", mode: "demo", startedAt: 1,
    level: "full", levelLabel: "Full Automation",
    levelBlurb: "I open and manage trades on my own.",
    levelExecutes: true,
  } as unknown as AutomationState;

  it("names a running level that does not place orders", () => {
    const text = strip({ ok: true, data: CONNECTED },
                       { ok: true, data: RUNNING_SIGNALS }).textContent ?? "";
    expect(text).toContain("RUNNING");
    // The whole point: RUNNING must not be the only thing on the strip for a
    // level that trades nothing.
    expect(text).toContain("Signals Only");
  });

  it("stays quiet for a level that does place orders", () => {
    // Full Automation needs no qualifier — RUNNING already means what the
    // client expects, and a chip on every screen that says nothing new is a
    // chip people stop reading.
    const text = strip({ ok: true, data: CONNECTED },
                       { ok: true, data: RUNNING_FULL }).textContent ?? "";
    expect(text).toContain("RUNNING");
    expect(text).not.toContain("Full Automation");
  });

  it("shows no level when nothing is running", () => {
    const text = strip({ ok: true, data: CONNECTED },
                       { ok: true, data: STOPPED }).textContent ?? "";
    expect(text).not.toContain("Signals Only");
    expect(text).not.toContain("Level");
  });

  it("does not decide for itself which levels trade", () => {
    // `levelExecutes` absent is the old API answering, and a browser that
    // inferred "signals does not execute" from the level NAME would be a
    // second copy of a decision about money. Absent means unanswered, so the
    // chip stays off rather than guessing.
    const text = strip({ ok: true, data: CONNECTED }, {
      ok: true,
      data: { state: "running", ruleDocId: "r1", level: "signals",
              levelLabel: "Signals Only" } as unknown as AutomationState,
    }).textContent ?? "";
    expect(text).not.toContain("Signals Only");
  });
});

describe("the Risk Guard chip", () => {
  const running = (riskGuard?: unknown) => ({
    ok: true,
    data: { state: "running", ruleDocId: "r1", riskGuard } as unknown as AutomationState,
  });
  const text = (auto: unknown) => strip({ ok: true, data: CONNECTED }, auto).textContent ?? "";

  it("shows HOLDING with its reasons when the guard is holding", () => {
    const t = text(running({ state: "holding", reasons: ["daily loss limit"] }));
    expect(t).toContain("Risk Guard");
    expect(t).toContain("HOLDING");
    expect(document.querySelector('[title="daily loss limit"]')).not.toBeNull();
  });

  it("shows Active only when the guard reported ok", () => {
    expect(text(running({ state: "ok", reasons: [] }))).toContain("Active");
  });

  it("a guard that has not reported is 'No report yet' — never Active", () => {
    const t = text(running({ state: "unknown", reasons: [] }));
    expect(t).toContain("No report yet");
    expect(t).not.toContain("Active");
  });

  // The loop idles through the weekend close window before it publishes a
  // report, so a loop revived on a Saturday has none. Saying so is honest;
  // saying "Active" would not be, and "No report yet" reads as a failed guard.
  const weekend = (marketClosed: unknown) => ({
    ok: true,
    data: { state: "running", ruleDocId: "r1", marketClosed,
            riskGuard: { state: "unknown", reasons: [] } } as unknown as AutomationState,
  });

  it("says the market is closed when the guard is silent because of the weekend", () => {
    const t = text(weekend(true));
    expect(t).toContain("Market closed");
    expect(t).not.toContain("Active");
    expect(t).not.toContain("No report yet");
  });

  it.each([[false], [null], [undefined]])(
    "keeps 'No report yet' when the server said marketClosed=%s",
    (value) => {
      const t = text(weekend(value));
      expect(t).toContain("No report yet");
      expect(t).not.toContain("Market closed");
    },
  );

  it("never lets a closed market turn a HOLDING guard into a calm one", () => {
    const t = text({
      ok: true,
      data: { state: "running", ruleDocId: "r1", marketClosed: true,
              riskGuard: { state: "holding", reasons: ["daily loss limit"] } } as unknown as AutomationState,
    });
    expect(t).toContain("HOLDING");
    expect(t).not.toContain("Market closed");
  });

  it("is not shown at all when nothing is running (there is no report to show)", () => {
    expect(text({ ok: true, data: { state: "stopped", riskGuard: { state: "unknown", reasons: [] } } }))
      .not.toContain("Risk Guard");
  });

  it("is not invented when the server sent no guard block", () => {
    expect(text(running(undefined))).not.toContain("Risk Guard");
  });

  it("shows the weekend sentence the server sent, and not a running loop", () => {
    const t = text({
      ok: true,
      data: {
        state: "blocked",
        blockReason: "the licence is not active, so automation is not running",
        marketMessage: "Market closed (weekend), reopens Sun 22:00 UTC",
      } as unknown as AutomationState,
    });
    expect(t).toContain("BLOCKED");
    expect(t).not.toContain("RUNNING");
    expect(t).toContain("Market closed (weekend), reopens Sun 22:00 UTC");
  });
});
