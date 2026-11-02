"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type ApiResult } from "./api";

/**
 * One in-flight GET per path.
 *
 * `useRead` used to abort the previous read and start another whenever a poll,
 * a visibility change or a second subscriber asked again. The aborted request
 * had already left the browser, so the candles limiter counted both, and the
 * chart — polling every 15 seconds — answered RATE_LIMITED. A read that is
 * already on the wire is shared. A forced reload still aborts it: that is a
 * newer question, not a duplicate of the one in flight.
 */
type Flight = {
  force: boolean;
  controller: AbortController;
  promise: Promise<ApiResult<unknown>>;
  /** Mounted readers currently bound to this request. */
  readers: number;
};

const flights = new Map<string, Flight>();

/**
 * One cadence per path, shared by every mounted reader.
 *
 * The shell, the dashboard and the trade page each used to keep their own
 * timer for the same fact. A phone sitting on the dashboard then opening
 * Trade step 4 fired both, and a visibility change fired them again. The
 * server answered RATE_LIMITED. A poll that landed inside this gap is the
 * same question the previous reader just asked.
 */
export const MIN_POLL_GAP_MS = 8_000;
const lastAttempt = new Map<string, number>();
const pathPauseUntil = new Map<string, number>();

function pollGap(intervalMs: number): number {
  if (!intervalMs) return MIN_POLL_GAP_MS;
  return Math.max(MIN_POLL_GAP_MS, Math.floor(intervalMs / 2));
}

function beginRead(path: string, force: boolean): Flight {
  const current = flights.get(path);
  // Join only a request somebody is still waiting on. A flight left behind
  // by an unmounted reader is a different question's answer — the next
  // screen has to ask again, or it sits on "loading" forever.
  if (current && !current.controller.signal.aborted && current.readers > 0) {
    if (!force || current.force) return current;
    current.controller.abort();
  }
  const controller = new AbortController();
  const flight: Flight = {
    force,
    controller,
    readers: 0,
    promise: api(path, { signal: controller.signal }).finally(() => {
      if (flights.get(path)?.controller === controller) flights.delete(path);
    }),
  };
  flights.set(path, flight);
  return flight;
}

function releaseFlight(path: string, flight: Flight) {
  flight.readers = Math.max(0, flight.readers - 1);
  if (flight.readers > 0) return;
  if (!flight.controller.signal.aborted) flight.controller.abort();
  if (flights.get(path)?.controller === flight.controller) flights.delete(path);
}

/**
 * A read, with controlled polling.
 *
 * `lastSync` is exposed and shown on screen on purpose. A dashboard that
 * polls silently looks identical whether it refreshed a second ago or died
 * twenty minutes back, and the numbers on it look equally current either way.
 * Saying when they were last confirmed is the difference between data and a
 * screenshot.
 *
 * Polling stops while the tab is hidden: a background tab hammering the
 * broker's rate budget for a screen nobody is looking at helps no one.
 */
/**
 * Every mounted read, by the exact path it reads.
 *
 * WHY THIS EXISTS
 *
 * Two components can read the same endpoint, and they did: the dashboard
 * polled `automation` on its own clock and so did the app shell, for the
 * status strip. Pressing Start reloaded the dashboard's copy and left the
 * shell's alone, so the strip at the top of every screen said
 * "Automation STOPPED" for up to thirty seconds after a trading loop had
 * started. Measured in a browser: server `running`, panel "Watching market",
 * strip "STOPPED", all at once.
 *
 * That is worse than a stale number. The strip is the only automation
 * indicator on the rule page, and its own contract is that it never claims a
 * state it does not have. A control has to invalidate the ENDPOINT, not the
 * caller's private copy of it.
 *
 * Keyed on the exact path, deliberately. Prefix matching would quietly
 * reload reads the caller did not mean, and the caller naming each path it
 * has invalidated is the part a reviewer can check.
 */
const subscribers = new Map<string, Set<() => void>>();

export function invalidate(...paths: string[]) {
  for (const p of paths) {
    const subs = subscribers.get(p);
    if (subs) for (const fn of [...subs]) fn();
  }
}

// The shell reads `accounts` while pages read `ctrader/status` (same payload).
// Reloading one leaves the status strip on the account the client just left.
// positions/orders have no account id in the path, so they keep the previous
// account until polled.
export const BROKER_VIEW_PATHS = ["ctrader/status", "accounts", "me", "positions", "orders", "automation"] as const;

export function invalidateBrokerViews() {
  invalidate(...BROKER_VIEW_PATHS);
}

/** Test hook. The gap and the 429 pause are process-wide, so a test that
 *  advances time must not leave that wait for the next file. */
export function resetReadSchedule() {
  lastAttempt.clear();
  pathPauseUntil.clear();
}

