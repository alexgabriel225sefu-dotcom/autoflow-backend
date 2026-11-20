/**
 * The card that answers "why isn't it trading?".
 *
 * What it must NOT do: invent a reason (the sentence is the server's), turn a
 * failed read into a calm page, or word an empty list as proof the engine had
 * nothing to say.
 */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ApiResult, WhyRead } from "@/lib/api";

let answer: ApiResult<unknown> = { ok: false, status: 404, code: "NOT_FOUND", message: "no stub" } as ApiResult<unknown>;
const paths: string[] = [];

vi.mock("@/lib/api", async (orig) => {
  const actual = await orig<typeof import("@/lib/api")>();
  return { ...actual, api: vi.fn(async (path: string) => { paths.push(path); return answer; }) };
});

import { WhyCard } from "./why-card";

const why = (over: Partial<WhyRead> = {}): WhyRead => ({
  status: "ok", state: "running", reason: "watching",
  summary: "It is on and watching.", level: "full", levelLabel: "Full Automation",
  loopActive: true, marketOpen: true, halted: false, openPosition: null,
  maxPositions: 1, riskGuard: { state: "unknown", reasons: [] },
  skipsToday: null, skips: [], recorded: [],
  recordedCount: 0, recordedReadable: true, ...over,
});
const ok = (data: unknown) => ({ ok: true, status: 200, data } as ApiResult<unknown>);

afterEach(() => { cleanup(); paths.length = 0; });

describe("WhyCard", () => {
  it("reads the server's why route", async () => {
    answer = ok(why());
    render(<WhyCard />);
    await waitFor(() => expect(screen.queryByText("It is on and watching.")).not.toBeNull());
    expect(paths).toContain("automation/why");
  });

  it("shows the server's sentence verbatim", async () => {
    answer = ok(why({ reason: "stopped", summary: "Automation is stopped, which is why nothing is happening." }));
    render(<WhyCard />);
    await waitFor(() => expect(screen.queryByText(/Automation is stopped/)).not.toBeNull());
  });

  it("lists the refusals with their time", async () => {
    answer = ok(why({ skipsToday: 3, skips: [{ time: "09:15", reason: "spread too wide" }] }));
    render(<WhyCard />);
    await waitFor(() => expect(screen.queryByText(/spread too wide/)).not.toBeNull());
    expect(screen.queryByText(/3 today/)).not.toBeNull();
  });

  it("shows the persistent log with the instrument", async () => {
    answer = ok(why({ recorded: [{ at: 1700000000, symbol: "EURUSD", reason: "daily loss limit" }], recordedCount: 1 }));
    render(<WhyCard />);
    await waitFor(() => expect(screen.queryByText(/daily loss limit/)).not.toBeNull());
    expect(screen.queryByText(/EURUSD/)).not.toBeNull();
  });

  it("an empty list is not worded as 'no reason'", async () => {
    answer = ok(why());
    render(<WhyCard />);
    await waitFor(() => expect(screen.queryByText(/No refusals recorded yet/)).not.toBeNull());
    expect(screen.queryByText(/no reason/i)).toBeNull();
  });

  it("an unreadable log says so instead of claiming nothing happened", async () => {
    answer = ok(why({ recordedReadable: false }));
    render(<WhyCard />);
    await waitFor(() => expect(screen.queryByText(/could not be read/)).not.toBeNull());
    expect(screen.queryByText(/No refusals recorded yet/)).toBeNull();
  });

  it("a failed read is shown, not hidden", async () => {
    answer = { ok: false, status: 500, code: "INTERNAL_ERROR", message: "boom" } as ApiResult<unknown>;
    render(<WhyCard />);
    await waitFor(() => expect(document.body.textContent).toMatch(/INTERNAL_ERROR|boom/));
    expect(screen.queryByText("It is on and watching.")).toBeNull();
  });
});
