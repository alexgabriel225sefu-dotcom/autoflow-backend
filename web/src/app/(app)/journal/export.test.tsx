import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  usePathname: () => "/journal",
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));

let entries: unknown[] = [];
vi.mock("@/lib/api", async (orig) => ({
  ...(await orig<typeof import("@/lib/api")>()),
  api: vi.fn(async () => ({ ok: true, data: {
    status: "ok", entries, total: entries.length, limit: 25, offset: 0, hasMore: false,
  } })),
}));

import JournalView from "./page";

const row = {
  entryId: "e1", kind: "evaluation", status: "hold", ts: 1760000000, symbol: "EURUSD",
  accountId: "1", ruleDocId: "r1", correlationId: "c",
  decision: { verdict: "HOLD", reason: "no setup", conditions: [], executable: false },
};

describe("journal CSV export", () => {
  it("downloads the loaded rows without another request", async () => {
    entries = [row];
    const create = vi.fn(() => "blob:x");
    URL.createObjectURL = create;
    URL.revokeObjectURL = vi.fn();
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    await act(async () => { render(<JournalView />); });
    const btn = await screen.findByRole("button", { name: /export csv/i });
    fireEvent.click(btn);
    expect(create).toHaveBeenCalledOnce();
    const blob = (create.mock.calls[0] as unknown as [Blob])[0];
    expect(await blob.text()).toContain("EURUSD,hold,HOLD,no setup");
  });

  it("is disabled when there is nothing loaded", async () => {
    entries = [];
    await act(async () => { render(<JournalView />); });
    const btn = (await screen.findByRole("button", { name: /export csv/i })) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });
});
