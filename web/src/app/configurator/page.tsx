"use client";

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { ShieldCheck } from "lucide-react";

function ConfiguratorContent() {
  const params = useSearchParams();
  const key = params.get("key");

  return (
    <main className="a4t" style={{ display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div className="legacy" style={{ textAlign: "center" }}>
        <div style={{ width: 56, height: 56, borderRadius: 14, background: "var(--a4t-accent-wash)", border: "1px solid var(--a4t-accent-dim)", display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 1.2rem" }}>
          <ShieldCheck style={{ width: 26, height: 26, color: "var(--a4t-accent)" }} />
        </div>
        <h1>Setup Your Bot</h1>
        <p>
          Your purchase was successful. Follow the instructions below to configure and deploy your Apex Trade Bot.
        </p>
        {key && (
          <div className="notice" style={{ textAlign: "left" }}>
            <p className="label-xs">License Key</p>
            <p className="mono" style={{ wordBreak: "break-all", color: "var(--a4t-accent)" }}>{key}</p>
          </div>
        )}
        <p className="dim" style={{ fontSize: ".78rem" }}>Check your email for full setup instructions and source code download link.</p>
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
