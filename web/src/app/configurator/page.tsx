"use client";

import { Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { BrandLockup } from "@/components/brand/logo";

/**
 * The post-purchase landing page.
 *
 * It used to say "Setup Your Bot", "deploy your Apex Trade Bot" and "check
 * your email for the source code download link" — three statements about a
 * product that no longer exists. Nothing is downloaded, nothing is deployed
 * by the client, and there is no bot.
 *
 * The route is kept rather than deleted because it is the return URL the
 * previous checkout used, and a paid customer following an old link should
 * land somewhere that makes sense rather than on a 404.
 */
function ConfiguratorContent() {
  const key = useSearchParams().get("key");

  return (
    <main className="a4t">
      <div className="legacy">
        <div style={{ marginBottom: "var(--sp-5)" }}>
          <Link href="/"><BrandLockup size={24} /></Link>
        </div>

        <h1>Setting up your account</h1>
        <p>
          Apex4Traders runs in your browser. There is nothing to download and
          nothing to install.
        </p>

        {key ? (
          <div className="notice" style={{ marginTop: "var(--sp-4)" }}>
            <p className="label-xs">Reference</p>
            <p className="mono" style={{ wordBreak: "break-all" }}>{key}</p>
            <p className="muted" style={{ fontSize: ".82rem", marginTop: ".4rem" }}>
              {/* Never "your licence is active". Only the verified payment
                  webhook decides that, and this page cannot see it. */}
              Keep this reference if you need to contact support. Your licence
              state is shown on the Licence page once your payment has been
              confirmed by the payment provider.
            </p>
          </div>
        ) : null}

        <h2>What happens next</h2>
        <ol className="muted" style={{ fontSize: ".9rem", lineHeight: 1.8, paddingLeft: "1.2rem" }}>
          <li>Sign in and confirm your email address.</li>
          <li>Connect a cTrader demo account — you keep control of it, and can
            disconnect it at any time.</li>
          <li>Build a rule from named conditions and preview what it would
            decide on real bars.</li>
          <li>Activate the rule, then start automation on the demo account.</li>
        </ol>

        <div className="btn-row" style={{ marginTop: "var(--sp-5)" }}>
          <Link className="btn" href="/dashboard">Go to the dashboard</Link>
          <Link className="btn btn-ghost" href="/license">Check your licence</Link>
        </div>

        <p className="dim" style={{ fontSize: ".8rem", marginTop: "var(--sp-5)" }}>
          Live trading is not available in this release. Automation runs on
          demo accounts only.
        </p>
      </div>
    </main>
  );
}

export default function ConfiguratorPage() {
  return (
    <Suspense>
      <ConfiguratorContent />
    </Suspense>
  );
}
