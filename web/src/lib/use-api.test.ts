/**
 * `useRead` — what a cancelled read must NOT do.
 *
 * WHY THIS FILE EXISTS
 *
 * A real browser pass showed a dozen `ERR_ABORTED` entries in the console when
 * the middleware redirects a signed-in visitor away from /signup: the previous
 * page's polling reads were in flight and the browser tore them down. That is
 * ordinary navigation behaviour, not a defect.
 *
 * But it raises the question that matters for this product: does a cancelled
 * read render as a failure? If it did, a client navigating quickly would see
 * "we could not reach your broker" flash on screen — a false alarm about their
 * money, produced by nothing worse than clicking a link. `useRead` already
 * returns before setting any state when the signal aborted, and nothing was
 * pinning that.
 *
 * The opposite mistake is just as bad and is the easy way to "fix" aborts:
 * swallow every error, and a genuine broker outage renders as an empty list.
 * So both directions are asserted here.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { invalidate, invalidateBrokerViews, useRead, whenSynced } from "./use-api";
import * as apiModule from "./api";

/** A pending call whose result the test decides, later. */
function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => { resolve = r; });
  return { promise, resolve };
}

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("a cancelled read is not a failure", () => {
  it("sets no result when the signal aborted before the answer arrived", async () => {
    const d = deferred<apiModule.ApiResult<{ v: number }>>();
    let captured: AbortSignal | undefined;

    vi.spyOn(apiModule, "api").mockImplementation((_path, opts) => {
      captured = (opts as { signal?: AbortSignal } | undefined)?.signal;
      return d.promise as never;
    });

    const { result, unmount } = renderHook(() => useRead<{ v: number }>("positions"));
    await waitFor(() => expect(captured).toBeDefined());

    // Navigating away aborts the in-flight read, and only then does the
    // request settle — which is the exact ordering the browser produced.
    unmount();
    await act(async () => {
      d.resolve({ ok: false, status: 0, code: "NETWORK", message: "aborted" });
      await Promise.resolve();
    });

    // No error state was ever published, so no screen could render one.
    expect(result.current.result).toBeNull();
  });

  it("a superseded read does not stamp lastSync when it finally settles", async () => {
    // Each call gets its OWN pending promise: the first is the one that gets
    // aborted, the second stays in flight. Sharing one promise would let the
    // second call resolve too, and it would stamp lastSync legitimately —
    // which is what the first version of this test actually measured.
    const pending: Array<{ resolve: (v: unknown) => void }> = [];
    const signals: AbortSignal[] = [];

    vi.spyOn(apiModule, "api").mockImplementation((_path, opts) => {
      const s = (opts as { signal?: AbortSignal } | undefined)?.signal;
      if (s) signals.push(s);
      const d = deferred<unknown>();
      pending.push({ resolve: d.resolve });
      return d.promise as never;
    });

    const { result } = renderHook(() => useRead<{ v: number }>("positions"));
    await waitFor(() => expect(signals.length).toBe(1));

    // A second load supersedes the first and aborts its signal.
    await act(async () => { void result.current.reload(); await Promise.resolve(); });
    await waitFor(() => expect(signals.length).toBe(2));
    expect(signals[0].aborted).toBe(true);
    expect(signals[1].aborted).toBe(false);

    // The ABORTED one settles. It must publish nothing: not a result, and not
    // a sync time that would show fresh over data nobody confirmed.
    await act(async () => {
      pending[0].resolve({ ok: true, data: { v: 1 } });
      await Promise.resolve();
    });
    expect(result.current.result).toBeNull();
    expect(result.current.lastSync).toBeNull();

    // And the read that is still in flight can still answer normally.
    await act(async () => {
      pending[1].resolve({ ok: true, data: { v: 2 } });
      await Promise.resolve();
    });
    await waitFor(() => expect(result.current.result).not.toBeNull());
    expect(result.current.lastSync).not.toBeNull();
  });
});

