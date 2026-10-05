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
