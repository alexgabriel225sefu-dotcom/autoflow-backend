import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { ProductShowcase } from "./product-showcase";

describe("ProductShowcase", () => {
  it("opens on the setup step and switches parts of the platform", () => {
    render(<ProductShowcase />);
    expect(screen.getByRole("tab", { name: "Set up" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("heading", { level: 3 }).textContent).toBe("Pick an instrument and a strategy.");

    fireEvent.click(screen.getByRole("tab", { name: "Review" }));
    expect(screen.getByRole("tab", { name: "Review" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("heading", { level: 3 }).textContent).toBe("What happened, and when.");
    expect(screen.getByAltText(/journal/i).getAttribute("src")).toBe("/product/journal.webp");
  });

  it("describes every screenshot, so nobody is left with a blank image", () => {
    render(<ProductShowcase />);
    for (const name of ["Set up", "Run", "Review", "Track", "Make it yours"]) {
      fireEvent.click(screen.getByRole("tab", { name }));
      const img = screen.getByRole("img");
      expect(img.getAttribute("alt") ?? "").not.toBe("");
    }
  });
});
