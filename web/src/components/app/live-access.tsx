/**
 * How a screen talks about the live gate.
 *
 * The server sends the verdict. This file only refuses to repeat a sentence
 * that says live is available when that verdict is closed or missing.
 */
import type { Execution, LiveGateVerdict } from "@/lib/api";

const FALLBACK = "Live trading is not available in this release.";

export function claimsLiveAvailable(text: string | null | undefined): boolean {
  return /live trading is (available|enabled|supported|on)\b/i.test(text || "")
    || /live automation is available/i.test(text || "");
}

export function liveCleared(execution: Execution | null | undefined): boolean {
  return execution?.accountMode === "live"
    && execution.canAutomate === true
    && execution.liveGate?.open === true;
}

export function liveNotice(execution: Execution | null | undefined): {
  lead: string;
  details: string[];
} {
  const gate: LiveGateVerdict | undefined = execution?.liveGate;
  if (liveCleared(execution)) {
    const lead = execution?.message && !claimsLiveAvailable(execution.message)
      ? execution.message
      : "The server has cleared this account. A live order is still sent only when the order gate allows it.";
    return { lead, details: [] };
  }
  if (gate && gate.open !== true) {
    const raw = gate.status === "unknown"
      ? (gate.summary || "Unknown — treated as unavailable")
      : (gate.summary || FALLBACK);
    return {
      lead: claimsLiveAvailable(raw) ? FALLBACK : raw,
      details: (gate.missing ?? []).map((item) => item.detail).filter(Boolean),
    };
  }
  if (execution?.accountMode === "live"
      && execution.message
      && !claimsLiveAvailable(execution.message)) {
    return { lead: execution.message, details: [] };
  }
  return { lead: FALLBACK, details: [] };
}

export function requestSentence(gate: LiveGateVerdict | null | undefined): string {
  const status = gate?.request?.status || "none";
  if (status === "pending") {
    return "Your request is waiting for an operator. It does not connect a broker account.";
  }
  if (status === "approved") {
    return "An operator approved the request. A live order is still sent only when every other condition is met.";
  }
  if (status === "rejected") {
    const reason = (gate?.request?.reason || "").trim();
    const safe = reason && !claimsLiveAvailable(reason) ? reason : "";
    return safe
      ? `An operator declined the request: ${safe} You can send another request.`
      : "An operator declined the request. You can send another request.";
  }
  if (status === "unknown") {
    return "The request could not be read, so it is treated as not approved.";
  }
  return "You have not requested a live account connection.";
}

export function LiveAccessPanel({
  gate,
}: {
  gate: LiveGateVerdict | null | undefined;
}) {
  if (!gate) {
    return (
      <div className="notice notice-warn" role="status">
        <p>{FALLBACK}</p>
        <p className="muted">The live gate has not been read yet.</p>
      </div>
    );
  }
  const lead = gate.open === true
    ? (claimsLiveAvailable(gate.summary)
      ? "All checked conditions are met. A live order is still sent only when the order gate allows it."
      : gate.summary)
    : (claimsLiveAvailable(gate.summary) ? FALLBACK : (gate.summary || FALLBACK));
  const rows = gate.open === true ? gate.conditions : gate.missing;
  return (
    <div className={gate.open === true ? "notice notice-accent" : "notice notice-warn"} role="status">
      <p>{lead}</p>
      {rows?.length ? (
        <ul>
          {rows.map((item) => (
            <li key={item.code}>{item.detail}</li>
          ))}
        </ul>
      ) : null}
      {gate.checkoutOpen === true ? null : (
        <p>Live purchase is not yet open.</p>
      )}
    </div>
  );
}
