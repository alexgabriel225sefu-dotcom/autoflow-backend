"use client";

import { useRead } from "@/lib/use-api";
import type { PurchaseConfirmation as PurchaseConfirmationRecord } from "@/lib/api";

/**
 * The receipt. The words come from the server, which stored the consent
 * (account, time, policy version) before checkout and completes them when
 * access is granted. This component does not invent a timestamp.
 */
export function PurchaseConfirmation({ justPaid }: { justPaid: boolean }) {
  const read = useRead<PurchaseConfirmationRecord>(
    "billing/purchase-confirmation",
    justPaid ? 15_000 : 0,
  );
  const data = read.result?.ok ? read.result.data : null;
  if (data?.recorded && data.confirmation) {
    return (
      <div className="notice notice-accent" role="status">
        <p className="muted" style={{ fontSize: ".85rem", margin: 0 }}>
          {data.confirmation}
        </p>
      </div>
    );
  }
  if (!justPaid) return null;
  return (
    <div className="notice" role="status">
      <p className="muted" style={{ fontSize: ".85rem", margin: 0 }}>
        The purchase confirmation is kept on this account. It names the time
        you consented, the refund policy version and your account. It is not
        available to read just now.
      </p>
    </div>
  );
}
