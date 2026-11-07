// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { AccountsDuo } from "./accounts-duo";
import type { AutomationState, CtAccount, Execution } from "@/lib/api";

const accounts: CtAccount[] = [{ ctid: 111, mode: "demo" }, { ctid: 222, mode: "live" }];
const closed = {
  accountMode: "demo", canAutomate: true, liveExecutionEnabled: false,
  liveGate: { open: false, status: "closed", summary: "Live is not enabled for this account yet.", conditions: [], missing: [], request: { status: "none" }, checkoutOpen: false },
} as unknown as Execution;
const running = { state: "running", ruleDocId: "r", mode: "demo", startedAt: 1 } as unknown as AutomationState;

describe("AccountsDuo", () => {
  it("shows demo and live next to each other", () => {
    render(<AccountsDuo accounts={accounts} selected={{ ctid: 111, mode: "demo" }} execution={closed} running={null} />);
    expect(screen.getByText("Demo account")).toBeDefined();
    expect(screen.getByText("Live account")).toBeDefined();
    expect(screen.getByText("#111")).toBeDefined();
    expect(screen.getByText("#222")).toBeDefined();
  });

  it("never says live is available when the server says it is not", () => {
    const { container } = render(<AccountsDuo accounts={accounts} selected={null} execution={closed} running={null} />);
    expect(screen.getByText("Not enabled yet")).toBeDefined();
    expect(container.textContent).not.toMatch(/cleared|automating/i);
  });

  it("marks only the account that is actually running", () => {
    const { container } = render(<AccountsDuo accounts={accounts} selected={{ ctid: 111, mode: "demo" }} execution={closed} running={running} />);
    expect(container.querySelector('[data-kind="demo"]')?.getAttribute("data-active")).toBe("true");
    expect(container.querySelector('[data-kind="live"]')?.getAttribute("data-active")).toBeNull();
  });
});
