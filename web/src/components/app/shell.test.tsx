/**
 * The shell's navigation contract.
 *
 * The defect this guards against shipped once: the shell was a single
 * horizontally scrolling strip which, measured at 390px, showed 135px of a
 * 599px list. One destination out of eight was on screen, with no overflow
 * menu, no bottom bar and no scroll affordance — and because the page itself
 * did not overflow, nothing hinted the other seven existed.
 *
 * So the assertions below are about REACHABILITY, not about layout. A route
 * that exists on disk but is in no menu is unreachable however pretty the
 * menu is, which is why the first test reads the filesystem.
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();
let pathname = "/dashboard";

vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
  useRouter: () => ({ push, refresh: vi.fn() }),
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>{children}</a>
  ),
}));

vi.mock("@/lib/supabase/client", () => ({
  createClient: () => ({ auth: { signOut: vi.fn(async () => ({})) } }),
}));

vi.mock("@/lib/api", async (orig) => {
  const actual = await orig<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: vi.fn(async (path: string) => {
      if (path.startsWith("notifications")) {
        return { ok: true, data: { status: "ok", notifications: [], total: 0, unread: 3, hasMore: false } };
      }
      if (path === "me") {
        return { ok: true, data: {
          user: { userId: "u1", email: "trader@example.test", emailVerified: true },
          licence: { state: "active", expiresAt: null, plan: "demo" },
        } };
      }
      if (path === "accounts") {
        return { ok: true, data: {
          connected: true, accounts: [{ ctid: 501, mode: "demo" }],
          selected: { ctid: 501, mode: "demo" }, liveAllowed: false,
        } };
      }
      if (path === "automation") {
        return { ok: true, data: { state: "running", ruleDocId: "r1", mode: "demo", startedAt: 0 } };
      }
      return { ok: false, status: 404, code: "NOT_FOUND", message: "no stub" };
    }),
  };
});

import { AppShell } from "./shell";
import { NAV, PRIMARY, SECONDARY, isActive, titleFor } from "./nav";

afterEach(() => { pathname = "/dashboard"; vi.clearAllMocks(); });

const APP_DIR = join(__dirname, "..", "..", "app", "(app)");

/** Every route under app/(app) that is a page, as a URL path. */
function routesOnDisk(dir = APP_DIR, prefix = ""): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      out.push(...routesOnDisk(full, `${prefix}/${entry}`));
    } else if (entry === "page.tsx") {
      out.push(prefix || "/");
    }
  }
  return out;
}

describe("navigation model", () => {
  it("every page under app/(app) is reachable from a menu", () => {
    // Dynamic and nested routes are reached from their parent, not from the
    // nav — /rules/[id] is opened from the rules list.
    const top = routesOnDisk()
      .filter((r) => !r.includes("[") && r.split("/").filter(Boolean).length === 1);
    const known = new Set(NAV.map((n) => n.href));
    // /connect is reached from the account chip and from every not-connected
    // state, which the status bar and ReadPanel both link to.
    known.add("/connect");
    known.add("/license");
    for (const r of top) {
      expect(known.has(r), `${r} exists on disk but is in no menu`).toBe(true);
    }
  });

  it("the primary bar is small enough for a phone and the rest is not dropped", () => {
    expect(PRIMARY.length).toBeLessThanOrEqual(4);
    // Nothing may be lost between the two lists.
    expect([...PRIMARY, ...SECONDARY].map((n) => n.href).sort())
      .toEqual(NAV.map((n) => n.href).sort());
  });

  it("isActive matches a section and its children, not a prefix by accident", () => {
    expect(isActive("/rules", "/rules")).toBe(true);
    expect(isActive("/rules/abc", "/rules")).toBe(true);
    expect(isActive("/rules", "/orders")).toBe(false);
    // "/orders" must not light up for "/ordersomething".
    expect(isActive("/ordersomething", "/orders")).toBe(false);
  });

  it("every destination has a title, so the top bar always says where you are", () => {
    for (const n of NAV) expect(titleFor(n.href)).toBe(n.label);
    expect(titleFor("/connect")).toBe("Connect cTrader");
  });
});

