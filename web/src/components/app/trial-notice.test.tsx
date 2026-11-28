/**
 * The 14-day demo trial, as the client sees it.
 *
 * WHY THIS FILE EXISTS
 *
 * The trial was built end to end on the server — `plans.start_trial` runs on
 * first authentication, `licence` ages it out, and `capability()` reports
 * `onTrial`, `trialDaysLeft`, `trialExpiresAt` and a distinct `TRIAL_EXPIRED`
 * reason — and NOTHING IN THE BROWSER READ ANY OF IT. A client spent fourteen
 * free days without being told there was a clock, and on day fifteen the
 * Start button went quiet: the refusal reached them as a disabled button's
 * hover text, which is not where somebody looks for the reason a product
 * stopped working.
 *
 * So the countdown is the product telling the truth about its own offer, and
 * these tests pin the two things that make it honest rather than pushy:
 *
 *   1. It appears ONLY for a client who is on the trial or whose trial has
 *      ended. A paid client is not shown a countdown, and neither is a client
 *      whose licence was withdrawn — that is a different conversation with a
 *      different next step, and `LICENCE_REVOKED` outranks it on the server.
 *   2. It states no price and makes no promise. The pricing sentence is
 *      `planNotice`, which the server owns and `PlanNotice` renders; a second
 *      copy of it here is a commercial claim nobody reviewed.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { TrialNotice } from "./state";
import { PLAN_NOTICE, type Execution } from "@/lib/api";

afterEach(() => cleanup());

const DAY = 86_400;
const NOW = 1_760_000_000;

/** A capability payload shaped exactly like the server's. */
function exec(over: Partial<Execution> = {}): Execution {
  return {
    accountMode: "demo",
    entitlement: "free_demo",
    licenceState: "active",
    liveExecutionEnabled: false,
    planNotice: PLAN_NOTICE,
    canAutomate: true,
    canActivate: true,
    activationRefusal: null,
    plan: "demo_trial",
    onTrial: true,
    trialDaysLeft: 9,
    trialExpiresAt: NOW + 9 * DAY,
    accountAllowance: 1,
    reason: null,
    message: "demo automation is available on this account",
    badge: "DEMO",
    ...over,
  };
}

describe("the demo trial countdown", () => {
  it("tells a client on the trial how many days are left", () => {
    render(<TrialNotice execution={exec()} />);
    expect(screen.getByText(/9 days left/i)).toBeTruthy();
    expect(screen.getByText(/free demo trial/i)).toBeTruthy();
  });

  it("says ONE day, not 1 days, on the last day", () => {
    render(<TrialNotice execution={exec({ trialDaysLeft: 1 })} />);
    expect(screen.getByText(/1 day left/i)).toBeTruthy();
    expect(screen.queryByText(/1 days left/i)).toBeNull();
  });

  it("marks the last few days as running out", () => {
    // Not decoration: the days a client decides in are the last ones, and a
    // countdown that reads identically on day 14 and day 2 is not a countdown.
    const { container: calm } = render(<TrialNotice execution={exec({ trialDaysLeft: 9 })} />);
    expect(calm.querySelector(".notice-warn")).toBeNull();
    cleanup();
    const { container: urgent } = render(<TrialNotice execution={exec({ trialDaysLeft: 2 })} />);
    expect(urgent.querySelector(".notice-warn")).not.toBeNull();
  });

  it("shows the server's own words when the trial has ended", () => {
    const ended =
      "the 14-day free demo trial for this account has ended — reconnect " +
      "once a plan is active, or contact support";
    render(
      <TrialNotice
        execution={exec({
          onTrial: false,
          trialDaysLeft: null,
          licenceState: "expired",
          canAutomate: false,
          reason: "TRIAL_EXPIRED",
          message: ended,
        })}
      />,
    );
    // The sentence, VISIBLE — not a title attribute on a disabled button.
    expect(screen.getByText(ended)).toBeTruthy();
  });

  it("renders nothing for a client who paid", () => {
    const { container } = render(
      <TrialNotice
        execution={exec({
          entitlement: "paid_live",
          plan: "founder_lifetime",
          onTrial: false,
          trialDaysLeft: null,
          trialExpiresAt: null,
        })}
      />,
    );
    expect(container.innerHTML).toBe("");
  });

  it("renders nothing when the licence was withdrawn", () => {
    // A withdrawn licence is support's decision and outranks the trial on the
    // server. Offering a countdown next to it would be the product arguing
    // with its own refusal.
    const { container } = render(
      <TrialNotice
        execution={exec({
          onTrial: false,
          trialDaysLeft: null,
          licenceState: "revoked",
          canAutomate: false,
          reason: "LICENCE_REVOKED",
          message: "this licence was withdrawn — contact support",
        })}
      />,
    );
    expect(container.innerHTML).toBe("");
  });

  it("renders nothing before the capability has arrived", () => {
    const { container } = render(<TrialNotice execution={null} />);
    expect(container.innerHTML).toBe("");
    cleanup();
    const { container: undef } = render(<TrialNotice />);
    expect(undef.innerHTML).toBe("");
  });

  it("survives a trial with no expiry recorded", () => {
    // An older record, or a clock that could not be read. The countdown is
    // still worth showing; the date is what goes missing, not the warning.
    render(<TrialNotice execution={exec({ trialExpiresAt: null })} />);
    expect(screen.getByText(/9 days left/i)).toBeTruthy();
  });

  it("does not restate the price", () => {
    // `planNotice` is the one sentence about money, it lives on the server,
    // and `PlanNotice` renders it directly below this. A copy here is a
    // pricing claim in a component.
    const { container } = render(<TrialNotice execution={exec()} />);
    expect(container.textContent).not.toMatch(/\$|497|USD/);
  });
});
