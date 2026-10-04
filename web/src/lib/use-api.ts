"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type ApiResult } from "./api";

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

export function useRead<T>(path: string | null, intervalMs = 0) {
  const [result, setResult] = useState<ApiResult<T> | null>(null);
  const [lastSync, setLastSync] = useState<number | null>(null);
  const [loading, setLoading] = useState(!!path);
  const abort = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    if (!path) return;
    abort.current?.abort();
    const ctl = new AbortController();
    abort.current = ctl;
    setLoading(true);
    const r = await api<T>(path, { signal: ctl.signal });
    if (ctl.signal.aborted) return;
    setResult(r);
    setLoading(false);
    // Stamped only on an answer we actually received — including a refusal.
    // Leaving it untouched on failure would show a fresh time over stale data.
    setLastSync(Date.now());
  }, [path]);

  useEffect(() => {
    // Queued rather than called straight from the effect body. `load` sets
    // `loading` before it awaits, and doing that synchronously during commit
    // is a cascading render. One microtask later is invisible to the reader
    // and lets the first paint happen with the initial state.
    queueMicrotask(() => { void load(); });
  }, [load]);

  useEffect(() => {
    if (!path) return;
    const fn = () => { void load(); };
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
    const tick = () => { if (!document.hidden) void load(); };
    const id = window.setInterval(tick, intervalMs);
    document.addEventListener("visibilitychange", tick);
    return () => {
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", tick);
    };
  }, [intervalMs, path, load]);

  return { result, loading, lastSync, reload: load };
}

export function whenSynced(ts: number | null) {
  if (!ts) return "never";
  const secs = Math.round((Date.now() - ts) / 1000);
  if (secs < 5) return "just now";
  if (secs < 90) return `${secs}s ago`;
  return `${Math.round(secs / 60)}m ago`;
}
