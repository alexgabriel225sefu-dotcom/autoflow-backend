"use client";
/**
 * The signed-in buy control.
 *
 * Off, and labelled "Not on sale yet", unless the server says checkout is
 * open. When it is open, the server returns a Stripe URL that already
 * carries this user's id. This file does not build that URL and does not
 * know a price. A URL that is not a Stripe-hosted page is not followed.
 */
import { useState } from "react";
import { api, type ApiError } from "@/lib/api";
import { ErrorNotice } from "@/components/app/state";

const STRIPE_HOSTS = new Set(["buy.stripe.com", "checkout.stripe.com"]);

export function isStripeHostedUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && STRIPE_HOSTS.has(url.hostname);
  } catch {
    return false;
  }
}

export function BuyButton({
  open,
  navigate = (url: string) => window.location.assign(url),
}: {
  open: boolean;
  /** Test seam. Production follows the Stripe URL in this tab. */
  navigate?: (url: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  // The buyer confirms they tried the free demo. The server requires it and
  // keeps the time it was given; this box only collects it.
  const [tried, setTried] = useState(false);

  async function buy() {
    if (!tried) return;
    setBusy(true);
    setError(null);
    const result = await api<{ url?: string }>("billing/checkout", {
      method: "POST",
      body: { acknowledgedTrial: true },
    });
    setBusy(false);
    if (!result.ok) {
      setError(result);
      return;
    }
    const url = result.data.url ?? "";
    if (!isStripeHostedUrl(url)) {
      setError({
        ok: false,
        status: 502,
        code: "CHECKOUT_FAILED",
        message: "The payment page was not a Stripe page, so it was not opened.",
      });
      return;
    }
    navigate(url);
  }

  if (!open) {
    return (
      <button type="button" disabled>
        Not on sale yet
      </button>
    );
  }
  return (
    <>
      {error ? <ErrorNotice error={error} /> : null}
      <label style={{ display: "flex", gap: ".5rem", alignItems: "flex-start", fontSize: ".85rem", margin: ".5rem 0" }}>
        <input type="checkbox" checked={tried} onChange={(e) => setTried(e.target.checked)} />
        <span>
          I have tried the free demo. I understand this is a digital product that
          is available immediately, and that I cannot get a refund just because I
          changed my mind. Any refund right the law gives me stays.
        </span>
      </label>
      <button type="button" disabled={busy || !tried} onClick={() => void buy()}>
        {busy ? "Opening payment…" : "Buy Founder access"}
      </button>
    </>
  );
}
