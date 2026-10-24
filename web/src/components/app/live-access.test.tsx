import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { LiveAccessPanel, liveCleared, liveNotice } from "./live-access";
import type { Execution, LiveGateVerdict } from "@/lib/api";

const closed: LiveGateVerdict = {
  open: false,
  status: "closed",
  summary: "Live trading is not available until every condition below is met.",
  conditions: [],
  missing: [
    { code: "LEGAL_TERMS_ACCEPTED", status: "missing", detail: "You have not accepted the current legal terms." },
    { code: "PAID_LICENCE", status: "missing", detail: "No confirmed lifetime licence is on file." },
    { code: "OPERATOR_APPROVAL", status: "missing", detail: "An operator has not approved the live account request." },
  ],
  request: { status: "pending" },
  checkoutOpen: false,
};

function execution(over: Partial<Execution> = {}): Execution {
  return {
    accountMode: "live",
    entitlement: "paid_live",
    licenceState: "active",
    liveExecutionEnabled: true,
    planNotice: "Demo accounts are free for a 14-day trial.",
    canAutomate: true,
    canActivate: true,
    activationRefusal: null,
    plan: "founder_lifetime",
    onTrial: false,
    trialDaysLeft: null,
    trialExpiresAt: null,
    accountAllowance: 1,
    reason: null,
    message: "live automation is available on this account",
    badge: "LIVE",
    ...over,
  };
}

describe("the live gate on a screen", () => {
  it("shows the server's missing reasons and does not say live is available", () => {
    render(<LiveAccessPanel gate={closed} />);
    expect(screen.getByText(/You have not accepted the current legal terms/)).toBeTruthy();
    expect(screen.getByText(/No confirmed lifetime licence is on file/)).toBeTruthy();
    expect(screen.getByText(/An operator has not approved the live account request/)).toBeTruthy();
    expect(screen.getByText(/Live purchase is not yet open/)).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/live trading is available/i);
  });

  it("does not repeat an available sentence when the gate is closed", () => {
    const notice = liveNotice(execution({ liveGate: closed }));
    expect(notice.lead).not.toMatch(/live automation is available/i);
    expect(notice.lead).toMatch(/not available/i);
    expect(notice.details).toContain("You have not accepted the current legal terms.");
    expect(liveCleared(execution({ liveGate: closed }))).toBe(false);
  });

  it("treats a missing gate as not cleared", () => {
    expect(liveCleared(execution())).toBe(false);
    const notice = liveNotice(execution());
    expect(notice.lead).toBe("Live trading is not available in this release.");
    expect(notice.lead).not.toMatch(/live automation is available/i);
  });
});
