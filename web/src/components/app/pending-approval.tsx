"use client";
/**
 * The setup your rule found and will not place until you say so.
 *
 * WHY THIS COMPONENT EXISTS, AND WHAT HAPPENED WITHOUT IT
 *
 * The engine has an automation level called Approval Required: it finds a
 * setup, proposes it, and places nothing until a person agrees. The only
 * place that proposal could ever be answered was a Telegram chat — so for a
 * client of this platform the level meant a loop that found setups, wrote a
 * proposal nobody could see, and waited forever while the dashboard said
 * Running. This card is the answer half. `GET approvals` is the question.
 *
 * WHAT IT REFUSES TO DO
 *
 *   It never decides whether approving is allowed. `actionable` and `refusal`
 *   are the server's verdict and the button follows them. A second copy of
 *   that rule in the browser would be the copy that offered Approve on a
 *   setup the backend then refused — and the client would read the refusal as
 *   a fault rather than as the rule they are actually subject to.
 *
 *   It never shows a price it was not given. The price and the reasoning
 *   arrive in a separate write from the proposal itself, so they can be
 *   genuinely unknown; `detailKnown` distinguishes "nothing to say" from "we
 *   do not know", and an unknown price is said out loud rather than rendered
 *   as a blank that looks like agreement.
 *
 *   It never claims there is no setup waiting when the read failed. A card
 *   that simply does not appear is the same silence this whole piece of work
 *   exists to remove, so a failed read says so and offers a retry.
 *
 * THE COUNTDOWN IS MEASURED LOCALLY, FROM THE SERVER'S NUMBER
 *
 * The server sends `expiresInSec` — how long is left as of the moment it
 * answered — and the card counts down from there using the elapsed time on
 * this device. It deliberately does NOT compare `expiresAt` against the
 * browser's clock: a device whose clock is a few minutes out would show a
 * live setup as expired, or offer one that has gone. Only the DELTA of the
 * local clock is trusted, and every device agrees about that.
 */
import { useEffect, useState } from "react";
import { Clock } from "lucide-react";
import { api, type ApprovalRead, type ApprovalResult } from "@/lib/api";
import { invalidate, useRead } from "@/lib/use-api";
import { ConfirmAction } from "@/components/app/shell";
import { ErrorNotice } from "@/components/app/state";
import { Num, Side } from "@/components/app/table";

