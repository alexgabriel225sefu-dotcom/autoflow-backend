import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ApiResult } from "@/lib/api";

const answers: Record<string, ApiResult<unknown>> = {};
const paths: string[] = [];
vi.mock("@/lib/api", async (orig) => {
  const actual = await orig<typeof import("@/lib/api")>();
  return { ...actual, api: vi.fn(async (p: string) => { paths.push(p); return answers[p] ?? { ok: false, status: 404, code: "NOT_FOUND", message: "x" }; }) };
});
import { RuleHistory } from "./rule-history";

const versions = [
  { version: 2, state: "active", activatedAt: 1_760_000_100, frozen: true },
  { version: 1, state: "active", activatedAt: 1_760_000_000, frozen: true },
];
const okv = (data: unknown) => ({ ok: true, status: 200, data } as ApiResult<unknown>);
afterEach(() => { cleanup(); paths.length = 0; for (const k of Object.keys(answers)) delete answers[k]; });

describe("RuleHistory", () => {
  it("lists only the versions the server returned", async () => {
    answers["rules/r1/versions"] = okv({ versions });
    render(<RuleHistory id="r1" />);
    await waitFor(() => expect(screen.queryByText("v2")).not.toBeNull());
    expect(screen.queryByText("v1")).not.toBeNull();
    expect(screen.queryByText("v3")).toBeNull();
  });
  it("shows what changed between two versions", async () => {
    answers["rules/r1/versions"] = okv({ versions });
    answers["rules/r1/diff?from=1&to=2"] = okv({ changes: [
      { path: "conditions[0].params.period", kind: "changed", before: 14, after: 21 }] });
    render(<RuleHistory id="r1" />);
    await waitFor(() => expect(screen.queryByText("v2")).not.toBeNull());
    fireEvent.click(screen.getByRole("button", { name: /What changed since v1/ }));
    await waitFor(() => expect(screen.queryByText("conditions[0].params.period")).not.toBeNull());
    expect(screen.queryByText(/14 → 21/)).not.toBeNull();
  });
  it("says identical versions are identical", async () => {
    answers["rules/r1/versions"] = okv({ versions });
    answers["rules/r1/diff?from=1&to=2"] = okv({ changes: [] });
    render(<RuleHistory id="r1" />);
    await waitFor(() => expect(screen.queryByText("v2")).not.toBeNull());
    fireEvent.click(screen.getByRole("button", { name: /What changed since v1/ }));
    await waitFor(() => expect(screen.queryByText(/identical/)).not.toBeNull());
  });
  it("a failed read is an error, not an empty history", async () => {
    render(<RuleHistory id="r1" />);
    await waitFor(() => expect(screen.queryByText(/No versions are stored yet/)).toBeNull());
    expect(screen.queryByRole("alert")).not.toBeNull();
  });
});
