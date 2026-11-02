/**
 * The buy control follows the server, and will not open an arbitrary URL.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ApiResult } from "@/lib/api";

const api = vi.fn();

vi.mock("@/lib/api", async (orig) => {
  const actual = await orig<typeof import("@/lib/api")>();
  return { ...actual, api: (...args: unknown[]) => api(...args) };
});

import { BuyButton, isStripeHostedUrl } from "./buy-button";

describe("isStripeHostedUrl", () => {
  it("accepts Stripe payment and checkout hosts only", () => {
    expect(isStripeHostedUrl("https://buy.stripe.com/abc?client_reference_id=u")).toBe(true);
    expect(isStripeHostedUrl("https://checkout.stripe.com/c/pay/cs_test")).toBe(true);
    expect(isStripeHostedUrl("http://buy.stripe.com/abc")).toBe(false);
    expect(isStripeHostedUrl("https://buy.stripe.com.evil.test/abc")).toBe(false);
    expect(isStripeHostedUrl("https://evil.test/buy.stripe.com")).toBe(false);
    expect(isStripeHostedUrl("not a url")).toBe(false);
  });
});

describe("BuyButton", () => {
  it("stays Not on sale yet and does not call checkout while closed", () => {
    api.mockReset();
    render(<BuyButton open={false} />);
    const button = screen.getByRole("button", { name: /not on sale yet/i });
    expect(button).toHaveProperty("disabled", true);
    fireEvent.click(button);
    expect(api).not.toHaveBeenCalled();
  });

  it("asks the server and follows a Stripe payment link", async () => {
    api.mockReset();
    const navigate = vi.fn();
    api.mockResolvedValue({
      ok: true,
      data: {
        url: "https://buy.stripe.com/abc?client_reference_id=user-1&prefilled_email=a%40b.test",
        kind: "payment_link",
      },
    } satisfies ApiResult<{ url: string; kind: string }>);
    render(<BuyButton open navigate={navigate} />);
    fireEvent.click(screen.getByRole("button", { name: /buy founder access/i }));
    await waitFor(() => expect(navigate).toHaveBeenCalledTimes(1));
    expect(api).toHaveBeenCalledWith("billing/checkout", { method: "POST", body: {} });
    expect(navigate.mock.calls[0][0]).toContain("client_reference_id=user-1");
  });

  it("does not follow a url that is not Stripe", async () => {
    api.mockReset();
    const navigate = vi.fn();
    api.mockResolvedValue({
      ok: true,
      data: { url: "https://evil.test/checkout", kind: "payment_link" },
    });
    render(<BuyButton open navigate={navigate} />);
    fireEvent.click(screen.getByRole("button", { name: /buy founder access/i }));
    await waitFor(() => expect(screen.getByText(/not a Stripe page/i)).toBeTruthy());
    expect(navigate).not.toHaveBeenCalled();
  });
});
