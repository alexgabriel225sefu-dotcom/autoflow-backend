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
import { useRead, whenSynced } from "./use-api";
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
