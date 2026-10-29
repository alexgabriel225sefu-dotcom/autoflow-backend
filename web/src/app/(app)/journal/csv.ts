import type { JournalEntry } from "@/lib/api";

const HEADER = [
  "time_utc", "symbol", "status", "verdict", "reason", "refusal_code",
  "error", "entry_price", "confidence", "rule_id", "account_id", "entry_id",
] as const;

/**
 * One CSV cell.
 *
 * Quoted when it holds a comma, quote or newline. A cell that begins with =,
 * +, - or @ is prefixed with an apostrophe: spreadsheets execute those as
 * formulas, and a rule's reason text is partly user-supplied.
 */
export function csvCell(value: unknown): string {
  if (value === null || value === undefined) return "";
  let s = String(value);
  if (/^[=+\-@\t\r]/.test(s) && !/^-?\d+(\.\d+)?$/.test(s)) s = `'${s}`;
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

/** The rows already on screen, as CSV text. No request is made for this. */
export function journalToCsv(entries: JournalEntry[]): string {
  const rows = entries.map((e) => [
    Number.isFinite(e.ts) ? new Date(e.ts * 1000).toISOString() : "",
    e.symbol, e.status ?? e.kind, e.decision?.verdict,
    e.decision?.reason, e.decision?.refusalCode, e.error,
    typeof e.snapshot?.price === "number" ? e.snapshot.price : "",
    typeof e.decision?.confidence === "number" ? e.decision.confidence : "",
    e.ruleDocId, e.accountId, e.entryId,
  ].map(csvCell).join(","));
  return [HEADER.join(","), ...rows].join("\r\n") + "\r\n";
}

/** Save text as a file. Browser-only. */
export function downloadText(filename: string, text: string, type = "text/csv;charset=utf-8") {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
