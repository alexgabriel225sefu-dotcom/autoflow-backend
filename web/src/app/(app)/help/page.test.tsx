import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { NAV } from "@/components/app/nav";
import { SUPPORT_EMAIL } from "@/lib/support";
import HelpPage from "./page";

describe("help page", () => {
  it("answers the questions a new client has", () => {
    render(<HelpPage />);
    for (const q of [
      /what does demo mean/i,
      /what is ctrader/i,
      /open a ctrader demo account/i,
      /what does each automation level do/i,
      /what does stop do/i,
      /why was a trade refused/i,
      /how does licensing work/i,
    ]) {
      expect(screen.getByText(q), String(q)).toBeTruthy();
    }
  });

  it("mentions the broker minimum lot and makes no profit claim", () => {
    const { container } = render(<HelpPage />);
    const text = container.textContent ?? "";
    expect(text).toMatch(/minimum (lot|order|size)/i);
    expect(text).toMatch(/closes nothing|does not close/i);
    expect(text).not.toMatch(/guarantee[sd]? (profit|return)|risk-free/i);
  });

  it("does not invent a support address", () => {
    const { container } = render(<HelpPage />);
    if (SUPPORT_EMAIL === null) {
      expect(container.querySelector('a[href^="mailto:"]')).toBeNull();
    }
  });
});

describe("navigation of help and live", () => {
  it("lists Help, and keeps Live out of the primary bar with its caveat", () => {
    expect(NAV.some((n) => n.href === "/help")).toBe(true);
    const live = NAV.find((n) => n.href === "/live")!;
    expect(live.primary).toBeFalsy();
    expect(live.group).toBe("more");
    expect(live.note).toMatch(/not available in this release/i);
  });
});
