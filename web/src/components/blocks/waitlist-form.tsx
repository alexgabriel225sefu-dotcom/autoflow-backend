"use client";
/**
 * Early access capture.
 *
 * The one thing a visitor can do today. Checkout is off and live execution is
 * off, so the honest ask is an address and a promise to write once — and this
 * form says exactly that, rather than implying a product they can use now.
 *
 * Every state it can be in is a state the server put it in. In particular a
 * failure says so and keeps what was typed, because the worst version of this
 * component is one that clears the field and shows nothing: the visitor
 * cannot tell whether they are on the list, and the usual guess is that they
 * are.
 */
import { useId, useRef, useState } from "react";
import { ArrowRight, Check, CircleAlert, Loader2 } from "lucide-react";
import { joinWaitlist, type ApiError } from "@/lib/api";

type State =
  | { kind: "idle" }
  | { kind: "sending" }
  | { kind: "joined"; repeat: boolean }
  | { kind: "failed"; error: ApiError };

export function WaitlistForm({
  source = "landing",
  className,
}: {
  source?: "landing" | "pricing" | "direct";
  className?: string;
}) {
  const [email, setEmail] = useState("");
  const [state, setState] = useState<State>({ kind: "idle" });
  const fieldId = useId();
  const noteId = `${fieldId}-note`;

  const inputRef = useRef<HTMLInputElement>(null);
  const [platform, setPlatform] = useState("");
  const [broker, setBroker] = useState("");
  const [asked, setAsked] = useState(false);

  async function answer(e: React.FormEvent) {
    e.preventDefault();
    setAsked(true);
    // Fire and forget, deliberately. The sign-up is already recorded; if this
    // fails there is nothing for the visitor to do about it and nothing worth
    // showing them. Their address — the thing that mattered — is safe.
    void joinWaitlist(email, source, { platform, broker });
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (state.kind === "sending") return;
    // Empty is a precondition of the form, not an answer from the server, so
    // it costs a round trip and invents a sentence to treat it as one. The
    // cursor landing in the empty field says it without either.
    if (email.trim() === "") {
      inputRef.current?.focus();
      return;
    }
    setState({ kind: "sending" });
    const r = await joinWaitlist(email, source);
    if (r.ok) {
      setState({ kind: "joined", repeat: r.data.status === "already" });
      return;
    }
    // The field keeps its value. Re-typing an address because the server was
    // briefly unreachable is the kind of small insult that loses the sign-up.
    setState({ kind: "failed", error: r });
  }

  if (state.kind === "joined") {
    return (
      <div className={className} role="status">
        <p className="wl-done">
          <Check className="ico" aria-hidden />
          {state.repeat
            ? "You are already on the list."
            : "You are on the list."}
        </p>
        <p className="wl-note">
          We will email you once when early access opens. Nothing else, and no
          one else gets your address.
        </p>

        {/* ASKED HERE, NOT ON THE WAY IN
            Which platform somebody trades on decides what this product
            supports next, and it is not a question worth losing a sign-up
            over. So the address is taken first and this is asked of people
            who have already said yes. Skipping it costs them nothing and the
            sign-up is already recorded. */}
        {asked ? (
          <p className="wl-note" role="status">Noted — thank you.</p>
        ) : (
          <form className="wl-ask" onSubmit={answer}>
            {/* This sentence is load-bearing, and a test enforces it.
                The dropdown below names MetaTrader, and a reader who met
                those names with no context could reasonably conclude the
                product supports them. It does not. Saying what IS supported,
                in the same breath as the question, is what keeps a question
                from reading as an offer. */}
            <p className="wl-ask-q">
              Apex4Traders connects to cTrader today. We are asking so we know
              what to support next — what do you trade on?
            </p>
            <div className="wl-row">
              <select
                className="wl-input"
                aria-label="Trading platform"
                value={platform}
                onChange={(e) => setPlatform(e.target.value)}
              >
                <option value="">Platform…</option>
                <option value="ctrader">cTrader</option>
                <option value="mt5">MetaTrader 5</option>
                <option value="mt4">MetaTrader 4</option>
                <option value="other">Something else</option>
              </select>
              <input
                className="wl-input"
                placeholder="Broker (optional)"
                aria-label="Broker"
                maxLength={60}
                value={broker}
                onChange={(e) => setBroker(e.target.value)}
              />
            </div>
            <div className="wl-row" style={{ marginTop: ".5rem" }}>
              <button
                className="wl-submit"
                type="submit"
                disabled={platform === "" && broker.trim() === ""}
              >
                Send
              </button>
              <button
                className="wl-skip"
                type="button"
                onClick={() => setAsked(true)}
              >
                Skip
              </button>
            </div>
          </form>
        )}
      </div>
    );
  }

  return (
    <form className={className} onSubmit={submit} noValidate>
      <div className="wl-row">
        <label className="sr-only" htmlFor={fieldId}>
          Email address
        </label>
        <input
          id={fieldId}
          ref={inputRef}
          className="wl-input"
          type="email"
          inputMode="email"
          autoComplete="email"
          placeholder="you@example.com"
          value={email}
          aria-describedby={noteId}
          aria-invalid={state.kind === "failed" ? true : undefined}
          onChange={(e) => {
            setEmail(e.target.value);
            if (state.kind === "failed") setState({ kind: "idle" });
          }}
          required
        />
        <button
          className="wl-submit"
          type="submit"
          disabled={state.kind === "sending"}
        >
          {state.kind === "sending" ? (
            <>
              <Loader2 className="ico wl-spin" aria-hidden /> Joining
            </>
          ) : (
            <>
              Get early access <ArrowRight className="ico" aria-hidden />
            </>
          )}
        </button>
      </div>

      {state.kind === "failed" ? (
        /* The server's own words. A friendlier sentence we invented would
           hide which of "that address is wrong" and "we could not reach the
           list" actually happened, and only one of those is the visitor's
           to fix. */
        <p className="wl-error" role="alert">
          <CircleAlert className="ico" aria-hidden /> {state.error.message}
        </p>
      ) : null}

      <p className="wl-note" id={noteId}>
        One email when access opens. No newsletter, no sharing, no tracking.
        Demo accounts only at launch — this release does not place live orders.
      </p>
    </form>
  );
}

export default WaitlistForm;
