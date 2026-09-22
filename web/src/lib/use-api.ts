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

  useEffect(() => { void load(); }, [load]);

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
