import { defineConfig } from "@playwright/test";

/**
 * Browser smoke suite. Fully offline: the app talks to ONE local fake
 * (e2e/fake-server.mjs) that plays both Supabase Auth and the Apex4Traders
 * API. No real Supabase, no real backend, no broker, no secrets.
 *
 * The browser is the pre-installed Chromium (never `playwright install`).
 * Override with E2E_CHROMIUM_PATH if it lives elsewhere.
 */
const APP_PORT = 3910;
const FAKE_PORT = 3911;
const APP = `http://127.0.0.1:${APP_PORT}`;
const FAKE = `http://127.0.0.1:${FAKE_PORT}`;

export default defineConfig({
  testDir: "./e2e",
  testMatch: /.*\.e2e\.ts/,
  outputDir: "./node_modules/.e2e-results",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: [["list"]],
  use: {
    baseURL: APP,
    trace: "off",
    launchOptions: {
      executablePath: process.env.E2E_CHROMIUM_PATH ?? "/opt/pw-browsers/chromium",
      args: ["--no-sandbox", "--disable-setuid-sandbox"],
    },
  },
  webServer: [
    {
      command: "node e2e/fake-server.mjs",
      url: `${FAKE}/__health`,
      env: { FAKE_PORT: String(FAKE_PORT) },
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      // The dev server: no build step, and the public env points every
      // outbound call at the fake above.
      command: `npx next dev -p ${APP_PORT} -H 127.0.0.1`,
      url: `${APP}/login`,
      env: {
        NEXT_PUBLIC_SUPABASE_URL: FAKE,
        NEXT_PUBLIC_SUPABASE_ANON_KEY: "e2e-anon-key",
        NEXT_PUBLIC_API_BASE_URL: FAKE,
        NEXT_TELEMETRY_DISABLED: "1",
      },
      reuseExistingServer: false,
      timeout: 180_000,
    },
  ],
});
