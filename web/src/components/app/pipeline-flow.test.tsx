import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PipelineFlow } from "./pipeline-flow";

const base = { account: "#41720318 · Demo", accountReady: true, rule: "EURUSD trend", ruleReady: true, running: true, decisions: 3 };

describe("PipelineFlow", () => {
  it("shows the four stages with values the dashboard already reads", () => {
    render(<PipelineFlow {...base} />);
    expect(screen.getByText("#41720318 · Demo")).toBeTruthy();
    expect(screen.getByText("EURUSD trend")).toBeTruthy();
    expect(screen.getByText("Risk Guard")).toBeTruthy();
    expect(screen.getByText("3 recent decisions")).toBeTruthy();
    expect(screen.getByText("Live")).toBeTruthy();
  });

  it("moves light along the links only while running", () => {
    const { container, rerender } = render(<PipelineFlow {...base} />);
    expect(container.querySelectorAll('.pfl-link[data-on="true"]').length).toBe(3);
    rerender(<PipelineFlow {...base} running={false} />);
    expect(container.querySelectorAll('.pfl-link[data-on="true"]').length).toBe(0);
    expect(screen.getByText("Idle")).toBeTruthy();
  });

  it("shows a dash, not a guess, while a read has not answered", () => {
    render(<PipelineFlow account={null} accountReady={false} rule={null} ruleReady={false} running={false} decisions={null} />);
    expect(screen.getAllByText("—").length).toBe(3);
  });
});