describe("application shell", () => {
  it("renders the sidebar, the bottom bar, and the whole of NAV in each", () => {
    render(<AppShell><p>page</p></AppShell>);

    const sidebar = document.querySelector("aside.side")!;
    for (const n of NAV) {
      expect(
        within(sidebar as HTMLElement).getByRole("link", { name: new RegExp(n.label) }),
        `${n.label} missing from the sidebar`,
      ).toBeDefined();
    }

    const bottom = screen.getByRole("navigation", { name: "Primary" });
    for (const n of PRIMARY) {
      expect(within(bottom).getByRole("link", { name: new RegExp(n.label) })).toBeDefined();
    }
    // The overflow control is the promise that the other four still exist.
    expect(within(bottom).getByRole("button", { name: /More destinations/ })).toBeDefined();
  });

  it("the More drawer exposes EVERY destination, not only the overflow", () => {
    render(<AppShell><p>page</p></AppShell>);
    fireEvent.click(screen.getByRole("button", { name: /More destinations/ }));

    const drawer = screen.getByRole("dialog", { name: /More destinations/ });
    for (const n of NAV) {
      expect(
        within(drawer).getByRole("link", { name: new RegExp(n.label) }),
        `${n.label} is not reachable from the drawer`,
      ).toBeDefined();
    }
    // Signing out must not require finding the desktop sidebar.
    expect(within(drawer).getByRole("button", { name: /Sign out/ })).toBeDefined();
  });

  it("the drawer is a modal dialog and closes on Escape", () => {
    render(<AppShell><p>page</p></AppShell>);
    fireEvent.click(screen.getByRole("button", { name: /More destinations/ }));
    expect(screen.queryByRole("dialog")).not.toBeNull();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("the user menu is on every screen and reaches settings, licence and sign out", () => {
    render(<AppShell><p>page</p></AppShell>);
    fireEvent.click(screen.getByRole("button", { name: /Account|trader@example/ }));
    const menu = screen.getByRole("menu");
    expect(within(menu).getByRole("menuitem", { name: "Settings" })).toBeDefined();
    expect(within(menu).getByRole("menuitem", { name: "Licence" })).toBeDefined();
    expect(within(menu).getByRole("menuitem", { name: /Sign out/ })).toBeDefined();
  });

  it("the status strip states the account, the mode and the automation state", async () => {
    render(<AppShell><p>page</p></AppShell>);
    const strip = await screen.findByRole("status", { name: "Platform status" });
    expect(within(strip).getByText("DEMO")).toBeDefined();
    expect(within(strip).getByText("#501")).toBeDefined();
    expect(within(strip).getByText("RUNNING")).toBeDefined();
    // Demo-only is a property of the release, stated on every screen.
    expect(within(strip).getByText(/Demo/)).toBeDefined();
  });

  it("marks the active destination in both menus", () => {
    pathname = "/journal";
    render(<AppShell><p>page</p></AppShell>);
    const active = [...document.querySelectorAll('[data-active="true"]')]
      .map((e) => (e as HTMLAnchorElement).getAttribute("href"));
    expect(active).toContain("/journal");
    expect(active).not.toContain("/dashboard");
  });
});

describe("stylesheet obligations", () => {
  const CSS = readFileSync(join(__dirname, "..", "..", "app", "globals.css"), "utf8");

  it("honours prefers-reduced-motion", () => {
    expect(CSS).toContain("prefers-reduced-motion: reduce");
    // Not just present — it has to actually stop the animations.
    const block = CSS.slice(CSS.indexOf("prefers-reduced-motion"));
    expect(block).toContain("animation-duration");
    expect(block).toContain("transition-duration");
  });

  it("gives keyboard users a visible focus ring", () => {
    expect(CSS).toContain(":focus-visible");
    expect(CSS).toMatch(/:focus-visible\s*\{[^}]*outline:/);
  });

  it("declares a type scale and a spacing scale rather than loose literals", () => {
    for (const t of ["--fs-sm", "--fs-md", "--fs-lg", "--sp-2", "--sp-4"]) {
      expect(CSS, `${t} is not declared`).toContain(t);
    }
  });

  it("targets touch-sized controls", () => {
    // 44px is the smallest reliable touch target; the bottom bar and the
    // drawer links are the ones a thumb actually uses.
    expect(CSS).toMatch(/\.bottomnav a, \.bottomnav button \{[^}]*min-height: 44px/);
  });
});
