import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ApiResult } from "@/lib/api";

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>{children}</a>
  ),
}));

import { FirstRunChecklist, firstRunSteps } from "./first-run";

const ok = <T,>(data: T): ApiResult<T> => ({ ok: true, data });
const bad = { ok: false, status: 503, code: "STORE_UNAVAILABLE", message: "down" } as const;

const me = (verified: boolean) => ok({
  user: { userId: "u", email: "a@b.test", emailVerified: verified },
  licence: { state: "active" as const, expiresAt: null, plan: "demo" },
  execution: {},
}) as never;
const ct = (connected: boolean, selected: boolean) => ok({
  connected, accounts: [], liveAllowed: false,
  selected: selected ? { ctid: 1, mode: "demo" as const } : null,
}) as never;
const auto = (state: "stopped" | "running" | "paused") =>
  ok({ state, ruleDocId: null, mode: null, startedAt: null }) as never;
const rules = (states: string[]) =>
  ok({ rules: states.map((s, i) => ({ ruleDocId: `r${i}`, state: s })) }) as never;

describe("first-run checklist", () => {
  it("fresh sign-up: nothing done, each step links to its page", () => {
    render(<FirstRunChecklist me={me(false)} ct={ct(false, false)} auto={auto("stopped")} rules={rules([])} />);
    const card = screen.getByRole("region", { name: /getting started/i });
    expect(card.textContent).toContain("0 of 5 done");
    const hrefs = Object.fromEntries(
      within(card).getAllByRole("link").map((a) => [a.textContent, a.getAttribute("href")]));
    expect(hrefs["Confirm your email"]).toBe("/settings");
    expect(hrefs["Connect cTrader"]).toBe("/connect");
    expect(hrefs["Pick a demo account"]).toBe("/accounts");
    expect(hrefs["Choose a strategy on Trade"]).toBe("/trade");
    expect(hrefs["Press Start"]).toBe("/trade");
  });

  it("checks off exactly the steps the server confirmed", () => {
    const steps = firstRunSteps({
      me: me(true), ct: ct(true, false), auto: auto("stopped"), rules: rules(["draft"]),
    });
    expect(Object.fromEntries(steps.map((s) => [s.id, s.state]))).toEqual({
      email: "done", connect: "done", account: "todo", strategy: "done", start: "todo",
    });
  });

  it("an archived-only rule list does not count as having a strategy", () => {
    const steps = firstRunSteps({
      me: me(true), ct: ct(true, true), auto: auto("stopped"), rules: rules(["archived"]),
    });
    expect(steps.find((s) => s.id === "strategy")!.state).toBe("todo");
  });

  it("a failed read is unknown, never done and never todo", () => {
    const steps = firstRunSteps({ me: bad, ct: ct(true, true), auto: bad, rules: bad });
    expect(steps.map((s) => s.state)).toEqual(["unknown", "done", "done", "unknown", "unknown"]);
    render(<FirstRunChecklist me={bad} ct={ct(true, true)} auto={bad} rules={bad} />);
    expect(screen.getAllByText(/could not check this just now/i).length).toBe(3);
  });

  it("renders nothing while any read has not answered", () => {
    const { container } = render(
      <FirstRunChecklist me={me(true)} ct={undefined} auto={auto("running")} rules={rules(["active"])} />);
    expect(container.firstChild).toBeNull();
  });

  it("disappears when every step is done", () => {
    const { container } = render(
      <FirstRunChecklist me={me(true)} ct={ct(true, true)} auto={auto("running")} rules={rules(["active"])} />);
    expect(container.firstChild).toBeNull();
  });

  it("stays visible while one step is only unknown", () => {
    const { container } = render(
      <FirstRunChecklist me={me(true)} ct={ct(true, true)} auto={auto("running")} rules={bad} />);
    expect(container.firstChild).not.toBeNull();
  });
});
