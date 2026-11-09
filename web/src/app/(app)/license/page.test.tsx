/**
 * The buy screen states the refund rule and will not start checkout
 * until the withdrawal waiver is ticked. The receipt text is the server's.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PLAN_NOTICE, type Execution, type Me, type PublicOffer } from "@/lib/api";

const api = vi.fn();
const bag: {
  search: string;
  me: { ok: true; data: Me };
  offer: { ok: true; data: PublicOffer };
  confirmation: { ok: true; data: { recorded: boolean; confirmation?: string } };
} = {
  search: "",
  me: { ok: true, data: null as unknown as Me },
  offer: { ok: true, data: null as unknown as PublicOffer },
  confirmation: { ok: true, data: { recorded: false } },
};

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(bag.search),
}));

vi.mock("@/lib/api", async (orig) => {
  const actual = await orig<typeof import("@/lib/api")>();
  return { ...actual, api: (...args: unknown[]) => api(...args) };
});

vi.mock("@/lib/use-api", () => ({
  useRead: (path: string) => {
    const result = path === "me"
      ? bag.me
      : path === "billing/offer"
        ? bag.offer
        : path.startsWith("billing/purchase-confirmation")
          ? bag.confirmation
          : null;
    return { loading: false, result, reload: () => {} };
  },
}));

import LicensePage from "./page";

const EXEC: Execution = {
  accountMode: "demo",
  entitlement: "free_demo",
  licenceState: "active",
  liveExecutionEnabled: false,
  planNotice: PLAN_NOTICE,
  canAutomate: true,
  canActivate: true,
  activationRefusal: null,
  plan: "demo_trial",
  onTrial: false,
  trialDaysLeft: null,
  trialExpiresAt: null,
  accountAllowance: 1,
  reason: null,
  message: "demo automation is available on this account",
  badge: "DEMO",
};

function offer(open: boolean): PublicOffer {
  return {
    sku: "founder_lifetime",
    plan: "founder_lifetime",
    purchaseMode: "one_time",
    priceMinor: 49700,
    currency: "usd",
    periodDays: null,
    checkoutEnabled: open,
    checkoutImplemented: open,
  };
}

beforeEach(() => {
  api.mockReset();
  bag.search = "";
  bag.me = {
    ok: true,
    data: {
      user: { userId: "user-1", email: "buyer@example.test", emailVerified: true },
      licence: { state: "active", plan: "demo_trial", expiresAt: null },
      execution: EXEC,
    },
  };
  bag.offer = { ok: true, data: offer(false) };
  bag.confirmation = { ok: true, data: { recorded: false } };
});

describe("the licence buy screen", () => {
  it("states the refund rule before checkout is open", () => {
    render(<LicensePage />);
    expect(screen.getByText(/You get a free 14-day demo to test Apex4Traders before buying/)).toBeTruthy();
    expect(screen.getByText(/Licence purchases are final and non-refundable once access is granted, except where required by law/)).toBeTruthy();
    expect(screen.getByText(/Demo conditions \(fills, spreads, slippage\) can differ from live trading/)).toBeTruthy();
    expect(screen.getByRole("button", { name: /not on sale yet/i })).toBeTruthy();
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(document.body.textContent).not.toMatch(/identical to live/i);
  });

  it("requires the unticked waiver before checkout, and shows the server receipt", () => {
    bag.offer = { ok: true, data: offer(true) };
    bag.search = "checkout=success";
    bag.confirmation = {
      ok: true,
      data: {
        recorded: true,
        confirmation: "Purchase confirmation. You agreed: \"I request immediate access to the licence and acknowledge that I lose my 14-day right of withdrawal once access is granted.\" Consent recorded for user user-1 at 2026-11-09T12:00:00Z under refund policy 2026-11-09.",
      },
    };
    render(<LicensePage />);
    const box = screen.getByRole("checkbox");
    expect(box).toHaveProperty("checked", false);
    const buy = screen.getByRole("button", { name: /buy founder access/i });
    expect(buy).toHaveProperty("disabled", true);
    fireEvent.click(buy);
    expect(api).not.toHaveBeenCalled();
    expect(screen.getByText(/Consent recorded for user user-1 at 2026-11-09T12:00:00Z under refund policy 2026-11-09/)).toBeTruthy();
  });
});
