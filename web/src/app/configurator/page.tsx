"use client";

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { ShieldCheck } from "lucide-react";

function ConfiguratorContent() {
  const params = useSearchParams();
  const key = params.get("key");

  return (
    <main className="min-h-screen flex items-center justify-center px-4" style={{ background: "var(--background)" }}>
      <div className="max-w-lg w-full text-center space-y-6">
        <div className="w-16 h-16 rounded-2xl bg-amber-500/10 border border-amber-500/20 flex items-center justify-center mx-auto">
          <ShieldCheck className="w-8 h-8 text-amber-500" />
        </div>
        <h1 className="text-3xl font-extrabold tracking-tight">Setup Your Bot</h1>
        <p className="text-white/50 leading-relaxed">
          Your purchase was successful. Follow the instructions below to configure and deploy your Apex Trade Bot.
        </p>
        {key && (
          <div className="rounded-xl border border-amber-500/20 bg-amber-500/05 p-4 text-left">
            <p className="text-[10px] uppercase tracking-widest text-white/40 font-semibold mb-1">License Key</p>
            <p className="font-mono text-sm text-amber-400 break-all">{key}</p>
          </div>
        )}
        <p className="text-xs text-white/30">Check your email for full setup instructions and source code download link.</p>
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
