import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ApiResult } from "@/lib/api";

let answer: ApiResult<unknown> = { ok: false, status: 404, code: "NOT_FOUND", message: "x" } as ApiResult<unknown>;
vi.mock("@/lib/api", async (orig) => {
  const actual = await orig<typeof import("@/lib/api")>();
  return { ...actual, api: vi.fn(async () => answer) };
});
import { AccountKinds } from "./account-kinds";

const okv = (data: unknown) => ({ ok: true, status: 200, data } as ApiResult<unknown>);
afterEach(cleanup);

describe("AccountKinds", () => {
  it("labels demo, live and not-verified accounts and prints the server's sentences", async () => {
    answer = okv({ status: "ok", connected: true, summary: { demo: 1, live: 1, unverified: 1 }, accounts: [
      { ctid: 1, kind: "demo", basis: "cTrader reported this as a demo account.", selected: true, liveState: null, liveText: "Demo account: automation can run here with no real money." },
      { ctid: 2, kind: "live", basis: "cTrader reported this as a live account.", selected: false, liveState: "not_enabled", liveText: "Live accounts are not enabled on this deployment, so no order is sent to this account." },
      { ctid: 3, kind: "unverified", basis: "cTrader did not say whether this is a live or a demo account.", selected: false, liveState: "unverified", liveText: "Treated as live and closed: no order is sent until cTrader reports the account type." },
    ] });
    render(<AccountKinds />);
    await waitFor(() => expect(screen.queryByText("Demo")).not.toBeNull());
    expect(screen.queryByText("Live")).not.toBeNull();
    expect(screen.queryByText("Not verified")).not.toBeNull();
    expect(screen.queryByText(/no order is sent until cTrader reports/)).not.toBeNull();
    expect(document.querySelector('[data-kind="unverified"]')).not.toBeNull();
  });
  it("a failed read is an error, not an empty list", async () => {
    answer = { ok: false, status: 503, code: "STORE_UNAVAILABLE", message: "down" } as ApiResult<unknown>;
    render(<AccountKinds />);
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeNull());
    expect(screen.queryByText(/No cTrader account is connected/)).toBeNull();
  });
  it("not connected says so", async () => {
    answer = okv({ status: "ok", connected: false, accounts: [], summary: { demo: 0, live: 0, unverified: 0 } });
    render(<AccountKinds />);
    await waitFor(() => expect(screen.queryByText(/No cTrader account is connected/)).not.toBeNull());
  });
});
