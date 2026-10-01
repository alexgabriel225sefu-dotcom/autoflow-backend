"use client";
import { useEffect, useRef, useState } from "react";
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

/** Errors that mean this attempt is finished, whatever the page thinks.
 *
 * This list grew when the authorization code started being spent at the
 * callback. Before that, EXCHANGE_FAILED and NO_TOKEN could not happen at
 * this step at all; now they can, and they are as final as the rest — the
 * code behind them is spent either way, so offering "finish" again can only
 * fail. Leaving them out is how a page ends up inviting a click that is
 * guaranteed to do nothing, which is exactly what the owner sat through.
 */
const TERMINAL = new Set([
  "STATE_UNKNOWN", "STATE_EXPIRED", "STATE_REPLAYED", "NO_CODE",
  "PROVIDER_REFUSED", "EXCHANGE_FAILED", "NO_TOKEN",
]);

/** Deliberately NOT terminal.
 *
 * The token is already parked by the time accounts are listed, so a failure
 * here is the broker being briefly unreachable, not the attempt being dead.
 * Clearing the nonce would throw away a good token and send the visitor
 * through cTrader again for nothing.
 */
const RETRYABLE = new Set(["ACCOUNTS_FAILED", "RATE_LIMITED"]);

export default function ConnectPage() {
  const status = useRead<CtraderStatus>("ctrader/status");
  const [pending, setPending] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [diagnosticId, setDiagnosticId] = useState<string | null>(null);
  // Guards the automatic finish. Survives re-renders; never reset, because
  // one arrival with ?n= is one attempt.
  const autoRan = useRef(false);
  // Whether a broker account is already linked. Drives the heading below,
  // which must never invite step 1 at somebody who has finished step 2.
  const isConnected = Boolean(
    status.result?.ok && status.result.data.connected);

  // Resume after the visitor comes back from cTrader. Two ways in, because on
  // a phone only the second one is reliable:
  //   ?n=<nonce>   the callback page sends them back here carrying it, which
  //                works even when the original tab is gone entirely
  //   sessionStorage  the same tab, reloaded
  // The URL wins: it is the fresher of the two, and it is the one that exists
  // when iOS has discarded the tab the flow started in.
  useEffect(() => {
    let fromUrl: string | null = null;
    try {
      fromUrl = new URLSearchParams(window.location.search).get("n");
    } catch { /* no URL access is not a reason to fail */ }
    if (fromUrl) {
      remember(fromUrl);
      // Take it out of the address bar: it has served its purpose, and a nonce
      // left in the URL ends up in history and in anything the visitor shares.
      try {
        window.history.replaceState({}, "", window.location.pathname);
      } catch { /* not fatal */ }
      // Arriving with ?n= means cTrader has just approved and the callback
      // has already spent the code. Making the visitor press one more button
      // adds nothing: this step runs as them either way, which is what the
      // session cookie on this request proves. So finish it.
      //
      // ONCE. A ref, not state: an effect that re-runs on render would spend
      // the oauth budget in seconds, and the owner has already spent an
      // afternoon looking at RATE_LIMITED.
      if (!autoRan.current) {
        autoRan.current = true;
        void complete(fromUrl);
      }
      return;
    }
    const stored = loadNonce();
    // set-state-in-effect is disabled here deliberately, not worked around.
    // The obvious alternative — a lazy useState initialiser — would read
    // sessionStorage during render, which does not exist on the server: the
    // server would render "no pending attempt", the client would render one,
    // and the hydration mismatch is a worse bug than an extra render. An
    // effect is where a browser-only value is allowed to arrive.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (stored) setPending(stored);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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

  async function complete(nonceOverride?: string) {
    // The override exists because the automatic finish runs from the effect
    // that discovered the nonce, before React has re-rendered with it in
    // state. Reading `pending` there would read null and do nothing.
    const nonce = nonceOverride ?? pending;
    if (!nonce) {
      // Never silent. A button that can do nothing without saying so cannot
      // be diagnosed from outside the browser, and this flow has already cost
      // several rounds of "I press it and nothing happens" with no request
      // reaching the server and no message on screen.
      setErr("NO_PENDING: there is no connection attempt to finish. "
             + "Start again, or open Accounts if you are already connected.");
      return;
    }
    setBusy(true); setErr(null); setDiagnosticId(null);
    const r = await api<{ ctrader: CtraderStatus }>(
      "ctrader/complete", { method: "POST", body: { nonce } });
    setBusy(false);
    if (!r.ok) {
      // A terminal refusal must clear the stored nonce, or the page offers
      // "finish here" for ever against an attempt that can never succeed.
      // A retryable one must NOT: the token may already be parked.
      if (TERMINAL.has(r.code) && !RETRYABLE.has(r.code)) remember(null);
      setDiagnosticId(
        typeof r.diagnosticId === "string" ? r.diagnosticId : null);
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
        {/* WHAT THIS BRANCH IS FOR
            A finished connection used to leave "Step 1 — authorise" on
            screen with a Connect button under it, because the heading was
            chosen from `pending` alone and `pending` is cleared on success.
            The owner connected successfully and pressed Connect again five
            seconds later — the server log shows both — and reported the
            feature as broken. It was not; the page was telling him he had
            not started. The server's connected verdict must also beat a
            stale local pending nonce: sessionStorage is a recovery aid, not
            the source of truth. */}
        <div className="card-head">
          <h2>{isConnected ? "Account connected"
               : pending ? "Step 2 — finish here"
               : "Step 1 — authorise"}</h2>
          <span className="pill pill-accent">
            {isConnected ? "Done" : pending ? "2 of 2" : "1 of 2"}
          </span>
        </div>
        {isConnected ? (
          <>
            <p>
              cTrader is linked. Nothing is being traded yet — choose which
              account Apex4Traders should use.
            </p>
            {pending ? (
              <>
                <p className="notice" style={{ marginTop: ".6rem" }}>
                  A connection attempt from this tab has not been finished.
                  If you were adding a second account, finish it here.
                </p>
                {/* WHY THIS BUTTON SURVIVES THE CONNECTED BRANCH
                    The server's verdict beating a stale nonce is right, but
                    not every pending nonce is stale. Somebody already linked
                    who starts a SECOND connection and whose automatic finish
                    is refused retryably — RATE_LIMITED, ACCOUNTS_FAILED —
                    still holds a live attempt whose code is spent and whose
                    token is parked. Without this, that token cannot be
                    claimed and the only offer is another round trip through
                    cTrader to obtain something already obtained.
                    complete(), never begin(): begin() would throw it away. */}
                <button className="btn btn-ghost" style={{ marginTop: ".4rem" }}
                        onClick={() => void complete()} disabled={busy}>
                  {busy ? "Finishing…" : "Finish the saved attempt"}
                </button>
              </>
            ) : null}
            <div className="btn-row">
              <a className="btn" href="/accounts">Choose an account</a>
              {/* Demoted, not removed: somebody with a second broker account
                  still needs a way to add it. */}
              <button className="btn btn-ghost" onClick={begin} disabled={busy}>
                {busy ? "Preparing…" : "Connect another account"}
              </button>
            </div>
          </>
        ) : !pending ? (
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
            {/* No "already connected" notice here: this branch is reached
                only when isConnected is false, so the test would never be
                true. It was live when `pending` took precedence; the
                connected branch above carries that job now. */}
            <div className="btn-row">
              {/* Wrapped, not passed directly: complete() now takes an
                  optional nonce, and a bare handler would hand it the click
                  event as one. The typechecker caught that. */}
              <button className="btn" onClick={() => void complete()}
                      disabled={busy}>
                {busy ? "Finishing…" : "I have approved — finish"}
              </button>
              <button className="btn btn-ghost" onClick={() => setPending(null)} disabled={busy}>
                Cancel
              </button>
            </div>
          </>
        )}
        {err ? (
          <div className="notice notice-error" role="alert">
            {err}
            {/* Shown so a failure can be reported by reading eight characters
                aloud instead of sending a screenshot of a page that has a
                live session on it. */}
            {diagnosticId ? (
              <div style={{ marginTop: ".5rem", fontFamily: "ui-monospace, monospace",
                            fontSize: ".85em", opacity: .75, userSelect: "all" }}>
                Reference: {diagnosticId}
              </div>
            ) : null}
          </div>
        ) : null}
      </section>
    </main>
  );
}

