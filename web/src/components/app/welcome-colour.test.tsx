// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { WelcomeColour, resetWelcomeColour } from "./welcome-colour";

beforeEach(() => { localStorage.clear(); resetWelcomeColour(); document.documentElement.removeAttribute("data-accent"); });
afterEach(cleanup);

describe("WelcomeColour", () => {
  it("offers the colours on a first visit", () => {
    render(<WelcomeColour />);
    expect(screen.getByRole("radiogroup", { name: "Colour" })).toBeDefined();
    for (const name of ["Cream", "Blue", "Purple", "Pink", "Yellow"]) expect(screen.getByRole("radio", { name })).toBeDefined();
  });

  it("applies a colour at once and stays open until the visitor continues", () => {
    render(<WelcomeColour />);
    fireEvent.click(screen.getByRole("radio", { name: "Pink" }));
    expect(document.documentElement.getAttribute("data-accent")).toBe("orchid");
    expect(screen.getByRole("radio", { name: "Pink" }).getAttribute("aria-checked")).toBe("true");
    expect(screen.getByRole("radiogroup", { name: "Colour" })).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(screen.queryByRole("radiogroup", { name: "Colour" })).toBeNull();
    expect(localStorage.getItem("a4t-welcome-colour")).toBe("1");
  });

  it("does not appear for someone who already chose a colour", () => {
    localStorage.setItem("a4t-accent", "volt");
    render(<WelcomeColour />);
    expect(screen.queryByRole("radiogroup", { name: "Colour" })).toBeNull();
  });

  it("does not come back once dismissed", () => {
    localStorage.setItem("a4t-welcome-colour", "1");
    render(<WelcomeColour />);
    expect(screen.queryByRole("radiogroup", { name: "Colour" })).toBeNull();
  });
});
