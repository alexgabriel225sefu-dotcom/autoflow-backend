import { render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { TrustpilotWidget } from "./trustpilot-widget";

afterEach(() => {
  delete process.env.NEXT_PUBLIC_TRUSTPILOT_BUSINESSUNIT_ID;
  delete process.env.NEXT_PUBLIC_TRUSTPILOT_TEMPLATE_ID;
  document.head.querySelectorAll("script[data-trustpilot]").forEach((s) => s.remove());
});

describe("TrustpilotWidget", () => {
  it("renders nothing and loads nothing when it is not configured", () => {
    const { container } = render(<TrustpilotWidget />);
    expect(container.innerHTML).toBe("");
    expect(document.head.querySelector("script[data-trustpilot]")).toBeNull();
  });

  it("renders the TrustBox with a link to the public profile when configured", () => {
    process.env.NEXT_PUBLIC_TRUSTPILOT_BUSINESSUNIT_ID = "5f1a2b3c4d5e6f7a8b9c0d1e";
    process.env.NEXT_PUBLIC_TRUSTPILOT_TEMPLATE_ID = "5419b6a8b0d04a076446a9ad";
    const { container } = render(<TrustpilotWidget />);
    const box = container.querySelector(".trustpilot-widget");
    expect(box?.getAttribute("data-businessunit-id")).toBe("5f1a2b3c4d5e6f7a8b9c0d1e");
    const link = box?.querySelector("a");
    expect(link?.getAttribute("href")).toBe("https://www.trustpilot.com/review/apex4traders.com");
    expect(link?.getAttribute("target")).toBe("_blank");
    expect(link?.getAttribute("rel")).toContain("noopener");
    expect(document.head.querySelector("script[data-trustpilot]")).not.toBeNull();
  });
});
