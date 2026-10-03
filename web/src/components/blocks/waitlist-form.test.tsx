/**
 * The only thing the landing page asks anyone to do.
 *
 * The dangerous directions, in order: showing a success the server never
 * gave, losing what somebody typed, and a primary button that looks broken
 * before it is touched. Each is asserted below with its negative case, since
 * "it rendered something" is easy to assert by accident.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const joinWaitlist = vi.fn();

vi.mock("@/lib/api", async (orig) => {
  const actual = await orig<typeof import("@/lib/api")>();
  return {
    ...actual,
    joinWaitlist: (email: string, source: string) => joinWaitlist(email, source),
  };
});

const { WaitlistForm } = await import("./waitlist-form");

const DOWN = {
  ok: false as const, status: 503, code: "STORE_UNAVAILABLE",
  message: "the waitlist is not configured on this deployment",
};

function type(value: string) {
  const input = screen.getByRole("textbox") as HTMLInputElement;
  fireEvent.change(input, { target: { value } });
  return input;
}

beforeEach(() => joinWaitlist.mockReset());

describe("joining", () => {
  it("sends what was typed, with the source it was placed on", async () => {
    joinWaitlist.mockResolvedValue({ ok: true, data: { status: "added" } });
    render(<WaitlistForm source="pricing" />);
    type("Trader@Example.com");
    fireEvent.click(screen.getByRole("button"));
    await waitFor(() =>
      expect(joinWaitlist).toHaveBeenCalledWith("Trader@Example.com", "pricing"));
  });

  it("confirms only after the server said so", async () => {
    let resolve!: (v: unknown) => void;
    joinWaitlist.mockReturnValue(new Promise((r) => { resolve = r; }));
    render(<WaitlistForm />);
    type("a@b.com");
    fireEvent.click(screen.getByRole("button"));
    // In flight: no claim either way.
    await waitFor(() => expect(screen.getByRole("button")).toHaveProperty("disabled", true));
    expect(screen.queryByText(/on the list/i)).toBeNull();
    resolve({ ok: true, data: { status: "added" } });
    await waitFor(() => expect(screen.getByText("You are on the list.")).toBeTruthy());
  });

  it("says something different when the address was already there", async () => {
    joinWaitlist.mockResolvedValue({ ok: true, data: { status: "already" } });
    render(<WaitlistForm />);
    type("a@b.com");
    fireEvent.click(screen.getByRole("button"));
    await waitFor(() =>
      expect(screen.getByText("You are already on the list.")).toBeTruthy());
    expect(screen.queryByText("You are on the list.")).toBeNull();
  });
});

describe("when it fails", () => {
  it("shows the server's own words, not a friendlier invention", async () => {
    joinWaitlist.mockResolvedValue(DOWN);
    render(<WaitlistForm />);
    type("a@b.com");
    fireEvent.click(screen.getByRole("button"));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain(DOWN.message));
  });

  it("claims no success", async () => {
    joinWaitlist.mockResolvedValue(DOWN);
    render(<WaitlistForm />);
    type("a@b.com");
    fireEvent.click(screen.getByRole("button"));
    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
    expect(screen.queryByText(/on the list/i)).toBeNull();
  });

  it("keeps what was typed, so nobody retypes it", async () => {
    joinWaitlist.mockResolvedValue(DOWN);
    render(<WaitlistForm />);
    type("keep.me@example.com");
    fireEvent.click(screen.getByRole("button"));
    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
    expect((screen.getByRole("textbox") as HTMLInputElement).value)
      .toBe("keep.me@example.com");
  });

  it("and lets it be tried again", async () => {
    joinWaitlist.mockResolvedValue(DOWN);
    render(<WaitlistForm />);
    type("a@b.com");
    fireEvent.click(screen.getByRole("button"));
    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
    expect(screen.getByRole("button")).toHaveProperty("disabled", false);
  });
});

describe("the button", () => {
  it("is alive before anything is typed", () => {
    // A disabled primary call to action on first paint reads as broken, and
    // this is the single conversion the page exists for.
    render(<WaitlistForm />);
    expect(screen.getByRole("button")).toHaveProperty("disabled", false);
  });

  it("but an empty submit costs no request", () => {
    render(<WaitlistForm />);
    fireEvent.click(screen.getByRole("button"));
    expect(joinWaitlist).not.toHaveBeenCalled();
  });

  it("and whitespace is not an address either", () => {
    render(<WaitlistForm />);
    type("   ");
    fireEvent.click(screen.getByRole("button"));
    expect(joinWaitlist).not.toHaveBeenCalled();
  });
});

describe("what it promises", () => {
  it("states the one email, and that this release places no live orders", () => {
    render(<WaitlistForm />);
    const note = document.body.textContent ?? "";
    expect(note).toMatch(/one email/i);
    expect(note).toMatch(/no tracking/i);
    expect(note).toMatch(/does not place live orders/i);
  });
});
