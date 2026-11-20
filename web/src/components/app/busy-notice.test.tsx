/**
 * What a rate-limited read looks like while it waits to retry.
 *
 * A 429 used to render as "Slow down a moment" over an otherwise empty page,
 * with no sign that anything would happen next. When the read has a retry
 * scheduled it now says so, in plain words, and counts the seconds down.
 */
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ErrorNotice } from "./state";
import type { ApiError } from "@/lib/api";

const refused = (extra: Partial<ApiError> = {}): ApiError => ({
  ok: false, status: 429, code: "RATE_LIMITED",
  message: "too many requests — wait 12s and try again",
  retryAfterSec: 12, ...extra,
});

beforeEach(() => { vi.useFakeTimers(); });
afterEach(() => { vi.useRealTimers(); });

describe("ErrorNotice on a rate limit", () => {
  it("says it is busy and when it will retry, and counts down", async () => {
    render(<ErrorNotice error={refused({ retryAt: Date.now() + 12_000 })} />);
    const notice = screen.getByRole("status");
    expect(notice.textContent).toMatch(/busy/i);
    expect(notice.textContent).toMatch(/retrying in 12 s/i);
    // Plain words: no error code, and not the server's raw sentence.
    expect(notice.textContent).not.toMatch(/RATE_LIMITED/);
    expect(notice.textContent).not.toMatch(/too many requests/);

    await act(async () => { await vi.advanceTimersByTimeAsync(5_000); });
    expect(screen.getByRole("status").textContent).toMatch(/retrying in 7 s/i);

    await act(async () => { await vi.advanceTimersByTimeAsync(7_000); });
    expect(screen.getByRole("status").textContent).toMatch(/retrying now/i);
  });

  it("makes no promise of a retry when none is scheduled", () => {
    render(<ErrorNotice error={refused()} />);
    const notice = screen.getByRole("status");
    expect(notice.textContent).not.toMatch(/retrying/i);
    expect(notice.textContent).toMatch(/wait 12s and try again/);
  });

  it("leaves every other error as it was", () => {
    render(<ErrorNotice error={{ ok: false, status: 503, code: "STORE_UNAVAILABLE", message: "store down" }} />);
    expect(screen.getByRole("alert").textContent).toMatch(/store down/);
  });
});
