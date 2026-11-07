import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { JourneyStrip, journeySteps } from "./journey-strip";
import type { ApiResult, AutomationState, RuleSummary } from "@/lib/api";

const rule = (state: RuleSummary["state"]): RuleSummary => ({
  ruleDocId: "r1", name: "R", state, version: 1, symbols: ["EURUSD"], timeframe: "1h", updatedAt: 0,
});
const rules = (list: RuleSummary[]): ApiResult<{ rules: RuleSummary[] }> => ({ ok: true, data: { rules: list } }) as never;
const auto = (state: AutomationState["state"]): ApiResult<AutomationState> =>
  ({ ok: true, data: { state, ruleDocId: null, mode: null, startedAt: null } }) as never;
const states = (r: Parameters<typeof journeySteps>[0]) => journeySteps(r).map((s) => s.state);

describe("journeySteps", () => {
  it("starts at choosing a strategy when nothing exists yet", () => {
    expect(states({ auto: auto("stopped"), rules: rules([]) })).toEqual(["current", "todo", "todo"]);
  });
  it("moves to starting once a strategy exists", () => {
    expect(states({ auto: auto("stopped"), rules: rules([rule("active")]) })).toEqual(["done", "current", "todo"]);
  });
  it("is watching while it runs", () => {
    expect(states({ auto: auto("running"), rules: rules([rule("active")]) })).toEqual(["done", "done", "current"]);
  });
  it("says unknown, never done, while a read has not answered", () => {
    expect(states({ auto: null, rules: null })).toEqual(["unknown", "unknown", "unknown"]);
  });
  it("names the account type that is selected, not always demo", () => {
    const title = (mode: "demo" | "live" | null) =>
      journeySteps({ auto: auto("stopped"), rules: rules([rule("active")]), mode })[1].title;
    expect(title("demo")).toBe("Start on demo");
    expect(title("live")).toBe("Start on your live account");
    expect(title(null)).toBe("Start automation");
  });
  it("renders three links and marks the current step", () => {
    render(<JourneyStrip auto={auto("stopped")} rules={rules([])} />);
    expect(screen.getAllByRole("link")).toHaveLength(3);
    expect(screen.getByRole("link", { name: /1\. Choose a strategy/ }).getAttribute("aria-current")).toBe("step");
  });
});
