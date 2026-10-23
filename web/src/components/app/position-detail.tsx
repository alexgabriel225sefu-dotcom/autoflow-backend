"use client";
import { useEffect, useRef, useState } from "react";
import { api, type ApiResult, type ClosePositionRead, type Position } from "@/lib/api";
import { ErrorNotice } from "./state";
import { Num, Side } from "./table";

/**
 * One open position, and the only place a position is closed from.
 *
 * WHAT IS GUARANTEED HERE
 *
 * - A close is by POSITION ID, in the path of the demo-only close route. Never
 *   by symbol: two positions on one instrument are two positions, and a close
 *   by symbol would take whichever the broker found first.
 * - The close button exists only for a DEMO account. For anything else the
 *   page says closing from here is not available and to close it in cTrader.
 *   There is no live close path in this file to be reached by accident.
 * - Nothing is sent on the first click. Confirmation is in the page, not in a
 *   native dialog: a dialog is invisible to automated checks and easy to dismiss
 *   by reflex on a phone, and a dismissed one used to leave the button looking
 *   dead.
 * - The result is the server's: its status (FILLED, PARTIAL, ALREADY_CLOSED) and
 *   its sentence, verbatim. Only FILLED and ALREADY_CLOSED mean the position is
 *   closed. PARTIAL says the remainder is still open.
 */
const NOT_AVAILABLE = "Closing from here is not available yet. Close it in cTrader.";

type Stage = "idle" | "confirm" | "sending";

export function PositionDetail({
  position, accountId, mode, stillOpen, onBack, onClosed,
}: {
  position: Position;
  accountId: number | string | undefined;
  mode: string | undefined;
  /** False once the latest read no longer lists this position. */
  stillOpen: boolean;
  onBack: () => void;
  /** Called after a close request was answered, so the caller can re-read. */
  onClosed: () => void;
}) {
  const [stage, setStage] = useState<Stage>("idle");
  const [result, setResult] = useState<ApiResult<ClosePositionRead> | null>(null);
  const head = useRef<HTMLHeadingElement>(null);

  // Opening the detail brings it into view and moves focus to it. It sits above
  // the table, but on a phone the table is tall enough that a card that
  // appeared off-screen looked like a button that did nothing.
  useEffect(() => {
    head.current?.focus();
    head.current?.scrollIntoView?.({ block: "start" });
  }, [position.positionId]);

  const id = String(position.positionId);
  const canClose = mode === "demo" && accountId !== undefined && stillOpen;

  async function close() {
    setStage("sending");
    const r = await api<ClosePositionRead>(
      `accounts/${encodeURIComponent(String(accountId))}/positions/${encodeURIComponent(id)}/close`,
      { method: "POST" },
    );
    setResult(r);
    setStage("idle");
    onClosed();
  }

  const status = result?.ok ? result.data.close?.status : undefined;
  const sentence = result?.ok ? (result.data.close?.sentence ?? result.data.sentence) : undefined;
  const isClosed = status === "FILLED" || status === "ALREADY_CLOSED";

  return (
    <section className="card" aria-label={`Position ${id}`}>
      <div className="card-head">
        <h2 ref={head} tabIndex={-1}>{position.symbol} · Position {id}</h2>
        <button className="btn btn-ghost btn-sm" onClick={onBack}>Back</button>
      </div>

      <p className="sub">
        <Side side={position.side} /> · <Num value={position.units} /> units · Entry <Num value={position.entryPrice} />
        {" · "}Stop <Num value={position.stopLoss} />{" · "}Target <Num value={position.takeProfit} />
      </p>
      {position.warning ? <p className="notice notice-warn" role="note">{position.warning}</p> : null}

      {!stillOpen && !result ? (
        <p className="sub" role="status">This position is no longer listed as open.</p>
      ) : null}

      {canClose && !isClosed ? (
        stage === "idle" ? (
          <button className="btn btn-danger" onClick={() => setStage("confirm")}>Close position</button>
        ) : (
          <div className="btn-row">
            <span className="muted" style={{ fontSize: ".85rem" }}>
              Close {position.symbol} position {id} at market now? This cannot be undone.
            </span>
            <button className="btn btn-danger" disabled={stage === "sending"} onClick={() => void close()}>
              {stage === "sending" ? "Closing…" : "Yes, close it"}
            </button>
            <button className="btn btn-ghost" disabled={stage === "sending"} onClick={() => setStage("idle")}>Cancel</button>
          </div>
        )
      ) : null}

      {mode !== "demo" ? <p className="sub" data-close-unavailable>{NOT_AVAILABLE}</p> : null}

      {result?.ok ? (
        <div role="status" data-close-status={status ?? "unknown"} style={{ marginTop: "var(--sp-2)" }}>
          <p><strong>{status ?? "Answer received"}</strong>{sentence ? ` — ${sentence}` : ""}</p>
          {status === "PARTIAL" ? (
            <p className="muted">
              Only part of the position was closed
              {result.data.close?.remainingVolume != null ? ` (${result.data.close.remainingVolume} still open)` : ""}.
              The rest is still open at your broker.
            </p>
          ) : null}
        </div>
      ) : null}
      {result && !result.ok ? <ErrorNotice error={result} /> : null}
    </section>
  );
}