export function useRead<T>(path: string | null, intervalMs = 0) {
  const [result, setResult] = useState<ApiResult<T> | null>(null);
  const [lastSync, setLastSync] = useState<number | null>(null);
  const [loading, setLoading] = useState(!!path);
  const seq = useRef(0);
  /** Automatic polls wait out a RATE_LIMITED answer. A forced reload does not. */
  const pauseUntil = useRef(0);
  /** The request this mounted reader is waiting on, so unmount can drop it. */
  const held = useRef<Flight | null>(null);

  const load = useCallback(async (force = false, kind: "mount" | "poll" | "visible" | "online" = "mount"): Promise<ApiResult<T> | undefined> => {
    if (!path) return undefined;
    // The server said how long to wait. Polling again before that spends the
    // budget the refusal just told us is empty. The pause is per path, so a
    // second reader of the same endpoint waits out the same refusal.
    const sharedPause = pathPauseUntil.get(path) ?? 0;
    if (!force && (Date.now() < pauseUntil.current || Date.now() < sharedPause)) return undefined;
    if (!force && (kind === "poll" || kind === "visible")) {
      const last = lastAttempt.get(path) ?? 0;
      const gap = kind === "visible" ? Math.max(pollGap(intervalMs), 12_000) : pollGap(intervalMs);
      if (Date.now() - last < gap) return undefined;
    }
    lastAttempt.set(path, Date.now());
    const mine = ++seq.current;
    setLoading(true);
    const flight = beginRead(path, force);
    if (held.current !== flight) {
      const previous = held.current;
      held.current = flight;
      flight.readers += 1;
      if (previous) releaseFlight(path, previous);
    }
    const r = (await flight.promise) as ApiResult<T>;
    // A superseded read resolves to undefined: a newer one is on its way and
    // is the one whose answer counts. An aborted flight is the same thing —
    // its answer, if it arrives, belongs to a request we gave up on.
    if (mine !== seq.current || flight.controller.signal.aborted) return undefined;
    setResult(r);
    setLoading(false);
    if (!r.ok && r.code === "RATE_LIMITED"
        && typeof r.retryAfterSec === "number" && r.retryAfterSec > 0) {
      const until = Date.now() + r.retryAfterSec * 1000;
      pauseUntil.current = until;
      const prev = pathPauseUntil.get(path) ?? 0;
      pathPauseUntil.set(path, Math.max(prev, until));
    } else if (r.ok) {
      pauseUntil.current = 0;
    }
    // Stamped only on an answer we actually received — including a refusal.
    // Leaving it untouched on failure would show a fresh time over stale data.
    setLastSync(Date.now());
    // Returned so a caller that has just changed something can check the
    // answer it gets back against what it expected, instead of trusting the
    // screen to have caught up.
    return r;
  }, [path, intervalMs]);

  useEffect(() => {
    // Queued rather than called straight from the effect body. `load` sets
    // `loading` before it awaits, and doing that synchronously during commit
    // is a cascading render. One microtask later is invisible to the reader
    // and lets the first paint happen with the initial state.
    //
    // The flag is the other half. Strict-mode remount and a test that
    // unmounts before the microtask runs would otherwise start a read nobody
    // is mounted to, and the next reader would join that abandoned request.
    let alive = true;
    queueMicrotask(() => { if (alive) void load(); });
    return () => { alive = false; };
  }, [load]);

  useEffect(() => {
    return () => {
      const flight = held.current;
      held.current = null;
      if (path && flight) releaseFlight(path, flight);
    };
  }, [path]);

  useEffect(() => {
    if (!path) return;
    const fn = () => { void load(true); };
    const subs = subscribers.get(path) ?? new Set<() => void>();
    subs.add(fn);
    subscribers.set(path, subs);
    return () => {
      subs.delete(fn);
      // Dropped when empty, so a long session does not accumulate a key per
      // path it has ever read.
      if (subs.size === 0) subscribers.delete(path);
    };
  }, [path, load]);

  useEffect(() => {
    if (!intervalMs || !path) return;
    const tick = () => { if (!document.hidden) void load(false, "poll"); };
    const onVisible = () => { if (!document.hidden) void load(false, "visible"); };
    const id = window.setInterval(tick, intervalMs);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [intervalMs, path, load]);

  // RECOVER WHEN THE NETWORK COMES BACK, which nothing did.
  //
  // Seen on a phone during the first walk-through: the device moved from
  // WiFi to 5G, the in-flight reads failed, and the status bar fell to
  // "Account Unknown / Automation Unknown". Showing "unknown" rather than
  // repeating stale data is right — the UI must not claim a demo account it
  // could not verify — but nothing then tried again. The client had to know
  // to reload the page, and a client who does not know that reads a working
  // product as a broken one.
  //
  // Deliberately OUTSIDE the interval effect above: a hook created without
  // `intervalMs` returns early there and so never retried at all, which is
  // the case the status bar is. Recovery must not depend on polling.
  useEffect(() => {
    if (!path) return;
    const onBack = () => { void load(false, "online"); };
    window.addEventListener("online", onBack);
    return () => window.removeEventListener("online", onBack);
  }, [path, load]);

  return { result, loading, lastSync, reload: () => load(true) };
}

export function whenSynced(ts: number | null) {
  if (!ts) return "never";
  const secs = Math.round((Date.now() - ts) / 1000);
  if (secs < 5) return "just now";
  if (secs < 90) return `${secs}s ago`;
  return `${Math.round(secs / 60)}m ago`;
}
