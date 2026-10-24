/**
 * The review screen is not a way to become an operator.
 *
 * The server answers 403 NOT_OPERATOR when this account is not on
 * A4T_OPERATOR_USER_IDS. The page has to say so and take the decision
 * controls away — Approve and Reject left on screen would invite a press
 * the server has already refused.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ApiResult } from "@/lib/api";

const api = vi.fn();

vi.mock("@/lib/api", async (orig) => {
  const actual = await orig<typeof import("@/lib/api")>();
  return { ...actual, api: (...args: unknown[]) => api(...args) };
});

import LiveReviewPage from "./page";

const NOT_OPERATOR: ApiResult<never> = {
  ok: false,
  status: 403,
  code: "NOT_OPERATOR",
  message: "this action is limited to an operator",
};

describe("live review", () => {
  it("shows an operator-only state and hides Approve and Reject on 403", async () => {
    api.mockResolvedValue(NOT_OPERATOR);
    render(<LiveReviewPage />);
    expect(screen.getByRole("button", { name: "Approve" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Reject" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Load queue" }));
    const status = await screen.findByRole("status");
    expect(status.textContent).toMatch(/Operators only/i);
    expect(screen.getByText(/limited to an operator/i)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Reject" })).toBeNull();
    expect(api).toHaveBeenCalledWith("live/queue");
  });

  it("keeps the decision controls when the refusal is not 'not an operator'", async () => {
    api.mockResolvedValue({
      ok: false, status: 503, code: "STORE_UNAVAILABLE", message: "the queue could not be read",
    });
    render(<LiveReviewPage />);
    fireEvent.click(screen.getByRole("button", { name: "Load queue" }));
    await waitFor(() => expect(screen.getByText("STORE_UNAVAILABLE")).toBeTruthy());
    expect(screen.getByRole("button", { name: "Approve" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Reject" })).toBeTruthy();
  });
});
