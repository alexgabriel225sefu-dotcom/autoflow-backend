import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>{children}</a>
  ),
}));

import AppError from "./(app)/error";
import RootError from "./error";
import GlobalError from "./global-error";
import NotFound from "./not-found";
import Loading from "./loading";
import AppLoading from "./(app)/loading";

const leaky = Object.assign(new Error("SELECT * FROM secrets; at /srv/app/db.ts:41"), {
  digest: "abc123",
});

describe("route states", () => {
  it.each([
    ["(app) error", () => <AppError error={leaky} retry={() => {}} />],
    ["root error", () => <RootError error={leaky} retry={() => {}} />],
    ["global error", () => <GlobalError error={leaky} retry={() => {}} />],
  ])("%s offers a way back and leaks nothing", (_n, ui) => {
    // global-error renders <html>; render into the document element's body.
    const { container } = render(ui(), { container: document.body.appendChild(document.createElement("div")) });
    const text = container.textContent ?? "";
    expect(text).not.toMatch(/SELECT|secrets|\/srv\/app|db\.ts/);
    expect(text).toContain("abc123");
    expect(screen.getAllByRole("link", { name: /dashboard/i })[0].getAttribute("href")).toBe("/dashboard");
    expect(screen.getAllByRole("button", { name: /try again/i }).length).toBeGreaterThan(0);
  });

  it("try again calls retry", () => {
    const retry = vi.fn();
    render(<AppError error={new Error("x")} retry={retry} />);
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(retry).toHaveBeenCalledOnce();
  });

  it("not found links back to the dashboard", () => {
    render(<NotFound />);
    expect(screen.getByRole("heading", { name: /not found/i })).toBeTruthy();
    expect(screen.getByRole("link", { name: /dashboard/i }).getAttribute("href")).toBe("/dashboard");
  });

  it("loading states announce themselves", () => {
    render(<Loading />);
    render(<AppLoading />);
    expect(screen.getAllByRole("status").length).toBe(2);
  });
});
