import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { DashboardCustomise } from "./dashboard-customise";
import { STORAGE_KEY, useHiddenWidgets } from "@/lib/dashboard-layout";

function Harness() {
  const hidden = useHiddenWidgets();
  return (
    <div>
      <DashboardCustomise hidden={hidden} />
      <p data-testid="hidden">{[...hidden].sort().join(",")}</p>
    </div>
  );
}

beforeEach(() => window.localStorage.clear());
afterEach(cleanup);

describe("DashboardCustomise", () => {
  it("hides a card, remembers it, and shows everything again", () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: /Customise/ }));
    fireEvent.click(screen.getByLabelText("Market chart"));
    expect(screen.getByTestId("hidden").textContent).toBe("market");
    expect(JSON.parse(window.localStorage.getItem(STORAGE_KEY)!)).toEqual(["market"]);
    fireEvent.click(screen.getByRole("button", { name: /Show everything again/ }));
    expect(screen.getByTestId("hidden").textContent).toBe("");
    expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull();
  });
  it("does not offer the approval or the automation card", () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: /Customise/ }));
    expect(screen.queryByLabelText(/approval/i)).toBeNull();
    expect(screen.queryByLabelText(/^Automation/)).toBeNull();
    expect(screen.getByText(/always stay/)).toBeTruthy();
  });
  it("a corrupt stored value shows everything", () => {
    window.localStorage.setItem(STORAGE_KEY, "{broken");
    render(<Harness />);
    expect(screen.getByTestId("hidden").textContent).toBe("");
  });
});
