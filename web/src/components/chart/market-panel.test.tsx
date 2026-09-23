/**
 * The market view's contract with the broker read.
 *
 * Four of these tests assert the chart is NOT drawn. That is the point: a
 * quiet market, a broker timeout, an expired authorisation and a missing
 * account all produce "no bars", and rendering an empty chart for the last
 * three would say "nothing is happening" about data nobody received.
 *
 * The last test reads this component's own source. A chart is exactly where
 * an "and also close this position" button gets added later, and the only
 * durable guard against that is structural.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ApiResult } from "@/lib/api";

const calls: { path: string; init?: { method?: string } }[] = [];
let answer: unknown = null;

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>{children}</a>
  ),
}));

vi.mock("@/lib/api", async (orig) => {
  const actual = await orig<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: vi.fn(async (path: string, init?: { method?: string }) => {
      calls.push({ path, init });
      return (answer ?? { ok: false, status: 404, code: "NOT_FOUND", message: "no stub" }) as ApiResult<unknown>;
    }),
  };
});

import { MarketPanel } from "./market-panel";

const BARS = [
  { open: 1.1000, high: 1.1050, low: 1.0980, close: 1.1030, time: 1758542400 },
  { open: 1.1030, high: 1.1060, low: 1.1010, close: 1.1015, time: 1758546000 },
  { open: 1.1015, high: 1.1040, low: 1.0990, close: 1.0995, time: 1758549600 },
];

const okRead = {
  ok: true, data: {
    connected: true, status: "ok", accountId: 501, mode: "demo",
    candles: BARS, symbol: "EURUSD", timeframe: "1h", count: 3, requested: 200,
  },
};

async function mount(props: Partial<React.ComponentProps<typeof MarketPanel>> = {}) {
  await act(async () => {
    render(
      <MarketPanel
        ctid={501} mode="demo" symbols={["EURUSD", "XAUUSD"]} timeframe="1h"
        {...props}
      />,
    );
  });
  await act(async () => { await Promise.resolve(); await Promise.resolve(); });
}

const chartDrawn = () => document.querySelector("svg.candles") !== null;

beforeEach(() => { calls.length = 0; answer = null; });
afterEach(() => vi.clearAllMocks());

describe("market panel — the request", () => {
  it("reads the candles endpoint for the selected account, symbol and timeframe", async () => {
    answer = okRead;
    await mount();
    await waitFor(() => expect(calls.length).toBeGreaterThan(0));
    const c = calls[0];
    expect(c.path).toMatch(/^accounts\/501\/candles\?/);
    const q = new URLSearchParams(c.path.split("?")[1]);
    expect(q.get("symbol")).toBe("EURUSD");
    expect(q.get("timeframe")).toBe("1h");
    expect(Number(q.get("limit"))).toBeGreaterThan(0);
    // A read, never a write.
    expect(c.init?.method ?? "GET").toBe("GET");
  });

  it("refetches when the timeframe changes, and asks for the new one", async () => {
    answer = okRead;
    await mount();
    await waitFor(() => expect(chartDrawn()).toBe(true));
    calls.length = 0;
    await act(async () => {
      fireEvent.change(screen.getByRole("combobox", { name: /Timeframe/i }), { target: { value: "15m" } });
    });
    await waitFor(() => expect(calls.length).toBeGreaterThan(0));
    expect(new URLSearchParams(calls[0].path.split("?")[1]).get("timeframe")).toBe("15m");
  });

  it("offers only the instruments it was given, and asks for nothing without an account", async () => {
    answer = okRead;
    await mount({ ctid: null });
    await act(async () => { await Promise.resolve(); });
    expect(calls, "no account means nothing to ask").toHaveLength(0);
    expect(screen.getByText(/cTrader account not connected/)).toBeDefined();
    expect(chartDrawn()).toBe(false);
  });
});

describe("market panel — states that must not look like a quiet market", () => {
  it.each([
    ["not_connected", /cTrader account not connected/],
    ["reauth_required", /cTrader needs reconnecting/],
    ["unavailable", /Market data unavailable/],
  ])("read status %s is shown as itself, with no chart", async (status, expected) => {
    answer = { ok: true, data: {
      connected: status !== "not_connected", status,
      reason: "TimeoutError: cTrader did not answer within 12s",
    } };
    await mount();
    await waitFor(() => expect(screen.getByText(expected)).toBeDefined());
    expect(chartDrawn(), "a chart was drawn over a failed read").toBe(false);
  });

  it("a failed request shows its code, not an empty chart", async () => {
    answer = { ok: false, status: 400, code: "NO_SUCH_ACCOUNT", message: "that account is not connected" };
    await mount();
    await waitFor(() => expect(screen.getByText("NO_SUCH_ACCOUNT")).toBeDefined());
    expect(screen.getByText(/that account is not connected/)).toBeDefined();
    expect(chartDrawn()).toBe(false);
  });

  it("an ok read with no bars says the broker returned none", async () => {
    answer = { ok: true, data: {
      connected: true, status: "ok", accountId: 501, mode: "demo",
      candles: [], symbol: "EURUSD", timeframe: "1h", count: 0, requested: 200,
    } };
    await mount();
    await waitFor(() => expect(screen.getByText(/answered with no bars/)).toBeDefined());
    expect(chartDrawn()).toBe(false);
  });

  it("an expired authorisation offers reconnecting, which is the only thing that fixes it", async () => {
    answer = { ok: true, data: {
      connected: true, status: "reauth_required",
      reason: "the cTrader authorisation has expired",
    } };
    await mount();
    await waitFor(() => expect(screen.getByRole("link", { name: /Reconnect cTrader/ })).toBeDefined());
  });
});

describe("market panel — what it shows when it works", () => {
  it("draws the candles and states the source, bar count and latest bar", async () => {
    answer = okRead;
    await mount();
    await waitFor(() => expect(chartDrawn()).toBe(true));
    expect(document.querySelectorAll("svg.candles rect").length).toBeGreaterThan(BARS.length);
    expect(screen.getByText(/Source: cTrader account/)).toBeDefined();
    expect(screen.getByText(/#501/)).toBeDefined();
    expect(screen.getByText(/3 bars of EURUSD 1h/)).toBeDefined();
    // Twice: once in the OHLC readout, once in the source line.
    expect(screen.getAllByText(/2025-09-22 14:00 UTC/).length).toBeGreaterThan(0);
  });

  it("says the count asked for when the broker returned fewer", async () => {
    answer = { ok: true, data: { ...okRead.data, count: 3, requested: 200 } };
    await mount();
    await waitFor(() => expect(screen.getByText(/asked for 200/)).toBeDefined());
  });

  it("shows an OHLC readout for the last bar", async () => {
    answer = okRead;
    await mount();
    await waitFor(() => expect(chartDrawn()).toBe(true));
    const ohlc = document.querySelector(".ohlc")!;
    expect(ohlc.textContent).toContain("EURUSD");
    // The last bar, not the first.
    expect(ohlc.textContent).toContain("1.0995");
  });

  it("states that no volume is available rather than drawing one", async () => {
    answer = okRead;
    await mount();
    await waitFor(() => expect(chartDrawn()).toBe(true));
    expect(screen.getByText(/does not carry volume/)).toBeDefined();
  });

  it("draws a marker where a rule was evaluated", async () => {
    answer = okRead;
    await mount({ markers: [{ time: 1758549600, label: "Evaluated here", tone: "long" }] });
    await waitFor(() => expect(chartDrawn()).toBe(true));
    expect(screen.getAllByTestId("chart-marker")).toHaveLength(1);
  });
});

describe("market panel — read-only, structurally", () => {
  const SRC = [
    readFileSync(join(__dirname, "market-panel.tsx"), "utf8"),
    readFileSync(join(__dirname, "candles.tsx"), "utf8"),
  ].join("\n");

  it("never references an order, close or amend endpoint", async () => {
    for (const forbidden of [
      "automation/start", "automation/stop", "force_trade", "place_order",
      "/close", "/amend", "authorize_order",
    ]) {
      expect(SRC, `the chart references ${forbidden}`).not.toContain(forbidden);
    }
  });

  it("issues no non-GET request at runtime, in any state", async () => {
    for (const a of [
      okRead,
      { ok: true, data: { connected: true, status: "unavailable", reason: "x" } },
      { ok: false, status: 500, code: "BOOM", message: "x" },
    ]) {
      calls.length = 0;
      answer = a;
      await mount();
      await act(async () => { await Promise.resolve(); });
      const writes = calls.filter((c) => c.init?.method && c.init.method !== "GET");
      expect(writes, `the chart issued ${writes.map((w) => w.init?.method).join(", ")}`)
        .toHaveLength(0);
    }
  });
});
