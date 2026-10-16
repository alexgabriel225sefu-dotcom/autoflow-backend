/**
 * The referral link, and the disclosure it must never appear without.
 *
 * WHY THIS FILE EXISTS
 *
 * The account-limit refusal is the only place in the product that shows a
 * link to open a broker account under the operator's introducing-broker code.
 * That arrangement pays the operator from the volume the client trades, while
 * this platform decides how often to trade — so a link shown without saying
 * so is the version both a client and a regulator object to.
 *
 * The server never hands out the url alone: `referral.broker_signup()` returns
 * the url and the disclosure together and there is no other accessor. This
 * file is the other half of that guarantee, on the rendering side. The failure
 * it exists to catch is somebody tidying the markup and leaving the anchor
 * while the paragraph goes.
 *
 * It also pins the PLACEMENT. The component renders nothing for any code
 * other than ACCOUNT_LIMIT, because every client reads the screens it sits on
 * and almost all of them want exactly one account — a link they all see is
 * advertising, not an answer.
 */
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { cleanup } from "@testing-library/react";
import { AccountLimitNotice, MoreAccountsSection } from "./state";
import type { ApiError } from "@/lib/api";

afterEach(() => cleanup());

const DISCLOSURE =
  "Opening an account through this link pays the operator of this platform " +
  "a commission from the broker, based on the volume you trade. You do not " +
  "have to use it: you can open an account with any cTrader broker and " +
  "connect it here instead, and the accounts you already use are unaffected.";

function limitError(extra: Partial<ApiError> = {}): ApiError {
  return {
    ok: false,
    status: 400,
    code: "ACCOUNT_LIMIT",
    message:
      "this plan covers 1 real-money trading account and 1 is already in use.",
    ...extra,
  };
}

describe("the account-limit notice", () => {
  it("renders nothing for any other refusal", () => {
    const { container } = render(
      <AccountLimitNotice error={limitError({ code: "NO_SUCH_ACCOUNT" })} />,
    );
    expect(container.innerHTML).toBe("");
  });

  it("shows the server's own refusal text, not a rewritten one", () => {
    render(<AccountLimitNotice error={limitError()} />);
    expect(
      screen.getByText(/1 real-money trading account and 1 is already in use/i),
    ).toBeTruthy();
  });

  it("renders the link ONLY together with the disclosure", () => {
    render(
      <AccountLimitNotice
        error={limitError({
          brokerSignup: { url: "https://portal.example.test/r", disclosure: DISCLOSURE },
        })}
      />,
    );
    const link = screen.getByRole("link");
    expect(link.getAttribute("href")).toBe("https://portal.example.test/r");
    // The disclosure, in the same rendered output as the link.
    expect(screen.getByText(/pays the operator of this platform/i)).toBeTruthy();
    expect(screen.getByText(/do not have to use it/i)).toBeTruthy();
  });

  it("marks the link so it is not treated as an ordinary endorsement", () => {
    render(
      <AccountLimitNotice
        error={limitError({
          brokerSignup: { url: "https://portal.example.test/r", disclosure: DISCLOSURE },
        })}
      />,
    );
    const rel = screen.getByRole("link").getAttribute("rel") ?? "";
    for (const token of ["noopener", "noreferrer", "nofollow", "sponsored"]) {
      expect(rel).toContain(token);
    }
  });

  it("shows NO link when the server sent none, and says what to do instead", () => {
    render(<AccountLimitNotice error={limitError()} />);
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.getByText(/contact support/i)).toBeTruthy();
  });

  it("NEVER renders a bare link: a payload missing the disclosure is "
    + "dropped at the api layer, and this is the fallback if one arrives", () => {
    render(
      <AccountLimitNotice
        error={limitError({
          // Deliberately malformed — the api layer's type guard rejects this
          // shape, so reaching the component at all means something upstream
          // is wrong. The component must still not show a naked referral link.
          brokerSignup: { url: "https://portal.example.test/r", disclosure: "" } as never,
        })}
      />,
    );
    // No link at all: an empty disclosure means the payload is unusable, and
    // the fallback is support rather than a naked referral link.
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.getByText(/contact support/i)).toBeTruthy();
  });
});

/**
 * The "More accounts — free" section.
 *
 * Same rule as the refusal notice, for the same reason: the link and the
 * disclosure render together or not at all. This section is the one a client
 * FINDS rather than hits, so it is the more likely of the two to be tidied
 * later by somebody who has not read why the paragraph is there.
 */
describe("the More accounts section", () => {
  const SIGNUP = { url: "https://portal.example.test/r", disclosure: DISCLOSURE };
  const plan = (over = {}) => ({
    realMoneyAllowance: 1, realMoneyUsed: 1, demoUnlimited: true,
    confirmed: false, signup: SIGNUP, ...over,
  });

  it("states the allowance and that demo is unlimited", () => {
    render(<MoreAccountsSection plan={plan()} />);
    expect(screen.getByText(/demo accounts are unlimited/i)).toBeTruthy();
    expect(screen.getByText(/1 real-money account/i)).toBeTruthy();
  });

  it("renders the link only together with the disclosure", () => {
    render(<MoreAccountsSection plan={plan()} />);
    expect(screen.getByRole("link").getAttribute("href")).toBe(SIGNUP.url);
    expect(screen.getByText(/pays the operator of this platform/i)).toBeTruthy();
  });

  it("marks the link as the paid arrangement it is", () => {
    render(<MoreAccountsSection plan={plan()} />);
    const rel = screen.getByRole("link").getAttribute("rel") ?? "";
    for (const t of ["noopener", "noreferrer", "nofollow", "sponsored"]) {
      expect(rel).toContain(t);
    }
  });

  it("does not send a CONFIRMED client back to the link", () => {
    render(<MoreAccountsSection plan={plan({ confirmed: true, signup: null })} />);
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.getByText(/confirmed under the referral programme/i)).toBeTruthy();
  });

  it("shows no bare link when the disclosure is missing", () => {
    render(
      <MoreAccountsSection
        plan={plan({ signup: { url: SIGNUP.url, disclosure: "   " } })}
      />,
    );
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.getByText(/contact support/i)).toBeTruthy();
  });

  it("tells the client which platform to pick at the broker", () => {
    // The referral broker offers cTrader, and offers other platforms too.
    // This product speaks cTrader and nothing else, so a client who takes the
    // link and picks MT5 ends up with an account that cannot be connected
    // here — after the operator has already paid for the introduction. One
    // sentence next to the link is the whole fix.
    render(<MoreAccountsSection plan={plan()} />);
    expect(screen.getByText(/choose cTrader/i)).toBeTruthy();
  });

  it("does not repeat the platform hint when there is no link", () => {
    render(
      <MoreAccountsSection
        plan={plan({ signup: { url: SIGNUP.url, disclosure: "" } })}
      />,
    );
    expect(screen.queryByText(/choose cTrader/i)).toBeNull();
  });

  it("renders nothing at all when the server sent no plan", () => {
    const { container } = render(<MoreAccountsSection plan={undefined} />);
    expect(container.innerHTML).toBe("");
  });
});
