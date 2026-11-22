/**
 * What the pricing section is allowed to show.
 *
 * It is read by somebody deciding whether to pay, so the dangerous directions
 * are: offering to take money the server will refuse, showing a price the
 * server did not give, and showing a price that cannot be paid. All are
 * asserted here, with the negative cases: while purchase is closed (and while
 * the offer is loading or unreadable) NO figure is on screen and the paid
 * card is the live-trading waitlist.
 */
import { act, render, screen, waitFor } from "@testing-library/react";
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

const { PricingSection, planFor } = await import("./pricing-section");

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

const OPEN = { checkoutEnabled: true, checkoutImplemented: true } as const;

describe("the price on screen", () => {
  it("is the server's, formatted, and asked for from billing/offer, once purchase is open", async () => {
    publicApi.mockResolvedValue(answer({ ...OPEN }));
    render(<PricingSection />);
    await waitFor(() => expect(screen.getByText("$499")).toBeTruthy());
    expect(publicApi).toHaveBeenCalledWith("billing/offer");
  });

  it("follows the server when the server says something else", async () => {
    // A changed offer changes the page with no code change. A hardcoded 499
    // would pass the test above and fail this one.
    publicApi.mockResolvedValue(answer({ ...OPEN, priceMinor: 125000, currency: "eur" }));
    render(<PricingSection />);
    await waitFor(() => expect(screen.getByText(/1,250/)).toBeTruthy());
    expect(screen.queryByText("$499")).toBeNull();
  });

  it("is absent while purchase is closed, whatever the offer says", async () => {
    publicApi.mockResolvedValue(answer({ checkoutEnabled: false }));
    render(<PricingSection />);
    await screen.findByRole("link", { name: /join the waitlist/i });
    // The server holds a price; the page must not show one it cannot take.
    expect(document.body.textContent).not.toMatch(/\$\s?\d/);
    expect(screen.queryByText("$499")).toBeNull();
  });

  it("is absent entirely when the offer could not be read", async () => {
    publicApi.mockResolvedValue({
      ok: false, status: 503, code: "STORE_UNAVAILABLE", message: "down",
    });
    render(<PricingSection />);
    await waitFor(() => expect(publicApi).toHaveBeenCalled());
    await screen.findByRole("link", { name: /join the waitlist/i });
    // Not a remembered figure, and not a silent section that reads as free:
    // the paid card says Waitlist.
    expect(document.body.textContent).not.toMatch(/\$\s?\d/);
    expect(screen.getByText("Waitlist")).toBeTruthy();
  });

  it("is absent while the offer is still loading", async () => {
    let release!: (v: ApiResult<PublicOffer>) => void;
    publicApi.mockReturnValue(new Promise<ApiResult<PublicOffer>>((r) => { release = r; }));
    render(<PricingSection />);
    await screen.findByText("Waitlist");
    expect(document.body.textContent).not.toMatch(/\$\s?\d/);
    await act(async () => { release(answer({})); });
  });
});

describe("the live-trading waitlist card", () => {
  it("replaces the price while nothing can be bought, and sends to the form", async () => {
    publicApi.mockResolvedValue(answer({ checkoutEnabled: false }));
    render(<PricingSection />);
    const cta = await screen.findByRole("link", { name: /join the waitlist/i });
    expect(cta.getAttribute("href")).toBe("#waitlist");
    expect(screen.getByText("Waitlist")).toBeTruthy();
    expect(screen.getAllByText(/No payment is taken/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Coming later/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/founder/i)).toBeNull();
  });

  it("does not claim live trading is open, and promises no outcome", async () => {
    publicApi.mockResolvedValue(answer({}));
    render(<PricingSection />);
    await screen.findByText("Waitlist");
    expect(document.body.textContent).toMatch(/Live trading is not (open|available) yet/i);
    expect(document.body.textContent).not.toMatch(/profit|guarantee|% off|save \d|countdown/i);
  });
});

