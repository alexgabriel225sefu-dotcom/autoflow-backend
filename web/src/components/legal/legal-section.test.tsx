import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { afterEach, describe, expect, it } from "vitest";
import { LegalSection, LegalSections } from "./legal-section";
import { ReadingProgress, readingProgress } from "./reading-progress";

afterEach(cleanup);

const doc = (
  <LegalSections>
    <LegalSection>
      <h2>1. First</h2>
      <p>Alpha body text.</p>
    </LegalSection>
    <LegalSection>
      <h2>2. Second</h2>
      <p>Beta body text [TO BE CONFIRMED].</p>
    </LegalSection>
    <LegalSection>
      <h2>3. Third</h2>
      <p>Gamma body text.</p>
    </LegalSection>
  </LegalSections>
);

describe("readingProgress", () => {
  it("is 0 at the top and 1 at the end", () => {
    expect(readingProgress(0, 2000, 800)).toBe(0);
    expect(readingProgress(1200, 2000, 800)).toBe(1);
  });
  it("is proportional in between", () => {
    expect(readingProgress(600, 2000, 800)).toBeCloseTo(0.5);
  });
  it("clamps overscroll and treats a short page as fully read", () => {
    expect(readingProgress(-50, 2000, 800)).toBe(0);
    expect(readingProgress(5000, 2000, 800)).toBe(1);
    expect(readingProgress(0, 600, 800)).toBe(1);
  });
  it("counts sub-pixel rounding at the bottom as 100%", () => {
    expect(readingProgress(1199.5, 2000, 800)).toBe(1);
  });
});

describe("ReadingProgress", () => {
  it("is a labelled progressbar that is not focusable and reaches 100", async () => {
    const el = document.documentElement;
    Object.defineProperty(el, "scrollHeight", { configurable: true, value: 2000 });
    Object.defineProperty(el, "clientHeight", { configurable: true, value: 800 });
    render(<ReadingProgress />);
    const bar = screen.getByRole("progressbar", { name: "Reading progress" });
    expect(bar.getAttribute("aria-valuemin")).toBe("0");
    expect(bar.getAttribute("aria-valuemax")).toBe("100");
    expect(bar.hasAttribute("tabindex")).toBe(false);
    expect(bar.getAttribute("aria-valuenow")).toBe("0");

    Object.defineProperty(window, "scrollY", { configurable: true, value: 1200 });
    act(() => {
      window.dispatchEvent(new Event("scroll"));
    });
    await waitFor(() => expect(bar.getAttribute("aria-valuenow")).toBe("100"));
    Object.defineProperty(window, "scrollY", { configurable: true, value: 0 });
  });
});

describe("LegalSections", () => {
  it("server-renders every word, with every section open", () => {
    const html = renderToString(doc);
    for (const w of ["Alpha body text.", "Beta body text [TO BE CONFIRMED].", "Gamma body text.", "2. Second"]) {
      expect(html).toContain(w);
    }
    expect(html).not.toContain("hidden");
  });

  it("opens only the first section once hydrated, with the text still in the DOM", () => {
    render(doc);
    const buttons = screen.getAllByRole("button", { name: /^\d\./ });
    expect(buttons.map((b) => b.getAttribute("aria-expanded"))).toEqual(["true", "false", "false"]);
    expect(screen.getByText("Beta body text [TO BE CONFIRMED].")).toBeTruthy();
    expect(screen.getByText("Gamma body text.")).toBeTruthy();
  });

  it("links each button to its panel with aria-controls", () => {
    render(doc);
    const btn = screen.getByRole("button", { name: /2\. Second/ });
    const panel = document.getElementById(btn.getAttribute("aria-controls")!);
    expect(panel).not.toBeNull();
    expect(panel!.textContent).toContain("Beta body text");
  });

  it("toggles a section and its aria state", () => {
    render(doc);
    const btn = screen.getByRole("button", { name: /2\. Second/ });
    fireEvent.click(btn);
    expect(btn.getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(btn);
    expect(btn.getAttribute("aria-expanded")).toBe("false");
  });

  it("expands and collapses everything", () => {
    render(doc);
    fireEvent.click(screen.getByRole("button", { name: "Expand all" }));
    const states = () =>
      screen.getAllByRole("button", { name: /^\d\./ }).map((b) => b.getAttribute("aria-expanded"));
    expect(states()).toEqual(["true", "true", "true"]);
    expect((screen.getByRole("button", { name: "Expand all" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Collapse all" }));
    expect(states()).toEqual(["false", "false", "false"]);
    expect(screen.getByText("Alpha body text.")).toBeTruthy();
  });

  it("marks a settled collapsed body hidden=until-found so find-in-page can reach it", async () => {
    render(doc);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 300));
    });
    const panel = screen.getByText("Gamma body text.").closest("[role=region]")!;
    expect(panel.getAttribute("hidden")).toBe("until-found");
    expect(screen.getByText("Alpha body text.").closest("[role=region]")!.hasAttribute("hidden")).toBe(false);
  });
});
