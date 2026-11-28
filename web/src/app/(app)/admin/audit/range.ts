/**
 * The window the audit page asks for.
 *
 * The API's own default is seven days when `from` and `to` are omitted. This
 * page always sends both, in Europe/Amsterdam, so the table and the request
 * are the same range — fourteen days unless the operator picks another.
 */

export const DEFAULT_AUDIT_DAYS = 14;
export const AUDIT_DAY_CHOICES = [7, 14, 30, 90] as const;

const DAY_MS = 86_400_000;

/** ISO-8601 with the Amsterdam offset, so the server does not guess a zone. */
export function amsterdamIso(ms: number): string {
  const date = new Date(ms);
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Europe/Amsterdam",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).formatToParts(date);
  const pick = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  const year = pick("year");
  const month = pick("month");
  const day = pick("day");
  const hour = pick("hour");
  const minute = pick("minute");
  const second = pick("second");
  const asUtc = Date.UTC(+year, +month - 1, +day, +hour, +minute, +second);
  const offsetMin = Math.round((asUtc - date.getTime()) / 60_000);
  const sign = offsetMin >= 0 ? "+" : "-";
  const abs = Math.abs(offsetMin);
  const hh = String(Math.floor(abs / 60)).padStart(2, "0");
  const mm = String(abs % 60).padStart(2, "0");
  return `${year}-${month}-${day}T${hour}:${minute}:${second}${sign}${hh}:${mm}`;
}

export function auditWindow(days: number, now = Date.now()): { from: string; to: string } {
  return {
    from: amsterdamIso(now - days * DAY_MS),
    to: amsterdamIso(now),
  };
}

/** The four GETs for one account. The list itself is a separate call. */
export function auditDetailPaths(ctid: string | number, days: number, now = Date.now()) {
  const id = encodeURIComponent(String(ctid));
  const { from, to } = auditWindow(days, now);
  const q = new URLSearchParams({ from, to }).toString();
  const base = `admin/audit/accounts/${id}`;
  return {
    summary: base,
    open: `${base}/open`,
    deals: `${base}/deals?${q}`,
    orders: `${base}/orders?${q}`,
  };
}
