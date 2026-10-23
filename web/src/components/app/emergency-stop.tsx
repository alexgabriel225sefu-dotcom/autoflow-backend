"use client";
import { useState } from "react";
import { OctagonAlert } from "lucide-react";
import { api, type ApiError, type ApiResult, type AutomationState, type EmergencyResult } from "@/lib/api";
import { invalidate } from "@/lib/use-api";
import { runAutomationControl, type ControlResult } from "./automation-control";
import { ErrorNotice } from "./state";

/**
 * The client's own emergency button: stop trading, and optionally get out.
 *
 * Two deliberate choices, and a refusal to say more than was measured:
 *
 *  - "Stop and close" and "Stop only" are separate buttons, each behind its own
 *    confirmation. The first closes real (demo) positions at market and cannot
 *    be undone; nothing here runs on a single click.
 *  - The result is the SERVER's sentence plus one line per position. "Flat" is
 *    shown only when the server says `allFlat`, which it says only after a
 *    fresh read of the account. Anything else is shown as not confirmed.
 */
const OUTCOME_WORDS: Record<string, string> = {
  closed: "closed",
  already_closed: "was already closed",
  partial: "only partly closed — the rest is still open",
  refused: "not closed",
  unknown: "result unknown — check Positions before retrying",
  failed: "failed",
};

export function EmergencyStop({
  ctid, reloadAutomation,
}: {
  ctid: number | string | null;
  /** The caller's own read of `automation`, so "Stop only" can verify. */
  reloadAutomation: () => Promise<ApiResult<AutomationState> | undefined>;
}) {
  const [step, setStep] = useState<"idle" | "choose" | "close" | "stop">("idle");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);
  const [result, setResult] = useState<EmergencyResult | null>(null);
  const [stopOnly, setStopOnly] = useState<ControlResult | null>(null);

  /**
   * STOP ONLY runs the existing automation stop — the same function as the Stop
   * button, with the same reload-and-verify — and touches no position.
   *
   * STOP AND CLOSE is one server call that stops the loop first and then closes
   * each open position BY ITS POSITION ID through the demo-only close path (the
   * route `accounts/{ctid}/positions/{id}/close` calls that same function),
   * re-reads the account, and only then answers. It is one call rather than a
   * chain driven from here so that a closed tab halfway cannot leave the loop
   * stopped and the positions open without anyone being told.
   */
  async function fire(closePositions: boolean) {
    setBusy(true);
    setErr(null);
    setResult(null);
    setStopOnly(null);
    if (!closePositions) {
      const res = await runAutomationControl("stop", { reload: reloadAutomation });
      setBusy(false);
      setStep("idle");
      setStopOnly(res);
      return;
    }
    const r = await api<EmergencyResult>("emergency/stop", {
      method: "POST",
      body: { confirm: true, closePositions: true, ...(ctid ? { ctid: String(ctid) } : {}) },
    });
    setBusy(false);
    setStep("idle");
    invalidate("automation", "positions", "orders", "journal?limit=8", "me");
    if (r.ok) setResult(r.data); else setErr(r);
  }

  return (
    <div className="notice" style={{ marginTop: "var(--sp-3)" }}>
      <div className="btn-row">
        {step === "idle" ? (
          <button className="btn btn-danger" onClick={() => { setResult(null); setErr(null); setStopOnly(null); setStep("choose"); }}>
            <OctagonAlert className="ico" aria-hidden /> Emergency
          </button>
        ) : null}

        {step === "choose" ? (
          <>
            <span className="muted" style={{ fontSize: ".82rem" }}>
              Stop trading now. What about what is already open?
            </span>
            <button className="btn btn-danger" onClick={() => setStep("close")}>Stop and close positions</button>
            <button className="btn" onClick={() => setStep("stop")}>Stop only</button>
            <button className="btn btn-ghost" onClick={() => setStep("idle")}>Cancel</button>
          </>
        ) : null}

        {step === "close" ? (
          <>
            <span className="muted" style={{ fontSize: ".82rem" }}>
              This stops automation and closes every open position on this demo
              account at market. It cannot be undone.
            </span>
            <button className="btn btn-danger" disabled={busy} onClick={() => void fire(true)}>
              {busy ? "Working…" : "Yes, stop and close"}
            </button>
            <button className="btn btn-ghost" disabled={busy} onClick={() => setStep("choose")}>Back</button>
          </>
        ) : null}

        {step === "stop" ? (
          <>
            <span className="muted" style={{ fontSize: ".82rem" }}>
              This stops automation and closes nothing. Anything open keeps the
              stop and target it was given at your broker.
            </span>
            <button className="btn" disabled={busy} onClick={() => void fire(false)}>
              {busy ? "Working…" : "Yes, stop only"}
            </button>
            <button className="btn btn-ghost" disabled={busy} onClick={() => setStep("choose")}>Back</button>
          </>
        ) : null}
      </div>

      {err ? <ErrorNotice error={err} /> : null}

      {stopOnly ? (
        <p role={stopOnly.ok ? "status" : "alert"} data-stop-only={stopOnly.ok ? "ok" : "error"}
           style={{ marginTop: "var(--sp-2)" }}>
          {stopOnly.text}
        </p>
      ) : null}

      {result ? (
        <div role="status" style={{ marginTop: "var(--sp-2)" }}>
          <p>{result.sentence}</p>
          {result.allFlat === true ? (
            <p data-flat="yes" style={{ fontWeight: 600 }}>Confirmed flat.</p>
          ) : result.closes !== null ? (
            <p data-flat="no" style={{ fontWeight: 600 }}>Not confirmed flat.</p>
          ) : null}
          {result.closes && result.closes.length ? (
            <ul className="plain-list">
              {result.closes.map((c) => (
                <li key={c.positionId}>
                  {c.symbol ?? "position"} {c.side ?? ""} #{c.positionId} — {OUTCOME_WORDS[c.outcome] ?? c.outcome}
                  {c.detail ? ` (${c.detail})` : ""}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
