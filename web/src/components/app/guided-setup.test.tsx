import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { GuidedSetup, type GuidedSetupStep } from "./guided-setup";

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>{children}</a>
  ),
}));

const steps: GuidedSetupStep[] = [
  { id: "symbol", title: "Choose a symbol", description: "Pick the market.", href: "/rules/new", complete: true },
  { id: "strategy", title: "Choose a strategy", description: "Use a preset or build your own.", href: "/rules/new/strategy", complete: false },
  { id: "risk", title: "Set risk", description: "Review the stop and size.", href: "/rules/new/strategy#risk", complete: false },
  { id: "account", title: "Select an account", description: "Use a connected account.", href: "/connect", complete: false },
  { id: "start", title: "Start automation", description: "Start only when ready.", href: "#automation", complete: false },
];

describe("GuidedSetup", () => {
  it("exposes all five setup steps and opens the first incomplete one", () => {
    render(<GuidedSetup steps={steps} accountSummary="No account selected" />);

    expect(screen.getByRole("heading", { name: "Guided setup" })).toBeDefined();
    expect(screen.getByRole("list", { name: "Automation setup steps" })).toBeDefined();
    expect(screen.getAllByRole("listitem")).toHaveLength(5);
    expect(screen.getByRole("link", { name: "Open setup step: Choose a strategy" })
      .getAttribute("href")).toBe("/rules/new/strategy");
    expect(screen.getByLabelText("1 of 5 setup steps complete")).toBeDefined();
  });

  it("does not offer another setup action after every step is complete", () => {
    render(
      <GuidedSetup
        accountSummary="Demo account selected"
        steps={steps.map((step) => ({ ...step, complete: true }))}
      />,
    );

    expect(screen.getByText("All setup steps are complete. Starting is still a deliberate action.")).toBeDefined();
    expect(screen.getByRole("link", { name: "Review automation" })
      .getAttribute("href")).toBe("#automation");
    expect(screen.queryByRole("link", { name: /Open setup step:/ })).toBeNull();
  });
});
