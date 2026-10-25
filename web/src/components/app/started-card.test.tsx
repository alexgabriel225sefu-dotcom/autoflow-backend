import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { StartedCard } from "./started-card";

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) =>
    <a href={href} {...rest}>{children}</a>,
}));

describe("StartedCard", () => {
  it("announces that automation started, names the setup and links to the dashboard", () => {
    render(<StartedCard summary="XAUUSD · Fibonacci · 1h" onClose={() => {}} />);
    const dialog = screen.getByRole("dialog", { name: "Automation started" });
    expect(dialog.textContent).toContain("XAUUSD · Fibonacci · 1h");
    expect(screen.getByRole("link", { name: "Go to dashboard" }).getAttribute("href")).toBe("/dashboard");
  });

  it("says a trade happens only if the rule fires, never that one was placed", () => {
    render(<StartedCard summary="x" onClose={() => {}} />);
    expect(screen.getByRole("dialog").textContent).toMatch(/only if the rule fires/i);
    expect(screen.getByRole("dialog").textContent).not.toMatch(/placed (a|the) trade|trade (was|has been) placed/i);
  });

  it("closes on the button, on Escape and on the backdrop, but not on a click inside", () => {
    const close = vi.fn();
    const { container } = render(<StartedCard summary="x" onClose={close} />);
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(close).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(close).toHaveBeenCalledTimes(2);
    fireEvent.click(screen.getByRole("dialog"));
    expect(close).toHaveBeenCalledTimes(2);
    fireEvent.click(container.querySelector(".started-backdrop")!);
    expect(close).toHaveBeenCalledTimes(3);
  });
});
