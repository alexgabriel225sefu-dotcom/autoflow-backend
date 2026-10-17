/**
 * Stopping does not close positions, and the client must be told so.
 *
 * THE BUG, AND IT IS THE MOST EXPENSIVE SILENCE IN THE PRODUCT
 *
 * §8.1 of the live-execution specification requires a per-client stop to
 * flatten or explicitly DECLINE to flatten, and to say which. The server has
 * always answered correctly: `flattened: false`, `flattenDeclined: true`, and
 * a sentence explaining that an open position stays at the broker with the
 * stop and target it was given.
 *
 * `AutomationState` did not carry the fields, so the browser dropped the
 * whole answer and both control sites reported `Automation is now stopped`.
 *
 * A client with a losing position presses Stop, reads "stopped", reasonably
 * understands "and I am flat", and closes the tab. The position is still open
 * at their broker. The only place the truth appeared was a notification on a
 * page they were never sent to.
 *
 * WHAT THESE TESTS WILL NOT ACCEPT
 *
 * That the words exist somewhere. The failure was a correct server answer
 * being thrown away by the layer above it, so what is asserted is that the
 * SERVER's sentence survives into what the client reads — and that it stops
 * being shown the moment the server stops declining, because a warning that
 * outlives its truth is the same defect pointing the other way.
 */
import { describe, expect, it } from "vitest";
import { outcomeOf } from "./plain";

// The exact shape `automation.stop` returns today, from
// `apex/platform/automation.py:_flatten_answer`.
const DECLINED = {
  state: "stopped",
  flattened: false,
  flattenDeclined: true,
  flattenReason:
    "Stopping ends the trading loop. It does not close positions that are "
    + "already open — this release has no way to close a position. Any open "
    + "position stays at your broker with the stop and target it was given, "
    + "and you close it there.",
};

describe("the outcome of a stop", () => {
  it("does not report only the new state", () => {
    // The whole bug in one assertion.
    expect(outcomeOf(DECLINED)).not.toBe("Automation is now stopped");
  });

  it("still says what the state now is", () => {
    expect(outcomeOf(DECLINED)).toContain("stopped");
  });

  it("carries the server's refusal to flatten, verbatim", () => {
    // Verbatim on purpose. What a stop does to real exposure is not
    // something to keep a second copy of in a browser, where it would be
    // free to drift from what actually happened.
    expect(outcomeOf(DECLINED)).toContain(DECLINED.flattenReason);
  });

  it("tells the client where the position is and who closes it", () => {
    const out = outcomeOf(DECLINED);
    expect(out).toMatch(/stays at your broker/);
    expect(out).toMatch(/you close it there/);
  });
});

describe("and it stops warning when there is nothing to warn about", () => {
  it("says nothing extra once a release actually flattens", () => {
    // A warning that outlives its truth trains clients to ignore the ones
    // that are true.
    const flattened = {
      state: "stopped",
      flattened: true,
      flattenDeclined: false,
      flattenReason: null,
    };
    expect(outcomeOf(flattened)).toBe("Automation is now stopped");
  });

  it("adds nothing to a start", () => {
    expect(outcomeOf({ state: "running" })).toBe("Automation is now running");
  });

  it("adds nothing when the server sent no reason", () => {
    // Declined with no sentence is a server bug, not something to paper over
    // with copy invented here.
    expect(outcomeOf({ state: "stopped", flattenDeclined: true }))
      .toBe("Automation is now stopped");
  });
});
