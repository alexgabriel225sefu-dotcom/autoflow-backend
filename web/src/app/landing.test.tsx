import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>{children}</a>
  ),
}));
vi.mock("@/lib/api", async (orig) => ({
  ...(await orig<typeof import("@/lib/api")>()),
  publicApi: vi.fn(async () => ({ ok: false, status: 0, code: "NETWORK", message: "offline" })),
  joinWaitlist: vi.fn(),
}));

import Landing from "./page";

describe("landing page", () => {
  it("renders, with sign-up and log-in entry points", () => {
    render(<Landing />);
    expect(screen.getAllByRole("link", { name: /try free for 14 days|sign up|create/i }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("link", { name: /log in/i }).length).toBeGreaterThan(0);
  });

  it("states cTrader as available and the MetaTrader platforms as coming soon", () => {
    render(<Landing />);
    // Platform statuses are kept in the discreet Platforms section, below the hero.
    expect(screen.getAllByText("Available now")).toHaveLength(1);
    expect(screen.getAllByText("Coming soon")).toHaveLength(2);
  });

  it("shows a product preview, the three steps and plain-language FAQ", () => {
    render(<Landing />);
    expect(screen.getByRole("img", { name: /on a laptop and on a phone/i })).toBeTruthy();
    expect(screen.getByRole("heading", { name: /a simple path from idea to demo/i })).toBeTruthy();
    expect(screen.getByRole("heading", { name: /questions, answered plainly/i })).toBeTruthy();
    expect(screen.queryByText("Read-only preview")).toBeNull();
  });

  it("says demo-only and makes no profit claim", () => {
    const { container } = render(<Landing />);
    const text = container.textContent ?? "";
    expect(text).toMatch(/demo/i);
    expect(text).toMatch(/no profit guarantees|not financial advice|no.*guarantee/i);
    expect(text).not.toMatch(new RegExp("guarant" + "eed (profit|returns?)|risk-free|\\d+% (win|return)", "i"));
  });
});
