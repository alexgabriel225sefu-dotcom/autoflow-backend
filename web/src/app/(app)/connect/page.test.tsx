/**
 * The connect page must never invite a step the visitor has already taken.
 *
 * WHY THIS FILE EXISTS
 *
 * This has now gone wrong three times in one file, with three different
 * causes and the same symptom: an already-linked owner is shown
 * "Step 1 — authorise" with a Connect button, presses it because it is the
 * only button on the card, and starts a second OAuth round for an account he
 * already has. The oauth bucket is ten requests a minute, so what he actually
 * sees is RATE_LIMITED, and the feature reads as broken.
 *
 * Twice the cause was a stale `pending` nonce, and both times the fix was to
 * let the server's verdict win. The third — found on a phone on 2026-10-04,
 * with the Status card above still reading "Loading…" while this card offered
 * step 1 — is that NO VERDICT YET was still rendering as "not connected".
 *
 * So the rule under test is not "connected hides step 1". It is: step 1 is
 * offered only when the server has actually said there is nothing linked.
 * Loading is not a no. A failed read is not a no either.
 */
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ApiResult } from "@/lib/api";

let answer: ((r: ApiResult<unknown>) => void) | null = null;
let pendingRead: Promise<ApiResult<unknown>> | null = null;

vi.mock("@/lib/api", async (orig) => {
  const actual = await orig<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: vi.fn(() => pendingRead ?? Promise.resolve(
      { ok: false, status: 404, code: "NOT_FOUND", message: "no stub" })),
  };
});

import ConnectPage from "./page";

const CONNECTED = {
  ok: true as const,
  data: {
    connected: true,
    accounts: [{ ctid: 47765456, mode: "demo", label: "" }],
    selected: null, liveAllowed: false,
  },
};
const NOT_CONNECTED = {
  ok: true as const,
  data: { connected: false, accounts: [], selected: null, liveAllowed: false },
};
const READ_FAILED = {
  ok: false as const, status: 503, code: "STORE_UNAVAILABLE",
  message: "the platform could not read your broker link",
};

/** A read the test holds open, so the in-flight state can be inspected. */
function heldRead() {
  let resolve!: (r: ApiResult<unknown>) => void;
  pendingRead = new Promise<ApiResult<unknown>>((r) => { resolve = r; });
  answer = resolve;
}

beforeEach(() => {
  sessionStorage.clear();
  pendingRead = null;
  answer = null;
});
afterEach(() => { vi.clearAllMocks(); });

const connectButton = () => screen.queryByRole("button", { name: /^connect ctrader$/i });

describe("while the server has not answered yet", () => {
  it("does not offer to start a connection", async () => {
    heldRead();
    render(<ConnectPage />);
    // The exact state the phone was in: Status "Loading…", and this card
    // must not be inviting step 1 underneath it.
    await screen.findByText(/checking whether you already have/i);
    expect(connectButton()).toBeNull();
    expect(screen.queryByText(/step 1/i)).toBeNull();
  });

  it("and offers it as soon as the server says there is nothing linked", async () => {
    heldRead();
    render(<ConnectPage />);
    await screen.findByText(/checking whether you already have/i);
    answer!(NOT_CONNECTED as ApiResult<unknown>);
    await waitFor(() => expect(connectButton()).not.toBeNull());
    expect(screen.getByText(/step 1/i)).toBeTruthy();
  });
});

describe("when the server answers", () => {
  it("offers step 1 only when nothing is linked", async () => {
    pendingRead = Promise.resolve(NOT_CONNECTED as ApiResult<unknown>);
    render(<ConnectPage />);
    await waitFor(() => expect(connectButton()).not.toBeNull());
  });

  it("never offers step 1 to somebody already linked", async () => {
    pendingRead = Promise.resolve(CONNECTED as ApiResult<unknown>);
    render(<ConnectPage />);
    await screen.findByText(/ctrader is linked/i);
    expect(connectButton()).toBeNull();
    expect(screen.queryByText(/step 1/i)).toBeNull();
    // Adding a SECOND account stays reachable — demoted, not removed.
    expect(screen.getByRole("button", { name: /connect another account/i })).toBeTruthy();
  });

  it("names which account is linked, since that is the question", async () => {
    pendingRead = Promise.resolve(CONNECTED as ApiResult<unknown>);
    render(<ConnectPage />);
    expect(await screen.findByText(/DEMO #47765456/)).toBeTruthy();
  });
});

describe("when the read fails", () => {
  it("still does not offer step 1 — an error is not a 'no'", async () => {
    // The dangerous reading. A 503 says we could not look; rendering the
    // connect button over it sends somebody through OAuth for an account
    // they may already have linked.
    pendingRead = Promise.resolve(READ_FAILED as ApiResult<unknown>);
    render(<ConnectPage />);
    await screen.findByText(/checking whether you already have/i);
    expect(connectButton()).toBeNull();
  });
});
