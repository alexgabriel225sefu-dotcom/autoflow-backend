import { expect, test, type BrowserContext, type Page } from "@playwright/test";

const FAKE = "http://127.0.0.1:3911";
const APP = "http://127.0.0.1:3910";

/** The session cookie @supabase/ssr reads: sb-<first host label>-auth-token. */
async function signIn(context: BrowserContext) {
  const session = {
    access_token: "e2e-access-token",
    refresh_token: "e2e-refresh-token",
    token_type: "bearer",
    expires_in: 3600,
    expires_at: Math.floor(Date.now() / 1000) + 3600,
    user: {
      id: "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa", aud: "authenticated",
      role: "authenticated", email: "trader@example.com",
      email_confirmed_at: "2026-01-01T00:00:00Z", app_metadata: {}, user_metadata: {},
      created_at: "2026-01-01T00:00:00Z",
    },
  };
  const value = "base64-" + Buffer.from(JSON.stringify(session)).toString("base64url");
  await context.addCookies([
    { name: "sb-127-auth-token", value, url: APP },
  ]);
}

async function calls(page: Page): Promise<{ method: string; path: string }[]> {
  const r = await page.request.get(`${FAKE}/__calls`);
  return r.json();
}

test.beforeEach(async ({ page }) => {
  await page.request.post(`${FAKE}/__reset`);
});

test.describe("public pages", () => {
  test("landing shows the cTrader partner and two Coming soon cards", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Trade like you planned");
    const partners = page.locator("#partners");
    await expect(partners.getByAltText("cTrader")).toBeVisible();
    await expect(partners.getByText("Available now")).toHaveCount(1);
    await expect(partners.getByText("Coming soon")).toHaveCount(2);
  });

  for (const [path, heading] of [
    ["/terms", /terms/i], ["/privacy", /privacy/i],
    ["/refunds", /refund/i], ["/tax", /tax/i],
  ] as const) {
    test(`legal page ${path} loads`, async ({ page }) => {
      const res = await page.goto(path);
      expect(res?.status()).toBe(200);
      await expect(page.getByRole("heading", { level: 1 })).toContainText(heading);
    });
  }
});

test.describe("auth forms", () => {
  test("sign-up validates before it submits", async ({ page }) => {
    await page.goto("/signup");
    const email = page.getByLabel("Email");
    const password = page.getByLabel("Password");
    await page.getByRole("button", { name: "Create account" }).click();
    expect(await email.evaluate((e: HTMLInputElement) => e.validity.valueMissing)).toBe(true);

    await email.fill("not-an-email");
    await password.fill("longenough1");
    await page.getByRole("button", { name: "Create account" }).click();
    expect(await email.evaluate((e: HTMLInputElement) => e.validity.typeMismatch)).toBe(true);

    await email.fill("new@example.com");
    await password.fill("short");
    await page.getByRole("button", { name: "Create account" }).click();
    expect(await password.evaluate((e: HTMLInputElement) => e.validity.tooShort)).toBe(true);

    // None of the invalid attempts reached the auth server.
    expect((await calls(page)).filter((c) => c.path.includes("/auth/v1/signup"))).toHaveLength(0);
  });

  test("sign-up shows the server's refusal, then the confirm-email screen", async ({ page }) => {
    await page.goto("/signup");
    await page.getByLabel("Email").fill("taken@example.com");
    await page.getByLabel("Password").fill("longenough1");
    await page.getByRole("button", { name: "Create account" }).click();
    await expect(page.locator(".notice-error")).toContainText("User already registered");

    await page.getByLabel("Email").fill("new@example.com");
    await page.getByRole("button", { name: "Create account" }).click();
    await expect(page.getByText("Check your email.")).toBeVisible();
  });

  test("login rejects bad credentials with the server's message", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel("Email").fill("trader@example.com");
    await page.getByLabel("Password").fill("wrong-password");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.locator(".notice-error")).toContainText("Invalid login credentials");
    await expect(page).toHaveURL(/\/login/);
  });

  test("login with good credentials lands on the dashboard", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel("Email").fill("trader@example.com");
    await page.getByLabel("Password").fill("correct-horse-1");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).toHaveURL(/\/dashboard/);
  });
});

test.describe("signed out", () => {
  for (const path of ["/dashboard", "/trade", "/journal", "/rules", "/settings"]) {
    test(`${path} redirects to login and remembers where you were going`, async ({ page }) => {
      await page.goto(path);
      await expect(page).toHaveURL(/\/login\?next=/);
      expect(decodeURIComponent(new URL(page.url()).searchParams.get("next") ?? "")).toBe(path);
    });
  }
});

test.describe("signed in (mocked API)", () => {
  test.beforeEach(async ({ context }) => { await signIn(context); });

  test("dashboard shows the selected demo account", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/dashboard/);
    await expect(page.getByText("#4400123").first()).toBeVisible();
    await expect(page.getByText("Demo account").first()).toBeVisible();
  });

  test("trade: choose instrument and strategy, Start asks for confirmation, nothing is sent", async ({ page }) => {
    await page.goto("/trade");
    await page.getByRole("radio", { name: "EURUSD" }).click();
    await expect(page.getByRole("radio", { name: "EURUSD" })).toHaveAttribute("aria-checked", "true");

    const strategy = page.getByRole("radiogroup", { name: "Strategy" })
      .getByRole("radio", { name: /Trend pullback/ });
    await strategy.click();
    await expect(strategy).toHaveAttribute("aria-checked", "true");

    await page.getByRole("radiogroup", { name: "Who acts on a setup" })
      .getByRole("radio").first().click();

    await page.getByRole("button", { name: "Start on demo" }).click();
    await expect(page.getByText("Start on demo account #4400123?")).toBeVisible();

    // Back out. The API is a fake, and no write must have been attempted.
    await page.getByRole("button", { name: "Cancel" }).click();
    const writes = (await calls(page)).filter((c) => c.method !== "GET" && c.path.startsWith("/api/"));
    expect(writes).toEqual([]);
  });

  test("journal renders the entries the API returned", async ({ page }) => {
    await page.goto("/journal");
    await expect(page.getByRole("heading", { name: "Journal" })).toBeVisible();
    await expect(page.getByText("2 entries")).toBeVisible();
    await expect(page.getByText("No entry condition met on EURUSD.")).toBeVisible();
    await expect(page.getByText("Signal only — nothing placed, you trade it")).toBeVisible();
  });
});
