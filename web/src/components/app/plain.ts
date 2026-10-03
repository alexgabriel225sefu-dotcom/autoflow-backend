/**
 * Engine vocabulary, translated into what a trader would say.
 *
 * The engine's words are exact and they stay exact where exactness is the
 * point — inside rule details, in the journal's filter, in a refusal code.
 * But a dashboard that leads with `STOPPED`, `HOLD` and `price_vs_ma` asks
 * the reader to learn the implementation before they can answer "is it
 * running and did it buy anything".
 *
 * This file is a presentation layer and nothing else. It never decides
 * anything, it never invents a state the backend did not report, and every
 * unmapped value falls through to the original string rather than to a
 * friendly guess — a state we have not thought about must look unfamiliar,
 * not look fine.
 */

export type Tone = "long" | "short" | "neutral" | "accent";

export type Plain = {
  /** What to show as the headline. */
  label: string;
  /** One sentence of context, when there is one worth adding. */
  detail?: string;
  tone: Tone;
};

/* ── automation ───────────────────────────────────────────────────────── */

export function plainAutomation(
  state: string | null | undefined,
  hasRule: boolean,
): Plain {
  switch (state) {
    case "running":
      return {
        label: "Watching market",
        detail: "The rule is being evaluated on each new bar.",
        tone: "long",
      };
    case "paused":
      return {
        label: "Automation paused",
        detail: "Nothing will be placed until you resume it.",
        tone: "neutral",
      };
    case "stopped":
      return {
        label: "Not running",
        detail: hasRule
          ? "Start it when you want the rule watched."
          : "Activate a rule first, then start it.",
        tone: "neutral",
      };
    default:
      // Unknown, because the read has not come back — not "stopped".
      return { label: state ? String(state) : "Unknown", tone: "neutral" };
  }
}

/* ── one journal entry ────────────────────────────────────────────────── */

/**
 * The verdict is preferred over the status where both exist, because the
 * verdict is what the rule decided and the status is how it was recorded.
 */
export function plainDecision(e: {
  status?: string | null;
  kind?: string;
  decision?: { verdict?: string; refusalCode?: string | null } | null;
  error?: string | null;
}): Plain {
  const v = e.decision?.verdict;
  if (v === "BUY") return { label: "Buy signal", detail: "Conditions met.", tone: "long" };
  if (v === "SELL") return { label: "Sell signal", detail: "Conditions met.", tone: "short" };
  if (v === "CLOSE") return { label: "Close signal", tone: "accent" };

  switch (e.status) {
    case "hold":
      return { label: "Conditions not met", detail: "No order placed.", tone: "neutral" };
    case "reject":
      return {
        label: "Could not run",
        detail: e.decision?.refusalCode
          ? `No order placed — ${e.decision.refusalCode}.`
          : "No order placed.",
        tone: "short",
      };
    case "evaluated":
      return { label: "Market checked", detail: "No order placed.", tone: "neutral" };
    case "execution_requested":
      return { label: "Order requested", tone: "accent" };
    case "order_sent":
      return { label: "Order sent to broker", tone: "accent" };
    case "order_confirmed":
      return { label: "Order placed in demo", tone: "long" };
    case "order_rejected":
      return { label: "Broker rejected the order", detail: e.error ?? undefined, tone: "short" };
    case "position_closed":
      return { label: "Position closed", tone: "accent" };
    case "broker_error":
      return { label: "Broker error", detail: e.error ?? undefined, tone: "short" };
    case "automation_started":
      return { label: "Automation started", tone: "long" };
    case "automation_paused":
      return { label: "Automation paused", tone: "neutral" };
    case "automation_stopped":
      return { label: "Automation stopped", tone: "neutral" };
    default:
      // Deliberately unfriendly: an unmapped status should look unfamiliar.
      return { label: e.status ?? e.kind ?? "Recorded", tone: "neutral" };
  }
}

/* ── a broker read ────────────────────────────────────────────────────── */

/**
 * `status` from the `{connected, status}` contract.
 *
 * "ok" is not translated here: an ok read has data, and the data is the
 * message. Everything else is a reason the screen has nothing to show, and
 * those must never be collapsed into an empty list.
 */
export function plainRead(status: string, reason?: string): Plain | null {
  switch (status) {
    case "ok":
      return null;
    case "not_connected":
      return {
        label: "cTrader account not connected",
        detail: "Connect an account to see this.",
        tone: "neutral",
      };
    case "reauth_required":
      return {
        label: "cTrader needs reconnecting",
        detail: reason ?? "The authorisation has expired.",
        tone: "short",
      };
    case "unavailable":
      return {
        label: "Market data unavailable",
        detail: reason ?? "The broker did not answer.",
        tone: "short",
      };
    default:
      return { label: status, detail: reason, tone: "short" };
  }
}

/* ── licence ──────────────────────────────────────────────────────────── */

export function plainLicence(state: string | null | undefined): Plain {
  switch (state) {
    case "active":
      return { label: "Active", tone: "long" };
    case "expired":
      return { label: "Expired", detail: "Rules cannot be activated until it is renewed.", tone: "short" };
    case "revoked":
      return { label: "Withdrawn", tone: "short" };
    case "none":
      return { label: "No licence", detail: "Rules can be built and previewed, but not activated.", tone: "neutral" };
    default:
      return { label: "Unknown", tone: "neutral" };
  }
}

/** The CSS class for a tone. Kept here so the mapping lives in one file. */
export function toneClass(tone: Tone): string {
  return tone === "long" ? "side-long"
    : tone === "short" ? "side-short"
    : tone === "accent" ? "verdict-close"
    : "muted";
}

export function tonePill(tone: Tone): string {
  return tone === "long" ? "pill pill-ok"
    : tone === "short" ? "pill pill-warn"
    : tone === "accent" ? "pill pill-accent"
    : "pill pill-muted";
}
