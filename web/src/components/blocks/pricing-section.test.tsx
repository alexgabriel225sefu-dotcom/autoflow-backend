/**
 * What the pricing section is allowed to show.
 *
 * It is read by somebody deciding whether to pay, so the two dangerous
 * directions are: offering to take money the server will refuse, and showing
 * a price the server did not give. Both are asserted here, with the negative
 * cases — a disabled button and a missing price are easy to assert by
 * accident, so each test also pins what must NOT be on screen.
 */
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ApiResult, PublicOffer } from "@/lib/api";

const publicApi = vi.fn();

vi.mock("@/lib/api", async (orig) => {
  const actual = await orig<typeof import("@/lib/api")>();
  return { ...actual, publicApi: (p: string) => publicApi(p) };
});

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

const { PricingSection } = await import("./pricing-section");

const OFFER: PublicOffer = {
  sku: "founder_lifetime",
  plan: "founder_lifetime",
  purchaseMode: "one_time",
  priceMinor: 49900,
  currency: "usd",
  periodDays: null,
  checkoutEnabled: false,
};

function answer(data: Partial<PublicOffer>): ApiResult<PublicOffer> {
  return { ok: true, data: { ...OFFER, ...data } };
}

beforeEach(() => publicApi.mockReset());

describe("the price on screen", () => {
  it("is the server's, formatted, and is asked for from billing/offer", async () => {
    publicApi.mockResolvedValue(answer({}));
    render(<PricingSection />);
    await waitFor(() => expect(screen.getByText("$499")).toBeTruthy());
    expect(publicApi).toHaveBeenCalledWith("billing/offer");
  });

  it("follows the server when the server says something else", async () => {
    // The whole point of reading it: a changed offer changes the page with
    // no code change. A hardcoded 499 would pass the test above and fail
    // this one.
    publicApi.mockResolvedValue(answer({ priceMinor: 125000, currency: "eur" }));
    render(<PricingSection />);
    await waitFor(() => expect(screen.getByText(/1,250/)).toBeTruthy());
    expect(screen.queryByText("$499")).toBeNull();
  });

  it("is absent entirely when the offer could not be read", async () => {
    publicApi.mockResolvedValue({
      ok: false, status: 503, code: "STORE_UNAVAILABLE", message: "down",
    });
    render(<PricingSection />);
    await waitFor(() =>
      expect(screen.getByText(/price could not be loaded/i)).toBeTruthy());
    // Not a remembered figure, and not a silent section that reads as free.
    expect(document.body.textContent).not.toMatch(/\$\s?\d/);
    expect(screen.getByRole("button", { name: /try again/i })).toBeTruthy();
  });
});

describe("the call to action", () => {
  it("does not offer to take money while checkout is off", async () => {
    publicApi.mockResolvedValue(answer({ checkoutEnabled: false }));
    render(<PricingSection />);
    const cta = await screen.findByRole("button", { name: /not on sale yet/i });
    expect(cta).toHaveProperty("disabled", true);
    // It says why on the card, rather than at a checkout that refuses.
    expect(screen.getByText(/not on sale yet\./i)).toBeTruthy();
    // And there is no link anywhere to a purchase.
    const hrefs = Array.from(document.querySelectorAll("a")).map((a) => a.getAttribute("href"));
    expect(hrefs).not.toContain("/license");
  });

  it("becomes a real link once the server opens checkout", async () => {
    // Proves the disabled state above is driven by the flag and is not just
    // how this component always renders.
    publicApi.mockResolvedValue(answer({ checkoutEnabled: true }));
    render(<PricingSection />);
    const cta = await screen.findByRole("link", { name: /get founder access/i });
    expect(cta.getAttribute("href")).toBe("/license");
    expect(screen.queryByText(/not on sale yet/i)).toBeNull();
  });

  it("always offers the free demo, which needs no payment", async () => {
    publicApi.mockResolvedValue(answer({}));
    render(<PricingSection />);
    const signup = await screen.findByRole("link", { name: /create an account/i });
    expect(signup.getAttribute("href")).toBe("/signup");
    expect(screen.getByText("Free")).toBeTruthy();
  });
});
