// One local fake for the e2e suite: Supabase Auth + the Apex4Traders API.
// Deterministic, in-memory, no network beyond 127.0.0.1, no secrets.
//
// Test hooks (not part of either real API):
//   GET  /__health   readiness probe
//   GET  /__calls    every request seen, as [{method, path}]
//   POST /__reset    clear the call log
import http from "node:http";

const PORT = Number(process.env.FAKE_PORT || 3911);
const USER = {
  id: "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa",
  aud: "authenticated",
  role: "authenticated",
  email: "trader@example.com",
  email_confirmed_at: "2026-01-01T00:00:00Z",
  app_metadata: {},
  user_metadata: {},
  created_at: "2026-01-01T00:00:00Z",
};
const TOKEN = "e2e-access-token";
const GOOD_EMAIL = "trader@example.com";
const GOOD_PASSWORD = "correct-horse-1";

const session = () => ({
  access_token: TOKEN,
  refresh_token: "e2e-refresh-token",
  token_type: "bearer",
  expires_in: 3600,
  expires_at: Math.floor(Date.now() / 1000) + 3600,
  user: USER,
});

const ACCOUNT = { ctid: 4400123, mode: "demo", label: "Demo 4400123" };
const calls = [];

const api = {
  me: () => ({
    user: { userId: USER.id, email: USER.email, emailVerified: true },
    licence: { state: "none", expiresAt: null, plan: null },
    execution: {
      accountMode: "demo", entitlement: "free_demo", licenceState: "none",
      liveExecutionEnabled: false, planNotice: "Demo only.", canAutomate: true,
      canActivate: true, activationRefusal: null, plan: "free", onTrial: true,
      trialDaysLeft: 12, trialExpiresAt: null, accountAllowance: 1, reason: null,
      message: "Demo account.", badge: "DEMO",
    },
  }),
  "ctrader/status": () => ({
    connected: true, accounts: [ACCOUNT], selected: { ctid: ACCOUNT.ctid, mode: "demo" },
    liveAllowed: false,
  }),
  automation: () => ({
    state: "stopped", ruleDocId: null, mode: null, startedAt: null, level: null,
  }),
  positions: () => ({ connected: true, status: "ok", mode: "demo", positions: [] }),
  orders: () => ({ connected: true, status: "ok", mode: "demo", orders: [] }),
  rules: () => ({ rules: [] }),
  approvals: () => ({ status: "ok", approval: null }),
  notifications: () => ({
    status: "ok", notifications: [], total: 0, unread: 0, hasMore: false,
  }),
  strategies: () => ({
    strategies: [
      { id: "trend_pullback", label: "Trend pullback", version: "1", family: "trend",
        what: "Enters pullbacks inside an established trend.",
        decides: "Buys dips above the 200 average, sells rallies below it.",
        refuses: "Ranging markets and the first hour after a news release.",
        source: "engine" },
      { id: "range_fade", label: "Range fade", version: "1", family: "range",
        what: "Fades the edges of a quiet range.",
        decides: "Sells near the range high and buys near the low.",
        refuses: "Trending markets.", source: "engine" },
    ],
    withheld: [], ruleBuilderId: "rule_builder", presetField: "strategy",
  }),
  symbols: () => ({
    connected: true, status: "ok", mode: "demo",
    symbols: [
      { id: "EURUSD", class: "forex", tradeable: true, reason: null },
      { id: "GBPUSD", class: "forex", tradeable: true, reason: null },
      { id: "XAUUSD", class: "metal", tradeable: true, reason: null },
    ],
  }),
  "trade/min-lot": () => ({ connected: true, status: "unavailable", reason: "not stubbed" }),
  journal: () => ({
    status: "ok", total: 2, limit: 25, offset: 0, hasMore: false,
    entries: [
      { entryId: "j1", kind: "evaluation", status: "hold", ts: 1_780_000_000,
        symbol: "EURUSD", accountId: String(ACCOUNT.ctid), ruleDocId: null,
        correlationId: "c1",
        decision: { verdict: "HOLD", reason: "No entry condition met on EURUSD.",
          conditions: [], executable: false, refusalCode: null, confidence: null } },
      { entryId: "j2", kind: "evaluation", status: "signal", ts: 1_780_000_600,
        symbol: "GBPUSD", accountId: String(ACCOUNT.ctid), ruleDocId: null,
        correlationId: "c2", snapshot: { symbol: "GBPUSD", price: 1.2701 },
        decision: { verdict: "BUY", reason: "Trend pullback conditions met.",
          conditions: [{ id: "trend_up", passed: true, detail: "" }],
          executable: false, refusalCode: null, confidence: 70 } },
    ],
  }),
};

