import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const signIn = vi.fn();
vi.mock("@/lib/supabase/client", () => ({
  createClient: () => ({ auth: { signInWithPassword: (b: unknown) => signIn(b) } }),
}));

import {
  WATCH_INTERVAL_MS, WATCH_RATE_LIMITED_GAP_MS, isRateLimited, isUnconfirmed,
  useConfirmationWatch,
} from "./use-confirmation-watch";

const flush = async (ms: number) => { await act(async () => { await vi.advanceTimersByTimeAsync(ms); }); };

beforeEach(() => { vi.useFakeTimers(); signIn.mockReset(); });
afterEach(() => { vi.useRealTimers(); });

const unconfirmed = { error: { message: "Email not confirmed", code: "email_not_confirmed" } };

describe("error classification", () => {
  it("tells an unconfirmed address from a wrong password and from a rate limit", () => {
    expect(isUnconfirmed({ message: "Email not confirmed" })).toBe(true);
    expect(isUnconfirmed({ code: "email_not_confirmed" })).toBe(true);
    expect(isUnconfirmed({ message: "Invalid login credentials" })).toBe(false);
    expect(isRateLimited({ message: "email rate limit exceeded" })).toBe(true);
    expect(isRateLimited({ status: 429 })).toBe(true);
    expect(isRateLimited({ message: "Email not confirmed" })).toBe(false);
  });
});

describe("useConfirmationWatch", () => {
  it("does nothing until it is enabled, and never without a password", async () => {
    renderHook(() => useConfirmationWatch({ enabled: false, email: "a@b.test", password: "x", onConfirmed: vi.fn() }));
    renderHook(() => useConfirmationWatch({ enabled: true, email: "a@b.test", password: "", onConfirmed: vi.fn() }));
    await flush(WATCH_INTERVAL_MS * 3);
    expect(signIn).not.toHaveBeenCalled();
  });

  it("keeps waiting while the address is unconfirmed, then continues when sign-in works", async () => {
    const onConfirmed = vi.fn();
    signIn.mockResolvedValueOnce(unconfirmed).mockResolvedValueOnce(unconfirmed).mockResolvedValue({ error: null });
    renderHook(() => useConfirmationWatch({ enabled: true, email: "a@b.test", password: "pw-long-enough", onConfirmed }));
    await flush(WATCH_INTERVAL_MS);
    await flush(WATCH_INTERVAL_MS);
    expect(onConfirmed).not.toHaveBeenCalled();
    await flush(WATCH_INTERVAL_MS);
    expect(onConfirmed).toHaveBeenCalledTimes(1);
    expect(signIn).toHaveBeenLastCalledWith({ email: "a@b.test", password: "pw-long-enough" });
    // and it stops asking once it has succeeded
    const calls = signIn.mock.calls.length;
    await flush(WATCH_INTERVAL_MS * 3);
    expect(signIn.mock.calls.length).toBe(calls);
  });

  it("asks at once when the person returns to the tab", async () => {
    const onConfirmed = vi.fn();
    signIn.mockResolvedValue({ error: null });
    renderHook(() => useConfirmationWatch({ enabled: true, email: "a@b.test", password: "pw-long-enough", onConfirmed }));
    await flush(4000);               // past the minimum gap, before the first timer tick
    await act(async () => { window.dispatchEvent(new Event("focus")); await Promise.resolve(); });
    expect(onConfirmed).toHaveBeenCalledTimes(1);
  });

  it("stops for good on a wrong password instead of hammering sign-in", async () => {
    signIn.mockResolvedValue({ error: { message: "Invalid login credentials" } });
    renderHook(() => useConfirmationWatch({ enabled: true, email: "a@b.test", password: "wrong", onConfirmed: vi.fn() }));
    await flush(WATCH_INTERVAL_MS);
    await flush(WATCH_INTERVAL_MS * 3);
    expect(signIn).toHaveBeenCalledTimes(1);
  });

  it("after a rate limit stops the timer and only a return to the tab asks again", async () => {
    signIn.mockResolvedValue({ error: { message: "email rate limit exceeded", status: 429 } });
    renderHook(() => useConfirmationWatch({ enabled: true, email: "a@b.test", password: "pw-long-enough", onConfirmed: vi.fn() }));
    await flush(WATCH_INTERVAL_MS);
    expect(signIn).toHaveBeenCalledTimes(1);
    await flush(WATCH_INTERVAL_MS * 3);
    expect(signIn).toHaveBeenCalledTimes(1);
    await flush(WATCH_RATE_LIMITED_GAP_MS);
    await act(async () => { window.dispatchEvent(new Event("focus")); await Promise.resolve(); });
    expect(signIn).toHaveBeenCalledTimes(2);
  });

  it("stops when the page goes away", async () => {
    signIn.mockResolvedValue(unconfirmed);
    const { unmount } = renderHook(() => useConfirmationWatch({ enabled: true, email: "a@b.test", password: "pw-long-enough", onConfirmed: vi.fn() }));
    unmount();
    await flush(WATCH_INTERVAL_MS * 3);
    expect(signIn).not.toHaveBeenCalled();
  });
});
