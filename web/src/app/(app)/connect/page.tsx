"use client";
import { useEffect, useState } from "react";
import { api, type CtraderStatus } from "@/lib/api";
import { useRead } from "@/lib/use-api";
import { ErrorNotice, Spinner } from "@/components/app/state";

/**
 * Connecting a cTrader account. Three steps, and the third is the point.
 *
 * The callback finishes nothing — it hands back a nonce, and this page
 * completes the link with an authenticated call. That is what stops somebody
 * starting a flow for THEIR account and getting a victim to approve it.
 */
/**
 * Where the pending nonce is kept between step 1 and step 2.
 *
 * It used to be React state and nothing else, with the reasoning that a stale
 * nonce in storage "would invite a completion attempt against an attempt that
 * is long gone". That reasoning is right and the conclusion was wrong, because
 * it treated losing the tab's memory as the exception. On a phone it is the
 * normal case: step 1 opens cTrader in a NEW tab, iOS discards the JS state of
 * the backgrounded tab under memory pressure, and returning reloads it. The
 * page then showed "Step 1" again, the visitor pressed Connect again, and the
 * only visible outcome was RATE_LIMITED from the oauth bucket. The flow was
 * unfinishable on mobile. Found on the first real connection attempt.
 *
 * sessionStorage, not localStorage: it is scoped to this tab and survives the
 * reload, which is exactly the lifetime the nonce should have. And the stale
 * case the original comment worried about is handled directly rather than by
 * refusing to persist — the value is stored with the time it was issued and
 * ignored once it is older than the server's own PENDING_TTL_S, so the page
 * cannot offer to finish something the server has already forgotten.
 */
const NONCE_KEY = "a4t.ctrader.pending";
const NONCE_TTL_MS = 900_000;   // PENDING_TTL_S on the server, in milliseconds

function loadNonce(): string | null {
  try {
    const raw = sessionStorage.getItem(NONCE_KEY);
    if (!raw) return null;
    const { nonce, at } = JSON.parse(raw) as { nonce?: string; at?: number };
    if (!nonce || !at || Date.now() - at > NONCE_TTL_MS) {
      sessionStorage.removeItem(NONCE_KEY);
      return null;
    }
    return nonce;
  } catch {
    // A private window, disabled site data, or a value somebody else wrote.
    // None of those should break the page; they just mean no resume.
    return null;
  }
}

function saveNonce(nonce: string | null) {
  try {
    if (nonce === null) sessionStorage.removeItem(NONCE_KEY);
    else sessionStorage.setItem(NONCE_KEY,
      JSON.stringify({ nonce, at: Date.now() }));
  } catch { /* storage unavailable — the in-memory path still works */ }
}

/** Errors that mean this attempt is finished, whatever the page thinks. */
const TERMINAL = new Set([
  "STATE_UNKNOWN", "STATE_EXPIRED", "STATE_REPLAYED", "NO_CODE",
]);

export default function ConnectPage() {
  const status = useRead<CtraderStatus>("ctrader/status");
  const [pending, setPending] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Resume after the tab was reloaded while the visitor was away at cTrader.
  useEffect(() => { setPending(loadNonce()); }, []);

  function remember(nonce: string | null) {
    setPending(nonce);
    saveNonce(nonce);
  }

  async function begin() {
    setBusy(true); setErr(null);
    const r = await api<{ authorizeUrl: string; nonce: string }>(
      "ctrader/connect", { method: "POST" });
    setBusy(false);
    if (!r.ok) return setErr(`${r.code}: ${r.message}`);
    remember(r.data.nonce);
    window.open(r.data.authorizeUrl, "_blank", "noopener");
  }

  async function complete() {
    if (!pending) return;
    setBusy(true); setErr(null);
    const r = await api<{ ctrader: CtraderStatus }>(
      "ctrader/complete", { method: "POST", body: { nonce: pending } });
    setBusy(false);
    if (!r.ok) {
      // A terminal refusal must clear the stored nonce, or the page offers
      // "finish here" for ever against an attempt that can never succeed.
      if (TERMINAL.has(r.code)) remember(null);
      return setErr(`${r.code}: ${r.message}`);
    }
    remember(null);
    void status.reload();
  }

  return (
    <main>
      <div className="page-head">
        <div>
          <h1>Connect cTrader</h1>
          <span className="sub">
            Orders are placed on an account you connect yourself.
          </span>
        </div>
      </div>

      {/* Said where the decision is made, not only in a footer. */}
      <div className="notice notice-accent">
        Your broker tokens are stored encrypted on the server and are never
        sent to this page. Apex4Traders cannot move money in or out of your
        account — it can only place and close trades on it.
      </div>

      <section className="card">
        <div className="card-head"><h2>Status</h2></div>
        {status.loading && !status.result ? <Spinner /> : null}
        {status.result && !status.result.ok
          ? <ErrorNotice error={status.result} onRetry={status.reload} /> : null}
        {status.result?.ok ? (
          status.result.data.connected ? (
            <>
              <p><span className="pill pill-ok">Connected</span>{" "}{status.result.data.accounts.length} account(s) available</p>
              <a className="btn btn-ghost btn-sm" style={{ marginTop: ".6rem" }} href="/accounts">Choose which one to trade</a>
            </>
          ) : <p className="muted">No cTrader account is connected.</p>
        ) : null}
      </section>

      <section className="card">
        <div className="card-head"><h2>{pending ? "Step 2 — finish here" : "Step 1 — authorise"}</h2><span className="pill pill-accent">{pending ? "2 of 2" : "1 of 2"}</span></div>
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
