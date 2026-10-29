import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>{children}</a>
  ),
}));
const publicApi = vi.fn();
vi.mock("@/lib/api", async (orig) => ({
  ...(await orig<typeof import("@/lib/api")>()),
  publicApi: (p: string) => publicApi(p),
}));

import PricingPage from "./page";

describe("pricing page", () => {
  it("renders on its own URL with the marketing nav and legal footer", async () => {
    publicApi.mockResolvedValue({ ok: true, data: {
      sku: "s", plan: "founder_lifetime", purchaseMode: "one_time", priceMinor: 49900,
      currency: "usd", periodDays: null, checkoutEnabled: false,
    } });
    render(<PricingPage />);
    expect(screen.getByRole("link", { name: /get started/i }).getAttribute("href")).toBe("/signup");
    expect(screen.getByRole("link", { name: "Terms" }).getAttribute("href")).toBe("/terms");
    expect(screen.getByRole("link", { name: "Pricing" }).getAttribute("aria-current")).toBe("page");
    await waitFor(() => expect(screen.getByText("$499")).toBeTruthy());
  });

  it("does not invent a price when the server cannot be reached", async () => {
    publicApi.mockResolvedValue({ ok: false, status: 0, code: "NETWORK", message: "offline" });
    const { container } = render(<PricingPage />);
    await waitFor(() => expect(publicApi).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 20));
    expect(container.textContent).not.toMatch(/\$\s?\d/);
  });
});
