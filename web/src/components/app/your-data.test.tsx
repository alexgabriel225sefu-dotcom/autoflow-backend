import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();
const refresh = vi.fn();
const signOut = vi.fn(async () => ({}));
const exportAccount = vi.fn();
const deleteAccount = vi.fn();

vi.mock("next/navigation", () => ({ useRouter: () => ({ push, refresh }) }));
vi.mock("@/lib/supabase/client", () => ({ createClient: () => ({ auth: { signOut: () => signOut() } }) }));
vi.mock("@/lib/api", async (orig) => ({
  ...(await orig<typeof import("@/lib/api")>()),
  exportAccount: () => exportAccount(),
  deleteAccount: (c: string) => deleteAccount(c),
}));

import { YourData } from "./your-data";

beforeEach(() => {
  for (const m of [push, refresh, signOut, exportAccount, deleteAccount]) m.mockReset();
  signOut.mockResolvedValue({});
  URL.createObjectURL = vi.fn(() => "blob:x");
  URL.revokeObjectURL = vi.fn();
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
});

describe("Your data — export", () => {
  it("downloads the JSON and says so", async () => {
    exportAccount.mockResolvedValue({ ok: true, data: { ok: true, exportedAt: "2026-10-29T10:00:00Z", data: { rules: [] } } });
    render(<YourData />);
    fireEvent.click(screen.getByRole("button", { name: /export my data/i }));
    expect((await screen.findByRole("status")).textContent).toMatch(/downloaded/i);
    expect(URL.createObjectURL).toHaveBeenCalledOnce();
  });

  it("shows the calm message when the endpoint is not deployed", async () => {
    exportAccount.mockResolvedValue({ ok: false, status: 404, code: "NOT_DEPLOYED",
      message: "Export is not available on this server yet. Nothing was changed. Please try again later." });
    render(<YourData />);
    fireEvent.click(screen.getByRole("button", { name: /export my data/i }));
    expect((await screen.findByRole("alert")).textContent).toMatch(/not available on this server yet/);
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });
});

describe("Your data — delete", () => {
  it("stays disabled until DELETE is typed exactly", async () => {
    render(<YourData />);
    const btn = screen.getByRole("button", { name: /delete my account/i }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    const box = screen.getByLabelText(/type delete to confirm/i);
    await userEvent.type(box, "delete");
    expect(btn.disabled).toBe(true);
    await userEvent.clear(box);
    await userEvent.type(box, "DELETE");
    expect(btn.disabled).toBe(false);
  });

  it("deletes, signs out and goes to the landing page", async () => {
    deleteAccount.mockResolvedValue({ ok: true, data: { ok: true, deleted: { rules: 3 }, authUserDeleted: true } });
    render(<YourData />);
    await userEvent.type(screen.getByLabelText(/type delete to confirm/i), "DELETE");
    await userEvent.click(screen.getByRole("button", { name: /delete my account/i }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/"));
    expect(deleteAccount).toHaveBeenCalledWith("DELETE");
    expect(signOut).toHaveBeenCalled();
  });

  it("does not sign out or leave when the server refuses", async () => {
    deleteAccount.mockResolvedValue({ ok: false, status: 501, code: "NOT_DEPLOYED",
      message: "Account deletion is not available on this server yet. Nothing was changed. Please try again later." });
    render(<YourData />);
    await userEvent.type(screen.getByLabelText(/type delete to confirm/i), "DELETE");
    await userEvent.click(screen.getByRole("button", { name: /delete my account/i }));
    expect((await screen.findByRole("alert")).textContent).toMatch(/nothing was changed/i);
    expect(signOut).not.toHaveBeenCalled();
    expect(push).not.toHaveBeenCalled();
  });

  it("still leaves if sign-out throws after a successful delete", async () => {
    deleteAccount.mockResolvedValue({ ok: true, data: { ok: true, deleted: {}, authUserDeleted: true } });
    signOut.mockRejectedValue(new Error("no such user"));
    render(<YourData />);
    await userEvent.type(screen.getByLabelText(/type delete to confirm/i), "DELETE");
    await userEvent.click(screen.getByRole("button", { name: /delete my account/i }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/"));
  });
});