/** mm:ss, floored at zero. A negative countdown is a bug on display. */
function countdown(secs: number) {
  const s = Math.max(0, Math.floor(secs));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** What the server's refusal code means, in words a trader would use. */
function refusalWords(code: string | null, expired: boolean) {
  if (expired || code === "EXPIRED") {
    return "This setup has expired — it was found more than five minutes ago, "
      + "and the price has moved since. Your rule proposes the next one it "
      + "finds.";
  }
  if (code === "NOT_RUNNING") {
    return "Automation is not running, so this setup cannot be opened. "
      + "Stopping puts your account's own risk, stop and target back, and a "
      + "trade opened now would use those rather than this rule's.";
  }
  return null;
}

export function PendingApproval() {
  // Ten seconds: the setup expires in five minutes, and a client who answers
  // one in another tab should not be left looking at it here for long.
  const r = useRead<ApprovalRead>("approvals", 10_000);
  // Re-renders once a second so the countdown moves. It holds no derived
  // state of its own — the remaining time is computed from the server's
  // number and `lastSync` on every render, so a stale tick cannot survive a
  // reload.
  const [, setTick] = useState(0);
  useEffect(() => {
    const id = window.setInterval(() => setTick((n) => n + 1), 1000);
    return () => window.clearInterval(id);
  }, []);

  if (!r.result) return null;                       // first paint, not a claim

  if (!r.result.ok) {
    return (
      <section className="card">
        <div className="card-head"><h2>Waiting for your approval</h2></div>
        <ErrorNotice error={r.result} onRetry={r.reload} />
        <p className="muted" style={{ fontSize: ".8rem" }}>
          This is the check for a setup waiting on your decision. Until it
          succeeds, this screen cannot tell you whether one is waiting.
        </p>
      </section>
    );
  }

  const data = r.result.data;
  // "unknown" means the account's engine state could not be read. Nothing is
  // claimed either way, and there is nothing a client can do about it from
  // here, so the card stays out of the way.
  if (data.status !== "ok") return null;

  if (data.unreadable) {
    return (
      <section className="card">
        <div className="card-head"><h2>Waiting for your approval</h2></div>
        <div className="notice notice-warn" role="alert">
          <p style={{ fontWeight: 600 }}>A setup is stored and cannot be read</p>
          <p className="muted" style={{ fontSize: ".82rem" }}>
            It cannot be opened, and while it is there your rule will not
            propose another. Dismissing it clears the way.
          </p>
          <DismissButton onDone={r.reload} />
        </div>
      </section>
    );
  }

  const a = data.approval;
  if (!a) return null;                 // read succeeded; there is none waiting

  const elapsed = r.lastSync ? (Date.now() - r.lastSync) / 1000 : 0;
  const left = a.expiresInSec - elapsed;
  const gone = a.expired || left <= 0;
  // The server's verdict AND the clock. Either one saying no is a no: the
  // read can be up to ten seconds old, and a setup that expired in between
  // must stop being offered without waiting for the next poll.
  const canApprove = a.actionable && !gone;
  const why = refusalWords(a.refusal, gone);

  async function approve() {
    const res = await api<ApprovalResult>("approvals/approve", { method: "POST" });
    // Named paths, every one of them: this card sits on the dashboard beside
    // a positions panel and a journal panel that have just become wrong, and
    // the shell's unread badge has just changed too.
    invalidate("approvals", "positions", "journal?limit=8",
               "notifications?limit=1");
    if (!res.ok) return `${res.code}: ${res.message}`;
    // The server's own sentence. It is the only thing that knows whether the
    // broker confirmed the order or never answered, and those are different
    // facts a client has to act on differently.
    return res.data.detail ?? "Approved.";
  }

  return (
    <section className="card">
      <div className="card-head">
        <h2>Waiting for your approval</h2>
        <span className="pill pill-muted mono" aria-label="time left">
          <Clock className="ico" aria-hidden style={{ width: 14, height: 14 }} />
          {" "}{countdown(left)}
        </span>
      </div>

      <p className="muted" style={{ fontSize: ".8rem" }}>
        Your rule found this setup and placed nothing. It opens only if you
        approve it, and only while it is still current.
      </p>

      <div className="verdict-banner" data-kind={a.side === "BUY" ? "buy" : "sell"}>
        <div className="vb-body" style={{ flex: 1 }}>
          <p className="verdict" style={{ fontSize: "1.15rem" }}>
            <Side side={a.side} /> {a.symbol}
          </p>
          <p className="vb-note">
            {a.price !== null ? (
              <>at <span className="mono"><Num value={a.price} /></span></>
            ) : (
              /* Said rather than left blank. The price is a separate write
                 from the proposal, so "we were not told" is a real state and
                 an empty space would read as nothing to say. */
              <span className="dim">
                the price it was found at was not recorded
              </span>
            )}
            {a.confidence !== null ? <> · confidence {a.confidence}</> : null}
          </p>
        </div>
      </div>

      {/* The rule's own reason, in full. Not truncated and not summarised:
          it is the whole basis on which somebody is being asked to risk
          money, and it is short because the evaluator writes one line. */}
      <p style={{ fontSize: ".84rem", marginTop: "var(--sp-2)", marginBottom: 0 }}>
        <span className="dim" style={{ fontSize: ".7rem", letterSpacing: ".06em", textTransform: "uppercase" }}>
          Why
        </span>
        <br />
        {a.reasoning
          ? a.reasoning
          : a.detailKnown
            ? <span className="dim">no reason was recorded</span>
            : <span className="dim">
                the rule&apos;s reason for this setup was not recorded — the
                side and the instrument above are what is known
              </span>}
      </p>
      {a.keyFactors.length ? (
        <p className="muted" style={{ fontSize: ".8rem", marginBottom: 0 }}>
          {a.keyFactors.join(", ")}
        </p>
      ) : null}

      {why ? (
        <div className="notice notice-warn" role="status">
          <p className="muted" style={{ fontSize: ".82rem", margin: 0 }}>{why}</p>
        </div>
      ) : null}

      <div className="btn-row" style={{ marginTop: "var(--sp-3)" }}>
        <ConfirmAction
          label="Approve"
          /* A second step, like every other control here that moves money.
             It names the trade rather than asking "are you sure?", because
             the thing to check is the side and the instrument. */
          question={`Open ${a.side} ${a.symbol} now?`}
          disabled={!canApprove}
          /* The notice above already carries the reason, and the same
             sentence printed twice beside a disabled button reads as two
             problems rather than one. The fallback is for a refusal code
             this release has no words for: the server said no, and saying
             only that is better than inventing which no it was. */
          disabledReason={why ? undefined
            : !canApprove ? "This setup cannot be opened right now."
              : undefined}
          onConfirm={approve}
        />
        <DismissButton onDone={r.reload} />
      </div>
    </section>
  );
}

/**
 * Dismissing. Always available, including for an expired or unreadable
 * proposal: a client must be able to say no to anything the product is
 * asking them about, and while a proposal sits there the rule proposes
 * nothing else.
 */
function DismissButton({ onDone }: { onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<string | null>(null);
  return (
    <span className="btn-row">
      <button
        className="btn btn-ghost"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          const res = await api<ApprovalResult>("approvals/reject", { method: "POST" });
          setBusy(false);
          setOutcome(res.ok
            ? (res.data.alreadyGone
              ? "It had already been answered."
              : "Dismissed. Nothing was opened.")
            : `${res.code}: ${res.message}`);
          invalidate("approvals", "notifications?limit=1");
          onDone();
        }}
      >
        {busy ? "Working…" : "Dismiss"}
      </button>
      {outcome ? (
        <span className="muted" role="status" style={{ fontSize: ".82rem" }}>
          {outcome}
        </span>
      ) : null}
    </span>
  );
}
