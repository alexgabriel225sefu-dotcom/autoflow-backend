import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { PasswordField } from "./password-field";

function Harness() {
  const [v, setV] = useState("");
  return <PasswordField label="Password" value={v} onChange={setV} autoComplete="current-password" />;
}

describe("PasswordField", () => {
  it("is a password input, labelled, with the autocomplete it was given", () => {
    render(<Harness />);
    const input = screen.getByLabelText(/^password$/i) as HTMLInputElement;
    expect(input.type).toBe("password");
    expect(input.autocomplete).toBe("current-password");
  });

  it("toggles the type and aria-pressed, and the field keeps focus", async () => {
    render(<Harness />);
    const input = screen.getByLabelText(/^password$/i) as HTMLInputElement;
    await userEvent.type(input, "hunter22");
    const toggle = screen.getByRole("button", { name: /show password/i });
    expect(toggle.getAttribute("aria-pressed")).toBe("false");

    await userEvent.click(toggle);
    expect(input.type).toBe("text");
    expect(input.value).toBe("hunter22");
    expect(toggle.getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: /hide password/i })).toBe(toggle);
    expect(document.activeElement).toBe(input);

    await userEvent.click(toggle);
    expect(input.type).toBe("password");
    expect(toggle.getAttribute("aria-pressed")).toBe("false");
    expect(document.activeElement).toBe(input);
  });

  it("works from the keyboard", async () => {
    render(<Harness />);
    const input = screen.getByLabelText(/^password$/i) as HTMLInputElement;
    await userEvent.click(input);
    await userEvent.tab();
    await userEvent.keyboard("{Enter}");
    expect(input.type).toBe("text");
  });
});
