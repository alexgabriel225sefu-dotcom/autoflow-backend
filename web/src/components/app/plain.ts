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

/**
 * WHO ACTS ON A SETUP. The three levels the server services, in the words the
 * Telegram bot used, with what each one does and does NOT do. The `id` is the
 * engine's own and is what the rule stores; an unknown id falls through to
 * itself (see `plainLevel`) instead of being shown as a friendly guess.
 */
export const AUTOMATION_LEVELS = [
  {
    id: "signals", label: "Signals Only",
    does: "Tells you when your rule finds a setup.",
    doesNot: "Places nothing.",
  },
  {
    id: "approval", label: "Approval Required",
    does: "Proposes each trade and waits for you to approve it.",
    doesNot: "Places nothing until you approve.",
  },
  {
    id: "full", label: "Full Automation",
    does: "Places the trade itself when your rule fires.",
    doesNot: "Does not ask.",
  },
] as const;

export function plainLevel(id: unknown): string {
  const hit = AUTOMATION_LEVELS.find((l) => l.id === id);
  return hit ? hit.label : String(id ?? "—");
}

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

/** The sentence the engine's refusal to start a loop was recorded under. */
const LEGACY_ENGINE_REFUSAL = "the engine refused to start this loop";

function isLegacyEngineRefusal(error: string | null | undefined): boolean {
  return typeof error === "string"
    && error.trim().toLowerCase().startsWith(LEGACY_ENGINE_REFUSAL);
}

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
      // Entries written before engine errors had their own status. A handover
      // refusal ("the engine refused to start this loop") was filed here as a
      // broker error although the provider was never asked — the journal is
      // append-only evidence, so the stored status is left alone and only the
      // WORDS are corrected. Matched on the engine's own opening sentence and
      // nothing looser: a real provider failure must keep its label.
      if (isLegacyEngineRefusal(e.error)) {
        return { label: "Engine error", detail: e.error ?? undefined, tone: "short" };
      }
      return { label: "Broker error", detail: e.error ?? undefined, tone: "short" };
    // The engine or the platform failed and the broker rejected nothing. Its
    // own label: calling it a broker error sends the reader to look for a
    // fault at a provider that did nothing wrong.
    case "engine_error":
      return { label: "Engine error", detail: e.error ?? undefined, tone: "short" };
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
      /* THIS STATUS COVERS TWO SITUATIONS AND THE LABEL CLAIMED ONE.
         `broker_read` answers "no cTrader account is connected, OR NONE HAS
         BEEN SELECTED" — one status for both, because from the reader's
         point of view there is simply no account to read from. The label
         said "cTrader account not connected", which is false in the second
         case, and every panel that drew it also offered /connect.
         So an owner who had linked cTrader and not yet picked an account was
         told on three separate screens that he had not connected, each time
         with the status strip directly above reading "cTrader Linked", and
         each time invited to authorise again. Reported from a phone on
         2026-10-04; the extra authorisation round is what produced
         RATE_LIMITED.
         "No account selected" is true in BOTH cases — nothing is selected
         when nothing is linked either — and the server's own sentence,
         carried here like every sibling branch already carries it, says
         which of the two it is. The action belongs at /accounts, which is
         right either way: it lists the accounts when there is a link, and
         says there is none and offers to connect when there is not. */
      return {
        label: "No account selected",
        detail: reason ?? "Choose a cTrader account to see this.",
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

/* ── the outcome of a control ─────────────────────────────────────────── */

/**
 * What to tell the client after Start, Pause, Resume or Stop.
 *
 * WHY THIS EXISTS RATHER THAN `Automation is now ${state}`
 *
 * Both control sites said exactly that, and for Stop it was the most
 * expensive sentence in the product. The server's stop answer carries
 * `flattened: false`, `flattenDeclined: true` and a sentence explaining that
 * open positions stay at the broker with the stop and target they were
 * given — §8.1 of the live-execution specification requires a stop to
 * flatten or explicitly decline and SAY WHICH. The browser dropped all three
 * fields and reported "stopped".
 *
 * So a client with a losing position pressed Stop, read "stopped",
 * reasonably understood "and I am flat", and closed the tab. The position
 * was still open. The only place the truth appeared was a notification on a
 * page they were never sent to.
 *
 * The explanation is the SERVER's sentence, verbatim. What a stop does to
 * real exposure is not something to keep a second copy of in a browser,
 * where it would be free to drift from what actually happened.
 */
export function outcomeOf(a: {
  state: string;
  flattened?: boolean;
  flattenDeclined?: boolean;
  flattenReason?: string | null;
  /** Present when the stop was recorded but no loop was stopped in the process
   *  that took the request. Shown verbatim: it is the server's caution. */
  stopNote?: string | null;
}): string {
  const base = `Automation is now ${a.state}`;
  // Only when the server actually declined. A release that later closes
  // positions will send `flattened: true`, and this must then say nothing
  // extra rather than keep repeating a warning that has stopped being true.
  const flat = a.flattenDeclined && a.flattenReason ? `${base}. ${a.flattenReason}` : base;
  return a.stopNote ? `${flat} ${a.stopNote}` : flat;
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
