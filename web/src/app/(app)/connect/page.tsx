"use client";
import { useState } from "react";
import { api, type CtraderStatus } from "@/lib/api";
import { useRead } from "@/lib/use-api";
import { ErrorNotice, Spinner, StatusPill } from "@/components/app/state";

/**
 * Connecting a cTrader account. Three steps, and the third is the point.
 *
 * The callback finishes nothing — it hands back a nonce, and this page
 * completes the link with an authenticated call. That is what stops somebody
 * starting a flow for THEIR account and getting a victim to approve it.
 */
export default function ConnectPage() {
  const status = useRead<CtraderStatus>("ctrader/status");
  const [pending, setPending] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function begin() {
    setBusy(true); setErr(null);
    const r = await api<{ authorizeUrl: string; nonce: string }>(
      "ctrader/connect", { method: "POST" });
    setBusy(false);
    if (!r.ok) return setErr(`${r.code}: ${r.message}`);
    // The nonce is kept in memory for this tab only. It is not a credential,
    // and it is not written to localStorage — a stale one in storage would
    // invite a completion attempt against an attempt that is long gone.
    setPending(r.data.nonce);
    window.open(r.data.authorizeUrl, "_blank", "noopener");
  }

  async function complete() {
    if (!pending) return;
    setBusy(true); setErr(null);
    const r = await api<{ ctrader: CtraderStatus }>(
      "ctrader/complete", { method: "POST", body: { nonce: pending } });
    setBusy(false);
    if (!r.ok) return setErr(`${r.code}: ${r.message}`);
    setPending(null);
    void status.reload();
  }

  return (
    <main>
      <h1>Connect cTrader</h1>
      <p className="muted">
        Apex4Traders places orders on a cTrader account you connect yourself.
        Your broker tokens are stored encrypted on the server and are never
        sent to this page.
      </p>

      <section className="card">
        <h2>Status</h2>
        {status.loading && !status.result ? <Spinner /> : null}
        {status.result && !status.result.ok
          ? <ErrorNotice error={status.result} onRetry={status.reload} /> : null}
        {status.result?.ok ? (
          status.result.data.connected ? (
            <>
              <p>Connected · {status.result.data.accounts.length} account(s)</p>
              <a className="btn btn-ghost" href="/accounts">Choose which one to trade</a>
            </>
          ) : <p className="muted">No cTrader account is connected.</p>
        ) : null}
      </section>

      <section className="card">
        <h2>{pending ? "Step 2 — finish here" : "Step 1 — authorise"}</h2>
        {!pending ? (
          <>
            <p className="muted">
              We will open cTrader in a new tab. Sign in there and approve
              access, then come back to this page.
            </p>
            <button className="btn" onClick={begin} disabled={busy}>
              {busy ? "Preparing…" : "Connect cTrader"}
            </button>
          </>
        ) : (
          <>
            <p>
              Once you have approved access in the cTrader tab, finish the
              connection here.
            </p>
            <p className="muted">
              This last step runs as you — which is how we know the account
              being linked is being linked by its owner.
            </p>
            <div className="btn-row">
              <button className="btn" onClick={complete} disabled={busy}>
                {busy ? "Finishing…" : "I have approved — finish"}
              </button>
              <button className="btn btn-ghost" onClick={() => setPending(null)} disabled={busy}>
                Cancel
              </button>
            </div>
          </>
        )}
        {err ? <div className="notice notice-error" role="alert">{err}</div> : null}
      </section>
    </main>
  );
}
