/**
 * Alerts is the other place a Signals Only client reads their signals, and the
 * one that tells them a setup happened at all.
 *
 * The journal is the durable record; this list is the interruption. It is
 * capped at 500 rows across every type, so the two things it has to do are
 * say plainly that nothing was placed — a row titled "Buy setup: EURUSD" is
 * one word away from reading as a position — and offer a way through to the
 * record that outlives it.
 */
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ApiResult, Notification } from "@/lib/api";

let routes: Record<string, unknown> = {};

vi.mock("next/navigation", () => ({
  usePathname: () => "/notifications",
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

import NotificationsPage from "./page";

/** Exactly what `signals.deliver` writes, as the API serves it. */
const SIGNAL: Notification = {
  id: "n1", type: "signal", level: "info",
  title: "Buy setup: EURUSD",
  body: "Buy EURUSD · around 1.08421 · confidence 72%. "
      + "RSI 28 with price above the 200 EMA. "
      + "Nothing was placed — this rule runs at Signals Only. "
      + "Place it yourself at your broker, or not at all.",
  ts: 1760000000, readAt: null, link: "/journal",
};

const SYSTEM: Notification = {
  id: "n2", type: "system", level: "info", title: "Automation started",
  body: "Running my rule on demo account 901.", ts: 1760000001, readAt: null,
  link: null,
};

function page(rows: Notification[]) {
  routes = {
    notifications: {
      ok: true,
      data: { status: "ok", notifications: rows, total: rows.length,
              unread: rows.filter((r) => !r.readAt).length, hasMore: false },
    },
  };
}

async function show() {
  await act(async () => { render(<NotificationsPage />); });
  await act(async () => { await Promise.resolve(); await Promise.resolve(); });
}

function row(): string {
  return document.querySelector(".record")?.textContent ?? "";
}

beforeEach(() => { page([SIGNAL]); });
afterEach(() => vi.clearAllMocks());

describe("a signal alert", () => {
  it("says what the setup is", async () => {
    await show();
    expect(row()).toContain("Buy setup: EURUSD");
    expect(row()).toContain("1.08421");
  });

  it("says nothing was placed, in the row itself", async () => {
    await show();
    // Not in a tooltip and not on another screen. A client scanning this list
    // has to be able to tell a signal from a position without opening
    // anything.
    expect(row()).toContain("Nothing was placed");
    expect(row()).toContain("Place it yourself");
  });

  it("offers the way through to the durable record", async () => {
    await show();
    // This list holds 500 rows across every type; the journal holds the
    // setups. A signal with no route to the journal is a signal that expires.
    const link = document.querySelector<HTMLAnchorElement>(".record a");
    expect(link?.getAttribute("href")).toBe("/journal");
  });

  it("and no such link on an alert that has nowhere to go", async () => {
    page([SYSTEM]);
    await show();
    expect(document.querySelector(".record a")).toBeNull();
  });
});

describe("the type filter", () => {
  it("offers Signal", async () => {
    await show();
    // Without it, the only thing a Signals Only client's rule did today is
    // mixed in with licence and account notices.
    expect(screen.getByRole("button", { name: "Signal" })).toBeTruthy();
  });
});
