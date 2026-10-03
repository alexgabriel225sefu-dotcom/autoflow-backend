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
