import { useMemo, useSyncExternalStore } from "react";

/**
 * Which optional dashboard cards the viewer has hidden.
 *
 * A per-viewer convenience kept in this browser only. It can come back empty
 * (private window, cleared data, blocked storage) and then every card shows,
 * which is the default. Cards that carry a deadline or a safety control are
 * not in this list and cannot be hidden: the approval, and the automation card
 * with its stop controls.
 */
export const WIDGETS = [
  { id: "market", label: "Market chart" },
  { id: "why", label: "Why isn't it trading?" },
  { id: "decisions", label: "What the rule decided" },
  { id: "rule", label: "Active rule" },
  { id: "positions", label: "Open positions" },
  { id: "orders", label: "Pending orders" },
] as const;

export type WidgetId = (typeof WIDGETS)[number]["id"];
export const STORAGE_KEY = "a4t.dashboard.hidden.v1";

const KNOWN = new Set<string>(WIDGETS.map((w) => w.id));

/** Parse whatever was stored; anything unreadable or unknown is dropped. */
export function parseHidden(raw: string | null): Set<WidgetId> {
  if (!raw) return new Set();
  try {
    const v: unknown = JSON.parse(raw);
    if (!Array.isArray(v)) return new Set();
    return new Set(v.filter((x): x is WidgetId => typeof x === "string" && KNOWN.has(x)));
  } catch {
    return new Set();
  }
}

export function toggle(hidden: ReadonlySet<WidgetId>, id: WidgetId): Set<WidgetId> {
  const next = new Set(hidden);
  if (next.has(id)) next.delete(id); else next.add(id);
  return next;
}

const EVENT = "a4t-dashboard-layout";

function rawStored(): string {
  try { return window.localStorage.getItem(STORAGE_KEY) ?? ""; } catch { return ""; }
}
function subscribe(cb: () => void) {
  window.addEventListener("storage", cb);
  window.addEventListener(EVENT, cb);
  return () => { window.removeEventListener("storage", cb); window.removeEventListener(EVENT, cb); };
}

/** The hidden set, read from this browser. The server render sees nothing
 *  hidden, so a viewer who hid a card briefly sees it on first paint. */
export function useHiddenWidgets(): Set<WidgetId> {
  const raw = useSyncExternalStore(subscribe, rawStored, () => "");
  return useMemo(() => parseHidden(raw || null), [raw]);
}

export function writeHidden(hidden: ReadonlySet<WidgetId>): void {
  try {
    if (hidden.size === 0) window.localStorage.removeItem(STORAGE_KEY);
    else window.localStorage.setItem(STORAGE_KEY, JSON.stringify([...hidden]));
  } catch { /* storage unavailable: nothing is saved, every card stays shown */ }
  window.dispatchEvent(new Event(EVENT));
}