describe("the call to action", () => {
  it("does not offer to take money while checkout is off", async () => {
    publicApi.mockResolvedValue(answer({ checkoutEnabled: false }));
    render(<PricingSection />);
    await screen.findByRole("link", { name: /join the waitlist/i });
    const hrefs = Array.from(document.querySelectorAll("a")).map((a) => a.getAttribute("href"));
    expect(hrefs).not.toContain("/license");
    expect(screen.queryByRole("link", { name: /get founder access/i })).toBeNull();
  });

  it("becomes a real purchase link once the server opens checkout", async () => {
    // Proves the closed state above is driven by the flags and is not just
    // how this component always renders.
    publicApi.mockResolvedValue(answer({ ...OPEN }));
    render(<PricingSection />);
    const cta = await screen.findByRole("link", { name: /get founder access/i });
    expect(cta.getAttribute("href")).toBe("/license");
    expect(screen.queryByRole("link", { name: /join the waitlist/i })).toBeNull();
    expect(screen.queryByText("Waitlist")).toBeNull();
  });

  it("stays closed when the flags are on but checkout is not implemented", async () => {
    // The flags have been true over a route that answers 501. That must not
    // become a buy link or a price.
    publicApi.mockResolvedValue(answer({
      checkoutEnabled: true, checkoutImplemented: false,
    }));
    render(<PricingSection />);
    await screen.findByRole("link", { name: /join the waitlist/i });
    expect(screen.queryByRole("link", { name: /get founder access/i })).toBeNull();
    expect(document.body.textContent).not.toMatch(/\$\s?\d/);
  });

  it("states the decided refund rule and that demo is not live", async () => {
    publicApi.mockResolvedValue(answer({}));
    render(<PricingSection />);
    await screen.findByText("Free");
    expect(screen.getByText(/You get a free 14-day demo to test Apex4Traders before buying/)).toBeTruthy();
    expect(screen.getByText(/Licence purchases are final and non-refundable once access is granted, except where required by law/)).toBeTruthy();
    expect(screen.getByText(/Demo conditions \(fills, spreads, slippage\) can differ from live trading/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Refund policy" }).getAttribute("href")).toBe("/refunds");
    expect(document.body.textContent).not.toMatch(/identical to live/i);
  });

  it("always offers the free demo, which needs no payment", async () => {
    publicApi.mockResolvedValue(answer({}));
    render(<PricingSection />);
    const signup = await screen.findByRole("link", { name: /create an account/i });
    expect(signup.getAttribute("href")).toBe("/signup");
    expect(screen.getByText("Free")).toBeTruthy();
    expect(screen.getByText(/Free for 14 days/)).toBeTruthy();
    expect(screen.queryByText(/no expiry/i)).toBeNull();
  });
});

describe("the paid plan as a function of the offer", () => {
  const paid = (o: Partial<PublicOffer>) =>
    planFor({ ...OFFER, ...o }).find((p) => p.palette === "accent")!;

  it("is the waitlist card, with no figure, until purchase is open", () => {
    for (const o of [
      { checkoutEnabled: false },
      { checkoutEnabled: true, checkoutImplemented: false },
    ]) {
      const p = paid(o);
      expect(p.id).toBe("live_waitlist");
      expect(p.price).toBe("Waitlist");
      expect(p.ctaHref).toBe("#waitlist");
      expect(p.variant).toBeUndefined();
    }
  });

  it("is the Founder card with the server's price once purchase is open", () => {
    const p = paid({ ...OPEN });
    expect(p.id).toBe("founder_lifetime");
    expect(p.statusBadge).toBeUndefined();
    expect(p.ctaHref).toBe("/license");
  });

  it("is a lifetime card only when the open offer has no period", () => {
    expect(paid({ ...OPEN, periodDays: null }).variant).toBe("lifetime");
    expect(paid({ ...OPEN, periodDays: 365 }).variant).toBeUndefined();
  });

  it("invents no discount, strike-through price or countdown", () => {
    for (const o of [{}, { ...OPEN }]) {
      const f = paid(o);
      expect(f.originalPrice).toBeUndefined();
      expect(JSON.stringify(f)).not.toMatch(/countdown|% off|save \d/i);
    }
  });

  it("takes its price from the offer, not from the component", () => {
    expect(paid({ ...OPEN, priceMinor: 125000 }).price)
      .not.toBe(paid({ ...OPEN, priceMinor: 49900 }).price);
  });
});
