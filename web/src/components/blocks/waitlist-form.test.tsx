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
    // Forwards EVERY argument. An earlier version forwarded two, which was
    // written before the third existed and silently dropped it — the test
    // then asserted against a call the component never made.
    joinWaitlist: (...args: unknown[]) => joinWaitlist(...args),
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

/**
 * The question asked after the sign-up, never before it.
 *
 * Which platform somebody trades on decides what this product supports next.
 * It is also not worth losing a sign-up over, so the address is taken first
 * and this is asked of people who have already said yes. Everything below is
 * about that order holding.
 */
describe("the platform question", () => {
  async function joinThen() {
    joinWaitlist.mockResolvedValue({ ok: true, data: { status: "added" } });
    render(<WaitlistForm source="landing" />);
    type("a@b.com");
    fireEvent.click(screen.getByRole("button"));
    await waitFor(() => expect(screen.getByText("You are on the list.")).toBeTruthy());
    joinWaitlist.mockClear();
  }

  it("is not on the form before signing up", () => {
    render(<WaitlistForm />);
    // One field and one button. Anything more is a hurdle in front of the
    // only thing this page asks for.
    expect(screen.queryByLabelText(/trading platform/i)).toBeNull();
    expect(screen.queryByPlaceholderText(/broker/i)).toBeNull();
  });

  it("appears only after the server confirmed the sign-up", async () => {
    await joinThen();
    expect(screen.getByLabelText(/trading platform/i)).toBeTruthy();
  });

  it("sends the answer against the same address", async () => {
    await joinThen();
    fireEvent.change(screen.getByLabelText(/trading platform/i),
                     { target: { value: "mt5" } });
    fireEvent.change(screen.getByLabelText(/^broker$/i),
                     { target: { value: "IC Markets" } });
    fireEvent.click(screen.getByRole("button", { name: /^send$/i }));
    await waitFor(() => expect(joinWaitlist).toHaveBeenCalledWith(
      "a@b.com", "landing", { platform: "mt5", broker: "IC Markets" }));
  });

  it("can be skipped, and skipping sends nothing", async () => {
    await joinThen();
    fireEvent.click(screen.getByRole("button", { name: /skip/i }));
    await waitFor(() => expect(screen.getByText(/noted/i)).toBeTruthy());
    expect(joinWaitlist).not.toHaveBeenCalled();
  });

  it("cannot be sent empty", async () => {
    await joinThen();
    expect(screen.getByRole("button", { name: /^send$/i }))
      .toHaveProperty("disabled", true);
  });

  it("never takes back the confirmation, whatever the answer does", async () => {
    await joinThen();
    joinWaitlist.mockResolvedValue({
      ok: false, status: 503, code: "STORE_UNAVAILABLE", message: "down" });
    fireEvent.change(screen.getByLabelText(/trading platform/i),
                     { target: { value: "mt4" } });
    fireEvent.click(screen.getByRole("button", { name: /^send$/i }));
    await waitFor(() => expect(screen.getByText(/noted/i)).toBeTruthy());
    // The address is already recorded. A failed afterthought must not make
    // somebody think their sign-up did not happen.
    expect(screen.getByText("You are on the list.")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
