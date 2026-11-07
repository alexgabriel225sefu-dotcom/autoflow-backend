import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ProductGuide } from "./product-guide";

describe("ProductGuide", () => {
  it("explains three steps in plain words, each with a real screenshot", () => {
    render(<ProductGuide />);
    expect(screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent)).toEqual([
      "Choose how you want to trade",
      "Start on a demo account",
      "See every decision and why",
    ]);
    const imgs = screen.getAllByRole("img");
    expect(imgs).toHaveLength(3);
    for (const img of imgs) expect((img.getAttribute("alt") ?? "").length).toBeGreaterThan(10);
  });

  it("makes no claim about results", () => {
    const { container } = render(<ProductGuide />);
    expect(container.textContent ?? "").not.toMatch(/profit|return|guarantee/i);
  });
});
