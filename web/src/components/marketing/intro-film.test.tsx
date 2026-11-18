import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { IntroFilm } from "./intro-film";

const KEY = "a4t-intro-seen";

function setSearch(search: string) {
  window.history.replaceState({}, "", `/${search}`);
}

describe("IntroFilm", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    setSearch("");
  });
  afterEach(() => {
    vi.useRealTimers();
    document.documentElement.classList.remove("a4t-intro-lock");
  });

  it("plays on a first visit, labelled as an example, with a way out", () => {
    render(<IntroFilm />);
    expect(screen.getByTestId("intro-film")).toBeTruthy();
    expect(screen.getByRole("button", { name: /skip intro/i })).toBeTruthy();
    expect(screen.getByText(/example rule · demo only/i)).toBeTruthy();
    expect(document.documentElement.classList.contains("a4t-intro-lock")).toBe(true);
  });

  it("makes no claim about results", () => {
    const { container } = render(<IntroFilm />);
    const text = (container.textContent ?? "").toLowerCase();
    for (const word of ["profit", "win", "earn", "guarantee", "%  return", "money"]) {
      expect(text.includes(word)).toBe(false);
    }
  });

  it("skips on the button, remembers it for the session and unlocks the page", () => {
    render(<IntroFilm />);
    fireEvent.click(screen.getByRole("button", { name: /skip intro/i }));
    expect(screen.queryByTestId("intro-film")).toBeNull();
    expect(window.sessionStorage.getItem(KEY)).toBe("1");
    expect(document.documentElement.classList.contains("a4t-intro-lock")).toBe(false);
  });

  it("skips on Escape", () => {
    render(<IntroFilm />);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByTestId("intro-film")).toBeNull();
  });

  it("ends by itself after its timeline", () => {
    vi.useFakeTimers();
    render(<IntroFilm />);
    expect(screen.getByTestId("intro-film")).toBeTruthy();
    act(() => {
      vi.advanceTimersByTime(7700);
    });
    expect(screen.queryByTestId("intro-film")).toBeNull();
  });

  it("does not play again in the same session", () => {
    window.sessionStorage.setItem(KEY, "1");
    render(<IntroFilm />);
    expect(screen.queryByTestId("intro-film")).toBeNull();
  });

  it("does not play with ?intro=0", () => {
    setSearch("?intro=0");
    render(<IntroFilm />);
    expect(screen.queryByTestId("intro-film")).toBeNull();
  });

  it("does not play for a visitor who asked for reduced motion", () => {
    const original = window.matchMedia;
    window.matchMedia = ((q: string) => ({
      matches: q.includes("prefers-reduced-motion"),
      media: q,
      addEventListener() {},
      removeEventListener() {},
      addListener() {},
      removeListener() {},
      dispatchEvent: () => false,
      onchange: null,
    })) as unknown as typeof window.matchMedia;
    try {
      render(<IntroFilm />);
      expect(screen.queryByTestId("intro-film")).toBeNull();
    } finally {
      window.matchMedia = original;
    }
  });
});
