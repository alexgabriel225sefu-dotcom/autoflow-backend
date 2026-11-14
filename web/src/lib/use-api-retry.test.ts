/**
 * `useRead` — what a 429 must turn into.
 *
 * WHY THIS FILE EXISTS
 *
 * Seen in production: a client walking through the app got
 * `429 GET /api/v1/trades?days=30&mode=demo`, and the page showed nothing
 * useful. The refusal carried `retryAfterSec`, and nothing acted on it: a read
 * that polls waited for its own interval, and a read that does not poll never
 * asked again at all. The reader was left to find the reload button.
 *
 * The server's cause is fixed separately. This pins the client's half, in the
 * one place every page reads through: a refused read says when it will ask
 * again (`retryAt`, which `ErrorNotice` renders as "Busy, retrying in N s"),
 * and asks again ONCE when that moment arrives. Once, because a second refusal
 * means the wait the server named was not enough, and a loop of automatic
 * retries is how a rate limit gets spent the moment it reopens.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { RETRY_PAD_MS, resetReadSchedule, useRead } from "./use-api";
import * as apiModule from "./api";

const refusal = (retryAfterSec?: number) => ({
  ok: false, status: 429, code: "RATE_LIMITED",
  message: "too many requests — wait 12s and try again",
  ...(retryAfterSec === undefined ? {} : { retryAfterSec }),
});

/** Answers from `answers` in order; the last one repeats. */
function serve(answers: unknown[]) {
  const calls: string[] = [];
  vi.spyOn(apiModule, "api").mockImplementation(async (path) => {
    calls.push(String(path));
    return answers[Math.min(calls.length, answers.length) - 1] as never;
  });
  return calls;
}

const settle = () => act(async () => { await vi.advanceTimersByTimeAsync(0); });
/** The wait the refusals below name, plus the pad the retry adds to it. */
const AFTER_WAIT = 12_000 + RETRY_PAD_MS;
const wait = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });

beforeEach(() => {
  vi.restoreAllMocks();
  vi.useFakeTimers();
});

afterEach(() => {
  resetReadSchedule();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("a refused read retries once, after the wait the server named", () => {
  it("publishes when it will retry, waits that long, then shows the answer", async () => {
    const calls = serve([refusal(12), { ok: true, data: { trades: [] } }]);
    const started = Date.now();
    // No interval: the case that used to stay refused until a manual reload.
    const { result } = renderHook(() => useRead<{ trades: unknown[] }>("rules"));
    await settle();

    expect(calls).toEqual(["rules"]);
    const first = result.current.result;
    if (first?.ok !== false) throw new Error("expected a refusal");
    expect(first.code).toBe("RATE_LIMITED");
    expect(first.retryAt, "the page cannot count down without the moment").toBe(started + 12_000);

    await wait(12_000);
    expect(calls, "asked again before the stated wait was over").toHaveLength(1);

    await wait(RETRY_PAD_MS);
    expect(calls).toEqual(["rules", "rules"]);
    expect(result.current.result).toEqual({ ok: true, data: { trades: [] } });
  });

  it("does not retry a second time when the retry is refused too", async () => {
    const calls = serve([refusal(12), refusal(12)]);
    const { result } = renderHook(() => useRead("rules"));
    await settle();
    await wait(AFTER_WAIT);
    expect(calls).toHaveLength(2);

    const second = result.current.result;
    if (second?.ok !== false) throw new Error("expected a refusal");
    expect(second.retryAt, "a countdown to a retry that will not happen").toBeUndefined();

    await wait(120_000);
    expect(calls, "an automatic retry loop").toHaveLength(2);
  });

  it("gives a manual reload its own single retry", async () => {
    const calls = serve([refusal(12), refusal(12), refusal(12), { ok: true, data: {} }]);
    const { result } = renderHook(() => useRead("rules"));
    await settle();
    await wait(AFTER_WAIT);
    expect(calls).toHaveLength(2);

    await act(async () => {
      void result.current.reload();
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(calls).toHaveLength(3);
    const third = result.current.result;
    if (third?.ok !== false) throw new Error("expected a refusal");
    expect(typeof third.retryAt).toBe("number");

    await wait(AFTER_WAIT);
    expect(calls).toHaveLength(4);
    expect(result.current.result?.ok).toBe(true);
  });

  it("does not ask again for a screen the reader has left", async () => {
    const calls = serve([refusal(12), { ok: true, data: {} }]);
    const { unmount } = renderHook(() => useRead("rules"));
    await settle();
    expect(calls).toHaveLength(1);

    unmount();
    await wait(60_000);
    expect(calls, "a retry for an unmounted reader").toHaveLength(1);
  });

  it("promises no retry when the server named no wait", async () => {
    const calls = serve([refusal()]);
    const { result } = renderHook(() => useRead("rules"));
    await settle();
    const first = result.current.result;
    if (first?.ok !== false) throw new Error("expected a refusal");
    expect(first.retryAt).toBeUndefined();
    await wait(120_000);
    expect(calls).toHaveLength(1);
  });

  it("does not retry other failures", async () => {
    const calls = serve([{ ok: false, status: 503, code: "STORE_UNAVAILABLE", message: "down" }]);
    renderHook(() => useRead("rules"));
    await settle();
    await wait(120_000);
    expect(calls).toHaveLength(1);
  });

  it("two readers of one path share the retry instead of doubling it", async () => {
    // The retry stays on the wire for a moment, as a real request does: both
    // readers' timers fire together and the second joins the first's request.
    let answer!: (v: unknown) => void;
    const onTheWire = new Promise((resolve) => { answer = resolve; });
    const calls = serve([refusal(12), onTheWire]);
    const a = renderHook(() => useRead("rules"));
    const b = renderHook(() => useRead("rules"));
    await settle();
    expect(calls).toHaveLength(1);
    await wait(AFTER_WAIT);
    expect(calls).toHaveLength(2);
    await act(async () => { answer({ ok: true, data: {} }); await vi.advanceTimersByTimeAsync(0); });
    expect(calls).toHaveLength(2);
    expect(a.result.current.result?.ok).toBe(true);
    expect(b.result.current.result?.ok).toBe(true);
  });

  it("a polling read retries at the stated moment, not a whole interval later", async () => {
    // The /trades case: it polls once a minute, so a refusal with a 12 second
    // wait used to leave the page refused for the rest of that minute.
    const calls = serve([refusal(12), { ok: true, data: { status: "ok" } }]);
    const { result } = renderHook(() => useRead("trades?days=30&mode=demo", 60_000));
    await settle();
    expect(calls).toHaveLength(1);
    await wait(AFTER_WAIT);
    expect(calls).toHaveLength(2);
    expect(result.current.result?.ok).toBe(true);
    // And the poll that follows does not double up on the retry.
    await wait(48_000);
    expect(calls.length).toBeLessThanOrEqual(3);
  });
});
