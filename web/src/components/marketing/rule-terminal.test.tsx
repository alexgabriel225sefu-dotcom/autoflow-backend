import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RuleTerminal } from "./rule-terminal";

const RULE = "Buy EURUSD on 1h when RSI(14, above, 55); risk 1.0% per trade.";
const REPLY = ["Market: EURUSD, 1h", "Preview only. Nothing is placed."];

describe("RuleTerminal", () => {
  it("has the full rule and reply in the DOM without any animation", () => {
    render(<RuleTerminal rule={RULE} reply={REPLY} />);
    // Hidden copy is readable by assistive tech; the animated copy is aria-hidden.
    expect(screen.getAllByText(RULE).length).toBeGreaterThanOrEqual(1);
    for (const l of REPLY) expect(screen.getAllByText(l).length).toBeGreaterThanOrEqual(1);
    expect(document.body.textContent).toContain(RULE);
  });

  it("marks the animated copy aria-hidden so the rule is not read twice", () => {
    const { container } = render(<RuleTerminal rule={RULE} reply={REPLY} />);
    expect(container.querySelectorAll("[aria-hidden]").length).toBeGreaterThan(0);
  });
});
