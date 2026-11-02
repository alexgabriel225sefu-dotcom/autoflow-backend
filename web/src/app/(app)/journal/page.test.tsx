/**
 * The journal is where a Signals Only client reads what their rule found.
 *
 * WHAT THIS SCREEN HAS TO GET RIGHT, AND WHY IT IS EASY TO GET WRONG
 *
 * A signal row and an executed row are rendered by the same component, from
 * the same `decision` shape, and a signal's title is the side — "BUY". So the
 * two look alike, and the difference between them is the entire product at
 * this level: one is a position the client now has, the other is a setup
 * nobody acted on and nobody will unless they do it themselves.
 *
 * The tests below assert the row says so, that the price a client needs in
 * order to act on it survives to the screen, and that the status filter can
 * reach these rows at all — without the filter value, a signals client's own
 * signals are only findable by scrolling past every evaluation that held.
 */
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ApiResult, JournalEntry } from "@/lib/api";

let routes: Record<string, unknown> = {};

vi.mock("next/navigation", () => ({
  usePathname: () => "/journal",
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));

vi.mock("@/lib/api", async (orig) => {
  const actual = await orig<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: vi.fn(async (path: string) => {
      const key = Object.keys(routes)
        .sort((a, b) => b.length - a.length)
        .find((k) => path.startsWith(k));
      if (!key) return { ok: false, status: 404, code: "NOT_FOUND", message: "no stub" };
      return routes[key] as ApiResult<unknown>;
    }),
  };
});

import JournalView from "./page";

/** Exactly what `journal.for_signal` writes, as the API serves it. */
const SIGNAL: JournalEntry = {
  entryId: "e1", kind: "evaluation", status: "signal", ts: 1760000000,
  symbol: "EURUSD", accountId: "901", ruleDocId: "rule-1",
  correlationId: "c1",
  snapshot: { symbol: "EURUSD", price: 1.08421 },
  decision: {
    verdict: "BUY", reason: "RSI 28 with price above the 200 EMA.",
    conditions: [{ id: "RSI oversold", passed: null, detail: "" }],
    executable: false, refusalCode: null, confidence: 72,
  },
};

/** A real order, for contrast: same shape, same title, opposite meaning. */
const CONFIRMED: JournalEntry = {
  entryId: "e2", kind: "execution", status: "order_confirmed",
  ts: 1760000001, symbol: "EURUSD", accountId: "901", ruleDocId: "rule-1",
  correlationId: "c2",
  decision: {
    verdict: "BUY", reason: "sent", conditions: [],
    executable: true, refusalCode: null, confidence: 72,
  },
};

const LEGACY_ENGINE_REFUSAL: JournalEntry = {
  entryId: "e3", kind: "control", status: "broker_error", ts: 1760000002,
  symbol: null, accountId: "901", ruleDocId: null, correlationId: "c3",
  error: "the engine refused to start this loop (the starter returned a refusal)",
};

function page(entries: JournalEntry[]) {
  routes = {
    journal: {
      ok: true,
      data: { status: "ok", entries, total: entries.length, limit: 25,
              offset: 0, hasMore: false },
    },
  };
}

async function show() {
  await act(async () => { render(<JournalView />); });
  await act(async () => { await Promise.resolve(); await Promise.resolve(); });
}

/** The first entry's own text.
 *
 * Scoped to the record rather than read off the whole page, because the status
 * filter is a <select> listing every status by name — so "Order Confirmed" is
 * in the document on every render, and an assertion over the page body could
 * never tell a row apart from the dropdown above it. */
function row(): string {
  return document.querySelector(".record")?.textContent ?? "";
}

beforeEach(() => { page([SIGNAL]); });
afterEach(() => vi.clearAllMocks());

describe("a signal row", () => {
  it("says nothing was placed and that the client trades it", async () => {
    await show();
    const text = row();
    expect(text).toContain("Signal only");
    expect(text).toContain("nothing placed");
    // The sentence that stops a client reading their own signal as a
    // position. "No order placed" alone is true of a hold as well, and a hold
    // means there is nothing to do.
    expect(text).toContain("you trade it");
  });

  it("carries the price the setup qualified at", async () => {
    await show();
    // At this level the client places the order, so without the level there
    // is nothing to act on.
    expect(row()).toContain("1.08421");
  });

  it("says so rather than inventing one when the engine had no price", async () => {
    page([{ ...SIGNAL, snapshot: { symbol: "EURUSD", price: null } }]);
    await show();
    const text = row();
    expect(text).toContain("entry price unavailable");
    // A missing price must not render as 0 — a signal to buy at zero is a
    // sentence that reads as information and is not.
    expect(text).not.toContain("entry around 0");
  });

  it("still shows the side and the reasoning", async () => {
    await show();
    const text = row();
    expect(text).toContain("BUY");
    expect(text).toContain("RSI 28 with price above the 200 EMA.");
  });

  it("does not claim a signal was an order", async () => {
    await show();
    const text = row();
    expect(text).not.toContain("Order Confirmed");
    expect(text).not.toContain("Order Sent");
  });
});

describe("an executed row is not dressed as a signal", () => {
  it("keeps the signal wording off a confirmed order", async () => {
    page([CONFIRMED]);
    await show();
    const text = row();
    expect(text).not.toContain("Signal only");
    expect(text).not.toContain("No order placed");
  });
});

describe("legacy engine refusals", () => {
  it("shows Engine error instead of blaming the broker", async () => {
    page([LEGACY_ENGINE_REFUSAL]);
    await show();
    expect(row()).toContain("Engine error");
    expect(row()).not.toContain("Broker Error");
    expect(row()).toContain("the engine refused to start this loop");
  });
});

describe("the status filter", () => {
  it("offers signal, so a client can ask for just those", async () => {
    await show();
    const select = screen.getByLabelText("Status", { selector: "select" })
      ?? screen.getAllByRole("combobox")[0];
    const values = Array.from(
      (select as HTMLSelectElement).options).map((o) => o.value);
    // Without this value the only way to find a signal is to page through
    // every evaluation that held, and holds outnumber signals by orders of
    // magnitude.
    expect(values).toContain("signal");
  });
});

describe("a page the server could not fully read", () => {
  function partial(entries: JournalEntry[], unreadable: number, total: number) {
    routes = {
      journal: {
        ok: true,
        data: { status: "ok", entries, total, limit: 25, offset: 0,
                hasMore: false, unreadable },
      },
    };
  }

  it("says the page is incomplete instead of looking complete", async () => {
    partial([SIGNAL], 2, 3);
    await show();
    const text = document.body.textContent ?? "";
    expect(text).toContain("This page is incomplete");
    expect(text).toContain("2 entries");
    expect(text).toContain("Nothing was deleted");
    // The rows that WERE read are still shown.
    expect(document.querySelectorAll(".record").length).toBe(1);
  });

  it("uses the singular for one entry", async () => {
    partial([SIGNAL], 1, 2);
    await show();
    expect(document.body.textContent).toContain("1 entry on this page");
  });

  it("never says 'nothing recorded' when entries exist but could not be read", async () => {
    partial([], 3, 3);
    await show();
    const text = document.body.textContent ?? "";
    expect(text).toContain("This page is incomplete");
    expect(text).not.toContain("Nothing recorded for this filter");
  });

  it("stays quiet when nothing was missed, and when the server predates the field", async () => {
    partial([SIGNAL], 0, 1);
    await show();
    expect(document.body.textContent).not.toContain("This page is incomplete");
    page([SIGNAL]); // no `unreadable` key at all
    await show();
    expect(document.body.textContent).not.toContain("This page is incomplete");
  });
});
