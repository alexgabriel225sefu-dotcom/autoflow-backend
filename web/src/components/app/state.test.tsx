/**
 * The UI's half of the honesty contract.
 *
 * The backend already distinguishes "there is nothing" from "we could not
 * ask". These checks are about the frontend not undoing that — the failure
 * being guarded is a confident empty table rendered over a 503.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ErrorNotice, ReadPanel, StatusPill } from "./state";

describe("ReadPanel", () => {
  it("renders the data only when the backend said status ok", () => {
    render(
      <ReadPanel read={{ connected: true, status: "ok" }}>
        <p>No open positions.</p>
      </ReadPanel>,
    );
    expect(screen.getByText("No open positions.")).toBeDefined();
  });

  it("never renders an empty state when the account is not connected", () => {
    render(
      <ReadPanel read={{ connected: false, status: "not_connected" }}>
        <p>No open positions.</p>
      </ReadPanel>,
    );
    // The reassuring sentence must NOT appear: we did not ask anyone.
    expect(screen.queryByText("No open positions.")).toBeNull();
    expect(screen.getByText(/No cTrader account is connected/)).toBeDefined();
  });

  it("offers reconnection, and only that, when the token needs reauth", () => {
    render(
      <ReadPanel read={{ connected: true, status: "reauth_required", reason: "expired" }}>
        <p>No open positions.</p>
      </ReadPanel>,
    );
    expect(screen.queryByText("No open positions.")).toBeNull();
    expect(screen.getByText("Reconnect cTrader")).toBeDefined();
    expect(screen.getByText("expired")).toBeDefined();
  });

  it("shows the backend's real reason when the broker could not be reached", () => {
    render(
      <ReadPanel read={{ connected: true, status: "unavailable", reason: "TimeoutError: 12s" }}>
        <p>No open positions.</p>
      </ReadPanel>,
    );
    expect(screen.queryByText("No open positions.")).toBeNull();
    // Not a friendlier sentence we invented.
    expect(screen.getByText("TimeoutError: 12s")).toBeDefined();
  });
});

describe("StatusPill", () => {
  it("labels demo and live differently and never guesses", () => {
    const { rerender } = render(<StatusPill mode="demo" />);
    expect(screen.getByText("DEMO")).toBeDefined();
    rerender(<StatusPill mode="live" />);
    expect(screen.getByText("LIVE")).toBeDefined();
    rerender(<StatusPill mode={null} />);
    expect(screen.getByText("No account selected")).toBeDefined();
  });
});

describe("ErrorNotice", () => {
  it("shows the code and the backend's own message", () => {
    render(<ErrorNotice error={{
      ok: false, status: 503, code: "AUTH_UNAVAILABLE",
      message: "could not reach Supabase",
    }} />);
    expect(screen.getByText("AUTH_UNAVAILABLE")).toBeDefined();
    expect(screen.getByText("could not reach Supabase")).toBeDefined();
    expect(screen.getByText(/HTTP 503/)).toBeDefined();
  });

  it("lists every validation problem so a form can point at each", () => {
    render(<ErrorNotice error={{
      ok: false, status: 422, code: "RULE_INVALID", message: "invalid",
      problems: ["symbols: required", "stopLoss.mode: must be 'atr' or 'pips'"],
    }} />);
    expect(screen.getByText("symbols: required")).toBeDefined();
    expect(screen.getByText(/stopLoss.mode/)).toBeDefined();
  });
});