function cors(res, origin) {
  res.setHeader("Access-Control-Allow-Origin", origin || "*");
  res.setHeader("Vary", "Origin");
  res.setHeader("Access-Control-Allow-Credentials", "true");
  res.setHeader("Access-Control-Allow-Headers",
    "authorization, apikey, content-type, x-client-info, x-supabase-api-version");
  res.setHeader("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS");
}

function send(res, status, body) {
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json");
  res.end(JSON.stringify(body));
}

function bearer(req) {
  return (req.headers.authorization || "").replace(/^Bearer\s+/i, "").trim();
}

async function readBody(req) {
  let raw = "";
  for await (const c of req) raw += c;
  try { return raw ? JSON.parse(raw) : {}; } catch { return {}; }
}

const server = http.createServer(async (req, res) => {
  cors(res, req.headers.origin);
  const url = new URL(req.url, `http://127.0.0.1:${PORT}`);
  const path = url.pathname;
  if (req.method === "OPTIONS") { res.statusCode = 204; return res.end(); }
  if (path === "/__health") return send(res, 200, { ok: true });
  if (path === "/__calls") return send(res, 200, calls);
  if (path === "/__reset") { calls.length = 0; return send(res, 200, { ok: true }); }
  calls.push({ method: req.method, path: path + url.search });

  // Supabase Auth
  if (path === "/auth/v1/user") {
    return bearer(req) === TOKEN ? send(res, 200, USER)
      : send(res, 401, { code: 401, msg: "invalid JWT" });
  }
  if (path === "/auth/v1/token") {
    const body = await readBody(req);
    if (url.searchParams.get("grant_type") === "refresh_token") {
      return body.refresh_token === "e2e-refresh-token"
        ? send(res, 200, session())
        : send(res, 400, { code: 400, error_code: "refresh_token_not_found", msg: "Invalid Refresh Token" });
    }
    if (body.email === GOOD_EMAIL && body.password === GOOD_PASSWORD) {
      return send(res, 200, session());
    }
    return send(res, 400, {
      code: 400, error_code: "invalid_credentials", msg: "Invalid login credentials",
    });
  }
  if (path === "/auth/v1/signup") {
    const body = await readBody(req);
    if (body.email === "taken@example.com") {
      return send(res, 422, {
        code: 422, error_code: "user_already_exists", msg: "User already registered",
      });
    }
    // No session: the address still has to be confirmed by email.
    return send(res, 200, { ...USER, email: body.email, email_confirmed_at: null });
  }
  if (path === "/auth/v1/logout") { res.statusCode = 204; return res.end(); }

  // Apex4Traders API
  const m = path.match(/^\/api\/v1\/(.+)$/);
  if (m) {
    if (bearer(req) !== TOKEN) {
      return send(res, 401, { ok: false, error: { code: "AUTH_REQUIRED", message: "Sign in." } });
    }
    const key = m[1];
    if (req.method === "GET" && api[key]) return send(res, 200, { ok: true, ...api[key]() });
    return send(res, 404, { ok: false, error: { code: "NOT_FOUND", message: `no stub for ${key}` } });
  }
  return send(res, 404, { ok: false });
});

server.listen(PORT, "127.0.0.1", () => console.log(`fake server on ${PORT}`));
