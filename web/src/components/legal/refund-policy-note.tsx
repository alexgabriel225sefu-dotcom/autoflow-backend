import type { CSSProperties } from "react";
import Link from "next/link";
import { DEMO_CONDITIONS_NOTE, PURCHASE_NOTE } from "@/content/refund-policy";

/**
 * The short refund note on pricing and on the buy screen.
 * The sentences live in one module so the checkout control cannot
 * disagree with the refunds page.
 */
export function RefundPolicyNote({
  className,
  style,
}: {
  className?: string;
  style?: CSSProperties;
}) {
  return (
    <p className={className} style={style}>
      {PURCHASE_NOTE} {DEMO_CONDITIONS_NOTE}{" "}
      <Link href="/refunds">Refund policy</Link>
    </p>
  );
}
