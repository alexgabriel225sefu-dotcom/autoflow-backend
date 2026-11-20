/**
 * The new-rule page, end to end through the browser-side code: pick who acts on
 * a setup, save, and prove the choice is what was sent.
 *
 * A QA pass on the deployed site reported that clicking "Approval Required"
 * left "Full Automation" pressed. The control's own unit test passes, so this
 * test goes through the real page: its state, its rule sentence and its save.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ApiResult } from "@/lib/api";

const calls: { path: string; init?: { method?: string; body?: Record<string, unknown> } }[] = [];
const pushed: string[] = [];
const CONDITIONS = {
  rsi: {
    id: "rsi", doc: "RSI against a threshold.", impliesDirection: true,
    params: {
      period: { type: "int", default: 14, choices: null, min: 2, max: 200, required: true },
      relation: { type: "str", default: "below", choices: ["above", "below"], min: null, max: null, required: true },
      value: { type: "float", default: 30, choices: null, min: 0, max: 100, required: true },
    },
  },
};

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: (p: string) => pushed.push(p), refresh: vi.fn() }),
  usePathname: () => "/rules/new",
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) =>
    <a href={href} {...rest}>{children}</a>,
}));
vi.mock("@/lib/api", async (orig) => {
  const actual = await orig<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: vi.fn(async (path: string, init?: { method?: string; body?: Record<string, unknown> }) => {
      calls.push({ path, init });
      if (path === "conditions") return { ok: true, status: 200, data: { conditions: CONDITIONS } } as ApiResult<unknown>;
      if (path === "rules" && init?.method === "POST") {
        return { ok: true, status: 201, data: { rule: { ruleDocId: "r1" } } } as ApiResult<unknown>;
      }
      return { ok: false, status: 404, code: "NOT_FOUND", message: "no stub" } as ApiResult<unknown>;
    }),
  };
});

import NewRulePage from "./page";

beforeEach(() => { calls.length = 0; pushed.length = 0; });
afterEach(() => cleanup());

const pressed = (name: string) =>
  screen.getByRole("button", { name }).getAttribute("aria-pressed");

async function mount() {
  render(<NewRulePage />);
  await waitFor(() => expect(screen.queryByRole("button", { name: "Approval Required" })).not.toBeNull());
}

describe("new rule page — who acts on a setup", () => {
  // WAS "starts on Full Automation". A level nobody chose is a rule that
  // places orders without asking, so a new rule starts with NONE selected and
  // cannot be saved until one is picked. Stored rules that never said still
  // read back as Full Automation (see rule-form.test), because that is what
  // they have always run at.
  it("starts with no level chosen, and says it must be", async () => {
    await mount();
    expect(pressed("Full Automation")).toBe("false");
    expect(pressed("Approval Required")).toBe("false");
    expect(pressed("Signals Only")).toBe("false");
    expect(document.body.textContent).toContain("must be picked before the rule can be saved");
  });

  it("cannot be saved until a level is chosen, and then can", async () => {
    await mount();
    const save = () => screen.getByRole("button", { name: /Save draft/ }) as HTMLButtonElement;
    expect(save().disabled).toBe(true);
    expect(document.body.textContent).toContain("before saving");
    fireEvent.click(screen.getByRole("button", { name: "Signals Only" }));
    expect(save().disabled).toBe(false);
  });

  it("clicking Approval Required moves the selection, and ONLY one is pressed", async () => {
    await mount();
    fireEvent.click(screen.getByRole("button", { name: "Approval Required" }));
    expect(pressed("Approval Required")).toBe("true");
    expect(pressed("Full Automation")).toBe("false");
    expect(pressed("Signals Only")).toBe("false");
  });

  it("the selection survives moving to another step and back", async () => {
    await mount();
    fireEvent.click(screen.getByRole("button", { name: "Approval Required" }));
    const rail = within(screen.getByRole("navigation", { name: "Rule sections" }));
    fireEvent.click(rail.getByRole("button", { name: /Entry/ }));
    fireEvent.click(rail.getByRole("button", { name: /Market/ }));
    expect(pressed("Approval Required")).toBe("true");
  });

  it("the rule sentence on the page says it", async () => {
    await mount();
    fireEvent.click(screen.getByRole("button", { name: "Approval Required" }));
    // Reviewing every field shows the level in the terms table.
    fireEvent.click(within(screen.getByRole("navigation", { name: "Rule sections" }))
      .getByRole("button", { name: /Review/ }));
    expect(document.body.textContent).toContain("When a setup appears");
    expect(document.body.textContent).toContain("Approval Required");
  });

  it("saving sends automationLevel: approval", async () => {
    await mount();
    fireEvent.click(screen.getByRole("button", { name: "Approval Required" }));
    fireEvent.click(screen.getByRole("button", { name: /Save draft/ }));
    await waitFor(() => expect(calls.some((c) => c.path === "rules" && c.init?.method === "POST")).toBe(true));
    const post = calls.find((c) => c.path === "rules" && c.init?.method === "POST")!;
    expect(post.init?.body?.automationLevel).toBe("approval");
  });
});


describe("new rule page — loading ends", () => {
  it("a failed condition load is an error with Retry, and Retry loads the form", async () => {
    let fail = true;
    const { api } = await import("@/lib/api");
    (api as unknown as ReturnType<typeof vi.fn>).mockImplementation(async (path: string) => {
      calls.push({ path });
      if (path === "conditions") {
        return fail
          ? { ok: false, status: 0, code: "AUTH_UNAVAILABLE", message: "Your session could not be confirmed in time." }
          : { ok: true, status: 200, data: { conditions: CONDITIONS } };
      }
      return { ok: false, status: 404, code: "NOT_FOUND", message: "no stub" };
    });
    render(<NewRulePage />);
    await waitFor(() => expect(document.body.textContent).toContain("AUTH_UNAVAILABLE"));
    expect(screen.queryByRole("button", { name: "Approval Required" })).toBeNull();
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: /retry|try again/i }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Approval Required" })).not.toBeNull());
  });
});
