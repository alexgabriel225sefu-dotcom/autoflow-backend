import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ApiResult } from "@/lib/api";

const calls: { path: string; init?: { method?: string; body?: unknown } }[] = [];
let note: unknown = null;
vi.mock("@/lib/api", async (orig) => {
  const actual = await orig<typeof import("@/lib/api")>();
  return { ...actual, api: vi.fn(async (path: string, init?: { method?: string; body?: unknown }) => {
    calls.push({ path, init });
    if (init?.method === "PUT") { note = { tags: (init.body as { tags: string[] }).tags, comment: "", updatedAt: 1 }; return { ok: true, status: 200, data: { note } } as ApiResult<unknown>; }
    return { ok: true, status: 200, data: { note } } as ApiResult<unknown>;
  }) };
});
import { JournalNote } from "./journal-note";

afterEach(() => { cleanup(); calls.length = 0; note = null; });

describe("JournalNote", () => {
  it("asks for nothing until opened", () => {
    render(<JournalNote entryId="e1" />);
    expect(calls.length).toBe(0);
  });
  it("saves tags split on commas, and says so", async () => {
    render(<JournalNote entryId="e1" />);
    fireEvent.click(screen.getByRole("button", { name: /Tags and notes/ }));
    await waitFor(() => expect(screen.queryByLabelText(/Tags/)).not.toBeNull());
    fireEvent.change(screen.getByLabelText(/Tags/), { target: { value: "review, late entry" } });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Save" })); });
    await waitFor(() => expect(screen.queryByText("Saved")).not.toBeNull());
    const put = calls.find((c) => c.init?.method === "PUT")!;
    expect(put.path).toBe("journal/e1/note");
    expect((put.init!.body as { tags: string[] }).tags).toEqual(["review", "late entry"]);
  });
});