describe("a genuine failure is still a failure", () => {
  it("a network error is published, not swallowed", async () => {
    vi.spyOn(apiModule, "api").mockResolvedValue({
      ok: false, status: 0, code: "NETWORK", message: "Network error",
    } as never);

    const { result } = renderHook(() => useRead<{ v: number }>("positions"));
    await waitFor(() => expect(result.current.result).not.toBeNull());
    expect(result.current.result?.ok).toBe(false);
    if (result.current.result && !result.current.result.ok) {
      expect(result.current.result.code).toBe("NETWORK");
    }
  });

  it("a refusal stamps lastSync too — it IS an answer we received", async () => {
    // Leaving lastSync untouched on a refusal would show a fresh time over
    // stale data, which is the failure the comment in use-api.ts describes.
    vi.spyOn(apiModule, "api").mockResolvedValue({
      ok: false, status: 503, code: "AUTH_UNAVAILABLE", message: "no",
    } as never);

    const { result } = renderHook(() => useRead<{ v: number }>("me"));
    await waitFor(() => expect(result.current.result).not.toBeNull());
    expect(result.current.lastSync).not.toBeNull();
  });

  it("a successful read publishes its data and stops loading", async () => {
    vi.spyOn(apiModule, "api").mockResolvedValue({
      ok: true, data: { v: 42 },
    } as never);

    const { result } = renderHook(() => useRead<{ v: number }>("positions"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.result).toEqual({ ok: true, data: { v: 42 } });
  });
});

describe("a null path reads nothing", () => {
  it("makes no call at all", async () => {
    const spy = vi.spyOn(apiModule, "api").mockResolvedValue({
      ok: true, data: {},
    } as never);
    const { result } = renderHook(() => useRead<unknown>(null));
    await act(async () => { await Promise.resolve(); });
    expect(spy).not.toHaveBeenCalled();
    // And it does not sit on a spinner forever for a read it never started.
    expect(result.current.loading).toBe(false);
  });
});

describe("whenSynced says how old the numbers are", () => {
  it("never, when nothing has synced", () => {
    // "never" rather than a time, because a dashboard that polls silently
    // looks identical whether it refreshed a second ago or died twenty
    // minutes back.
    expect(whenSynced(null)).toBe("never");
  });

  it("just now, seconds, then minutes", () => {
    const now = Date.now();
    vi.spyOn(Date, "now").mockReturnValue(now);
    expect(whenSynced(now - 1_000)).toBe("just now");
    expect(whenSynced(now - 30_000)).toBe("30s ago");
    expect(whenSynced(now - 600_000)).toBe("10m ago");
  });
});

/**
 * `invalidate` — the status strip must not outlive the control that changed it.
 *
 * Found in a browser, not by a test. The dashboard polled `automation` on its
 * own clock and so did the app shell, for the status strip. Pressing Start
 * reloaded the dashboard's copy and left the shell's alone, so for up to
 * thirty seconds the server said `running`, the panel said "Watching market",
 * and the strip at the top of every screen said "Automation STOPPED".
 *
 * On the rule page the strip is the ONLY automation indicator, so the whole
 * screen said stopped over a loop that had started. That is the one thing
 * this strip exists to never do.
 */
describe("invalidate reaches every reader of a path", () => {
  it("reloads BOTH copies of the same endpoint, not just the caller's", async () => {
    // Overlapping reads of one path share a single request. Counting calls
    // cannot tell "both reloaded" from "one reloaded twice", so the proof is
    // that BOTH hooks take the answer from the reload.
    let n = 0;
    vi.spyOn(apiModule, "api").mockImplementation(async () => {
      n += 1;
      return { ok: true, data: { n } } as never;
    });

    const shell = renderHook(() => useRead<{ n: number }>("automation"));
    const page = renderHook(() => useRead<{ n: number }>("automation"));
    await waitFor(() => {
      expect(shell.result.current.result?.ok).toBe(true);
      expect(page.result.current.result?.ok).toBe(true);
    });
    const before = n;

    await act(async () => { invalidate("automation"); });
    await waitFor(() => {
      const left = shell.result.current.result;
      const right = page.result.current.result;
      expect(left?.ok && left.data.n).toBe(before + 1);
      expect(right?.ok && right.data.n).toBe(before + 1);
    });
    // One shared reload, not one request per subscriber.
    expect(n).toBe(before + 1);

    shell.unmount();
    page.unmount();
  });

  it("leaves other endpoints alone", async () => {
    const spy = vi.spyOn(apiModule, "api")
      .mockResolvedValue({ ok: true, data: {} } as never);
    const other = renderHook(() => useRead("positions"));
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));

    await act(async () => { invalidate("automation"); });
    // Deliberately exact-match: a prefix rule would reload reads the caller
    // never named, and the naming is the part a reviewer can check.
    expect(spy).toHaveBeenCalledTimes(1);
    other.unmount();
  });

  it("forgets a reader that unmounted", async () => {
    const spy = vi.spyOn(apiModule, "api")
      .mockResolvedValue({ ok: true, data: {} } as never);
    const gone = renderHook(() => useRead("automation"));
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
    gone.unmount();

    await act(async () => { invalidate("automation"); });
    // A left-over subscription would call api() against a component that no
    // longer exists, and React would warn on the state it tried to set.
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("reloads accounts and positions together, and leaves journal alone", async () => {
    // The shell reads `accounts` while a page reads `ctrader/status`.
    // positions has no account id in the path, so it keeps the previous
    // account until something reloads it. journal is not a broker view.
    const spy = vi.spyOn(apiModule, "api")
      .mockResolvedValue({ ok: true, data: {} } as never);
    const accounts = renderHook(() => useRead("accounts"));
    const positions = renderHook(() => useRead("positions"));
    const journal = renderHook(() => useRead("journal"));
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(3));

    await act(async () => { invalidateBrokerViews(); });
    await waitFor(() => expect(spy.mock.calls.filter((c) => c[0] === "accounts").length).toBe(2));
    expect(spy.mock.calls.filter((c) => c[0] === "positions").length).toBe(2);
    expect(spy.mock.calls.filter((c) => c[0] === "journal").length).toBe(1);

    accounts.unmount();
    positions.unmount();
    journal.unmount();
  });

  it("reloads when the network comes back", async () => {
    // SEEN ON A PHONE during the first production walk-through: the device
    // moved from WiFi to 5G, the in-flight reads failed, and the status bar
    // fell to "Account Unknown". Saying "unknown" rather than repeating
    // stale data is correct — the UI must not claim an account it could not
    // verify — but nothing retried, so the client had to know to reload the
    // page. A client who does not know that reads a working product as a
    // broken one.
    const spy = vi.spyOn(apiModule, "api")
      .mockResolvedValue({ ok: true, data: {} } as never);
    const h = renderHook(() => useRead("ctrader/status"));
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));

    await act(async () => { window.dispatchEvent(new Event("online")); });
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
    h.unmount();
  });

  it("recovers even for a reader with no polling interval", async () => {
    // The recovery listener sits OUTSIDE the interval effect on purpose: a
    // hook created without intervalMs returns early there and so never
    // retried at all. The status bar is exactly that case, which is why it
    // stayed "Unknown" until a manual reload.
    const spy = vi.spyOn(apiModule, "api")
      .mockResolvedValue({ ok: true, data: {} } as never);
    // No interval at all — the status-bar case.
    const h = renderHook(() => useRead("me"));
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));

    await act(async () => { window.dispatchEvent(new Event("online")); });
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
    h.unmount();
  });

  it("asks again after the previous reader unmounts mid-flight", async () => {
    // The flight map is process-wide. A screen that goes away while its read
    // is still open must not leave that request for the next screen to join,
    // or the next screen waits on a promise nobody will resolve.
    const signals: AbortSignal[] = [];
    const pending: Array<{ resolve: (v: unknown) => void }> = [];
    vi.spyOn(apiModule, "api").mockImplementation((_path, opts) => {
      const signal = (opts as { signal?: AbortSignal } | undefined)?.signal;
      if (signal) signals.push(signal);
      const d = deferred<unknown>();
      pending.push({ resolve: d.resolve });
      return d.promise as never;
    });

    const first = renderHook(() => useRead<{ v: number }>("ctrader/status"));
    await waitFor(() => expect(signals).toHaveLength(1));
    first.unmount();

    const second = renderHook(() => useRead<{ v: number }>("ctrader/status"));
    await waitFor(() => expect(signals).toHaveLength(2));
    expect(signals[0].aborted).toBe(true);
    expect(signals[1].aborted).toBe(false);

    await act(async () => {
      pending[1].resolve({ ok: true, data: { v: 2 } });
      await Promise.resolve();
    });
    await waitFor(() => expect(second.result.current.result).toEqual({ ok: true, data: { v: 2 } }));
    second.unmount();
  });

  it("does not send a second request while the same read is still in flight", async () => {
    vi.useFakeTimers();
    try {
      const signals: AbortSignal[] = [];
      let resolveFirst: (value: apiModule.ApiResult<{ v: number }>) => void = () => {};
      vi.spyOn(apiModule, "api").mockImplementation((_path, opts) => {
        const signal = (opts as { signal?: AbortSignal } | undefined)?.signal;
        if (signal) signals.push(signal);
        return new Promise<apiModule.ApiResult<{ v: number }>>((resolve) => {
          resolveFirst = resolve;
        });
      });
      const { result } = renderHook(() => useRead<{ v: number }>("positions", 5_000));
      await act(async () => { await vi.advanceTimersByTimeAsync(0); });
      expect(signals).toHaveLength(1);

      await act(async () => { await vi.advanceTimersByTimeAsync(5_000); });
      expect(signals, "a poll overlapped the read and aborted it").toHaveLength(1);
      expect(signals[0].aborted).toBe(false);

      await act(async () => {
        resolveFirst({ ok: true, data: { v: 1 } });
        await Promise.resolve();
      });
      expect(result.current.result).toEqual({ ok: true, data: { v: 1 } });
    } finally {
      vi.useRealTimers();
    }
  });

  it("waits out retryAfterSec before the next automatic poll", async () => {
    vi.useFakeTimers();
    try {
      let calls = 0;
      vi.spyOn(apiModule, "api").mockImplementation(async () => {
        calls += 1;
        if (calls === 1) return { ok: true, data: { v: 1 } } as never;
        return {
          ok: false, status: 429, code: "RATE_LIMITED",
          message: "too many requests — wait 30s and try again",
          retryAfterSec: 30,
        } as never;
      });
      renderHook(() => useRead("accounts/9/candles?symbol=EURUSD", 15_000));
      await act(async () => { await vi.advanceTimersByTimeAsync(0); });
      expect(calls).toBe(1);

      await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
      expect(calls).toBe(2);

      await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
      expect(calls, "polled again inside the stated wait").toBe(2);

      await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
      expect(calls).toBe(3);
    } finally {
      vi.useRealTimers();
    }
  });

  it("stops listening once the reader unmounts", async () => {
    const spy = vi.spyOn(apiModule, "api")
      .mockResolvedValue({ ok: true, data: {} } as never);
    const gone = renderHook(() => useRead("orders"));
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
    gone.unmount();

    await act(async () => { window.dispatchEvent(new Event("online")); });
    expect(spy).toHaveBeenCalledTimes(1);
  });
});
