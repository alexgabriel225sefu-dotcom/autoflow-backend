// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { OverviewBand } from "./overview-band";

describe("OverviewBand", () => {
  it("shows a dash, never a zero, for a read that has not answered", () => {
    render(<OverviewBand tiles={[{ label: "Positions", value: null }]} />);
    const region = screen.getByRole("region", { name: "Overview" });
    expect(region.textContent).toContain("—");
    expect(region.textContent).not.toContain("0");
  });

  it("shows a real zero when the broker confirmed none are open", () => {
    render(<OverviewBand tiles={[{ label: "Positions", value: "0", note: "open at your broker" }]} />);
    expect(screen.getByText("0")).toBeDefined();
    expect(screen.getByText("open at your broker")).toBeDefined();
  });

  it("marks the tone so a running state can be coloured by the stylesheet", () => {
    const { container } = render(
      <OverviewBand tiles={[{ label: "State", value: "Running", tone: "long" }]} />,
    );
    expect(container.querySelector('[data-tone="long"]')).not.toBeNull();
  });
});
