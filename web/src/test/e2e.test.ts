/**
 * The main flow, end to end, against the REAL backend.
 *
 * A Python child process starts the actual Apex4Traders server — the same
 * router, ownership checks, licence store, rule store, journal and cTrader
 * link that ship. Only Supabase is stubbed, because this test has no Supabase
 * project to reach. Everything the frontend sends travels over a real socket
 * and everything it reads is the backend's own answer.
 *
 * This is the test that would catch the class of bug no mock can: the day the
 * client and the server disagree about a field name, a status code or the
 * shape of a refusal.
 */
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import path from "node:path";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";

let proc: ChildProcessWithoutNullStreams;
let port = 0;
let who = "alice";
let api: typeof import("../lib/api").api;

vi.mock("../lib/supabase/client", () => ({
  createClient: () => ({
    auth: { getSession: async () => ({ data: { session: { access_token: who } } }) },
  }),
}));

function seed(cmd: string) {
  return new Promise<void>((resolve, reject) => {
    const onLine = (buf: Buffer) => {
      const line = buf.toString().trim().split("\n").pop() ?? "";
      if (line.includes('"ok"')) {
        proc.stdout.off("data", onLine);
        JSON.parse(line).ok ? resolve() : reject(new Error(line));
      }
    };
    proc.stdout.on("data", onLine);
    proc.stdin.write(`${cmd}\n`);
  });
}

beforeAll(async () => {
  const script = path.resolve(__dirname, "backend_fixture.py");
  proc = spawn("python3", ["-u", script], { stdio: ["pipe", "pipe", "pipe"] });
  await new Promise<void>((resolve, reject) => {
    let buf = "";
    const t = setTimeout(() => reject(new Error(`backend did not start: ${buf}`)), 90_000);
    proc.stdout.on("data", (d) => {
      buf += d.toString();
      const m = buf.match(/\{"port":\s*(\d+)\}/);
      if (m) port = Number(m[1]);
      if (buf.includes("READY") && port) { clearTimeout(t); resolve(); }
    });
    proc.stderr.on("data", (d) => { buf += d.toString(); });
    proc.on("exit", (c) => { clearTimeout(t); reject(new Error(`exited ${c}: ${buf}`)); });
  });
  process.env.NEXT_PUBLIC_API_BASE_URL = `http://127.0.0.1:${port}`;
  ({ api } = await import("../lib/api"));
}, 120_000);

afterAll(() => { proc?.stdin.write("quit\n"); proc?.kill(); });

// Reset between tests. Without this, a test that fails midway leaves `who`
// set to whoever it was impersonating, and every later test runs as that
// user — turning one real failure into three misleading ones.
afterEach(() => { who = "alice"; });

describe("the main flow against the real backend", () => {
  it("refuses an expired or unknown session with 401, not with empty data", async () => {
    who = "not-a-real-token";
    const r = await api("me");
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.status).toBe(401);
    who = "alice";
  });

  it("reports the signed-in user and an unlicensed account honestly", async () => {
    const r = await api<{ user: { userId: string }; licence: { state: string } }>("me");
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.data.user.userId).toMatch(/^aaaaaaaa-/);
      // Not "active" by default. An unknown entitlement is not an entitlement.
      expect(r.data.licence.state).toBe("none");
    }
  });

  it("serves the condition library the Rule Builder is generated from", async () => {
    const r = await api<{ conditions: Record<string, unknown> }>("conditions");
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(Object.keys(r.data.conditions).length).toBe(12);
      expect(r.data.conditions).toHaveProperty("rsi");
      // Concepts with no pinned definition are deliberately absent.
      expect(r.data.conditions).not.toHaveProperty("liquidity_sweep");
    }
  });

  it("shows an unconnected account as not connected, with no positions key", async () => {
    const r = await api<{ connected: boolean; status: string; positions?: unknown }>("positions");
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.data.connected).toBe(false);
      expect(r.data.status).toBe("not_connected");
      // The absence of the key is the point: nothing can render "0 positions".
      expect(r.data.positions).toBeUndefined();
    }
  });

  it("creates a draft owned by the caller, not by the body", async () => {
    const r = await api<{ rule: { ruleDocId: string; userId: string; state: string } }>(
      "rules", {
        method: "POST",
        body: {
          name: "e2e", symbols: ["EUR_USD"], timeframe: "1h", accountId: "501",
          sides: "BUY", userId: "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb",
          entry: { combine: "AND", conditions: [{ id: "rsi", params: { op: "below", value: 100 } }] },
          exit: { combine: "OR", conditions: [{ id: "rsi", params: { op: "above", value: 70 } }] },
        },
      });
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.data.rule.userId).toMatch(/^aaaaaaaa-/);
      expect(r.data.rule.state).toBe("draft");
      ruleId = r.data.rule.ruleDocId;
    }
  });

  let ruleId = "";

  it("refuses another client's rule with 404, revealing nothing", async () => {
    who = "bob";
    const r = await api(`rules/${ruleId}`);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.status).toBe(404);
    const missing = await api("rules/does-not-exist");
    // Indistinguishable from one that never existed.
    if (!missing.ok && !r.ok) expect(missing.status).toBe(r.status);
    who = "alice";
  });

  it("reports every validation problem for an invalid rule", async () => {
    const created = await api<{ rule: { ruleDocId: string } }>("rules", {
      method: "POST", body: { name: "broken" },
    });
    expect(created.ok).toBe(true);
    if (!created.ok) return;
    const v = await api<{ valid: boolean; problems: string[] }>(
      `rules/${created.data.rule.ruleDocId}/validate`, { method: "POST" });
    expect(v.ok).toBe(true);
    if (v.ok) {
      expect(v.data.valid).toBe(false);
      expect(v.data.problems.length).toBeGreaterThan(1);
    }
    const a = await api(`rules/${created.data.rule.ruleDocId}/activate`, { method: "POST" });
    expect(a.ok).toBe(false);
    if (!a.ok) expect([402, 422]).toContain(a.status);
  });

  it("previews a HOLD as a decision that would not trade", async () => {
    const bars = Array.from({ length: 80 }, (_, i) => {
      const c = 1.1 + 0.004 * Math.sin((2 * Math.PI * i) / 37);
      return { open: c, high: c + 0.0005, low: c - 0.0005, close: c };
    });
    // RSI below 1 is essentially never true, so the rule holds.
    const hold = await api<{ rule: { ruleDocId: string } }>("rules", {
      method: "POST", body: {
        name: "holds", symbols: ["EUR_USD"], timeframe: "1h", accountId: "501", sides: "BUY",
        entry: { combine: "AND", conditions: [{ id: "rsi", params: { op: "below", value: 1 } }] },
        exit: { combine: "OR", conditions: [{ id: "rsi", params: { op: "above", value: 70 } }] },
      },
    });
    if (!hold.ok) throw new Error("setup failed");
    const p = await api<{ decision: { verdict: string }; wouldTrade: boolean; executable: boolean }>(
      `rules/${hold.data.rule.ruleDocId}/preview`,
      { method: "POST", body: { snapshot: { candles: bars, ts: 1758542400 } } });
    expect(p.ok).toBe(true);
    if (p.ok) {
      expect(p.data.decision.verdict).toBe("HOLD");
      expect(p.data.wouldTrade).toBe(false);
      expect(p.data.executable).toBe(false);
    }
  });

  it("previews a REJECT when the data cannot answer the rule", async () => {
    const rej = await api<{ rule: { ruleDocId: string } }>("rules", {
      method: "POST", body: {
        name: "rejects", symbols: ["EUR_USD"], timeframe: "1h", accountId: "501", sides: "BUY",
        entry: { combine: "AND", conditions: [
          { id: "weekday", params: { days: [0, 1, 2, 3, 4, 5, 6] } },
          { id: "price_vs_ma", params: { period: 200 } }] },
        exit: { combine: "OR", conditions: [{ id: "rsi", params: { op: "above", value: 70 } }] },
      },
    });
    if (!rej.ok) throw new Error("setup failed");
    const bars = Array.from({ length: 30 }, (_, i) => {
      const c = 1.1 + 0.001 * i;
      return { open: c, high: c + 0.0005, low: c - 0.0005, close: c };
    });
    const p = await api<{ decision: { verdict: string; refusalCode: string }; wouldTrade: boolean }>(
      `rules/${rej.data.rule.ruleDocId}/preview`,
      { method: "POST", body: { snapshot: { candles: bars, ts: 1758542400 } } });
    expect(p.ok).toBe(true);
    if (p.ok) {
      expect(p.data.decision.verdict).toBe("REJECT");
      expect(p.data.decision.refusalCode).toBe("INSUFFICIENT_DATA");
      expect(p.data.wouldTrade).toBe(false);
    }
  });

  it("refuses a preview with no candles instead of inventing a verdict", async () => {
    const p = await api(`rules/${ruleId}/preview`, { method: "POST", body: { snapshot: {} } });
    expect(p.ok).toBe(false);
    if (!p.ok) {
      expect(p.status).toBe(422);
      expect(p.code).toBe("INSUFFICIENT_DATA");
    }
  });

  it("will not start automation without a licence", async () => {
    const r = await api("automation/start", { method: "POST", body: { ruleDocId: ruleId } });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.status).toBe(402);
  });

  it("runs the whole demo flow once licence and a demo account exist", async () => {
    await seed("licence");
    await seed("ctrader");

    const acc = await api<{ connected: boolean; selected: { mode: string } }>("accounts");
    expect(acc.ok).toBe(true);
    if (acc.ok) {
      expect(acc.data.connected).toBe(true);
      expect(acc.data.selected.mode).toBe("demo");
    }

    const pos = await api<{ status: string; mode: string; positions: unknown[] }>("positions");
    expect(pos.ok).toBe(true);
    if (pos.ok) {
      expect(pos.data.status).toBe("ok");
      expect(pos.data.mode).toBe("demo");
      expect(pos.data.positions).toEqual([]);
    }

    const act = await api(`rules/${ruleId}/activate`, { method: "POST" });
    expect(act.ok).toBe(true);

    const start = await api<{ state: string; started: boolean }>(
      "automation/start", { method: "POST", body: { ruleDocId: ruleId } });
    expect(start.ok).toBe(true);
    if (start.ok) expect(start.data.state).toBe("running");

    const again = await api<{ alreadyRunning: boolean }>(
      "automation/start", { method: "POST", body: { ruleDocId: ruleId } });
    if (again.ok) expect(again.data.alreadyRunning).toBe(true);

    const paused = await api<{ state: string }>("automation/pause", { method: "POST" });
    if (paused.ok) expect(paused.data.state).toBe("paused");
    const resumed = await api<{ state: string }>("automation/resume", { method: "POST" });
    if (resumed.ok) expect(resumed.data.state).toBe("running");
    const stopped = await api<{ state: string }>("automation/stop", { method: "POST" });
    if (stopped.ok) expect(stopped.data.state).toBe("stopped");

    const jr = await api<{ entries: { status: string }[] }>("journal?status=automation_started");
    expect(jr.ok).toBe(true);
    if (jr.ok) expect(jr.data.entries.length).toBeGreaterThan(0);

    const nt = await api<{ unread: number }>("notifications");
    if (nt.ok) expect(nt.data.unread).toBeGreaterThan(0);
  });

  it("serves real candles, and refuses a bad request before the broker", async () => {
    const good = await api<{ status: string; candles: { open: number }[];
                             symbol: string; count: number }>(
      "accounts/501/candles?symbol=EURUSD&timeframe=1h&limit=60");
    expect(good.ok).toBe(true);
    if (good.ok) {
      expect(good.data.status).toBe("ok");
      expect(good.data.symbol).toBe("EURUSD");
      expect(good.data.count).toBe(60);
      expect(good.data.candles).toHaveLength(60);
      // Only the fields a snapshot needs. Anything else the connector
      // attaches is not part of this contract.
      expect(Object.keys(good.data.candles[0]).sort())
        .toEqual(["close", "high", "low", "open", "time"]);
    }
    for (const q of [
      "symbol=BTCUSD&timeframe=1h", "symbol=EURUSD&timeframe=7h",
      "symbol=EURUSD&timeframe=1h&limit=99999",
      "symbol=EURUSD&timeframe=1h&limit=abc", "symbol=&timeframe=1h",
    ]) {
      const bad = await api<{ candles?: unknown }>(`accounts/501/candles?${q}`);
      expect(bad.ok).toBe(false);
      if (!bad.ok) expect(bad.status).toBe(400);
      expect((bad as { data?: { candles?: unknown } }).data?.candles).toBeUndefined();
    }
    // Bob has linked nothing, so every account id answers the same way: not
    // connected, with no candles. He learns nothing about whether 501 exists,
    // which is the property that matters.
    who = "bob";
    const theirs = await api<{ connected: boolean; candles?: unknown }>(
      "accounts/501/candles?symbol=EURUSD&timeframe=1h");
    if (theirs.ok) {
      expect(theirs.data.connected).toBe(false);
      expect(theirs.data.candles).toBeUndefined();
      const invented = await api<{ connected: boolean }>(
        "accounts/424242/candles?symbol=EURUSD&timeframe=1h");
      // Indistinguishable from an account that does not exist at all.
      if (invented.ok) expect(invented.data).toEqual(theirs.data);
    } else {
      expect(theirs.code).toBe("NO_SUCH_ACCOUNT");
    }
    who = "alice";
  });

  it("previews on fetched candles and leaves nothing behind", async () => {
    // Bars a real fetch would produce, handed straight to preview — the same
    // two-step the UI performs.
    const bars = Array.from({ length: 90 }, (_, i) => {
      const c = 1.1 + 0.004 * Math.sin((2 * Math.PI * i) / 37);
      return { open: c, high: c + 0.0005, low: c - 0.0005, close: c };
    });
    const beforeJournal = await api<{ total: number }>("journal");
    const beforePositions = await api<{ positions: unknown[] }>("positions");
    const beforeOrders = await api<{ orders: unknown[] }>("orders");
    const beforeBalance = await api<{ balance: number }>("accounts/501");

    const p = await api<{ decision: { verdict: string }; wouldTrade: boolean;
                          executable: boolean; snapshot: { ts: number } }>(
      `rules/${ruleId}/preview`,
      { method: "POST", body: { snapshot: { candles: bars, ts: 1758542400 } } });
    expect(p.ok).toBe(true);
    if (p.ok) {
      expect(["BUY", "SELL", "HOLD", "REJECT"]).toContain(p.data.decision.verdict);
      expect(p.data.executable).toBe(false);
      // The snapshot's ts is the one we sent, never one the server chose.
      expect(p.data.snapshot.ts).toBe(1758542400);
    }

    const afterJournal = await api<{ total: number }>("journal");
    const afterPositions = await api<{ positions: unknown[] }>("positions");
    const afterOrders = await api<{ orders: unknown[] }>("orders");
    const afterBalance = await api<{ balance: number }>("accounts/501");
    if (beforeJournal.ok && afterJournal.ok) {
      // Not one execution entry, not one evaluation entry.
      expect(afterJournal.data.total).toBe(beforeJournal.data.total);
    }
    if (beforePositions.ok && afterPositions.ok) {
      expect(afterPositions.data.positions).toEqual(beforePositions.data.positions);
    }
    if (beforeOrders.ok && afterOrders.ok) {
      expect(afterOrders.data.orders).toEqual(beforeOrders.data.orders);
    }
    if (beforeBalance.ok && afterBalance.ok) {
      expect(afterBalance.data.balance).toEqual(beforeBalance.data.balance);
    }
  });

  it("reports reauth_required rather than an empty account", async () => {
    await seed("reauth");
    const r = await api<{ status: string; positions?: unknown }>("positions");
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.data.status).toBe("reauth_required");
      expect(r.data.positions).toBeUndefined();
    }
  });

  it("never returns a cTrader token to the client", async () => {
    const all = await Promise.all([
      api("accounts"), api("ctrader/status"), api("me"), api("journal"),
    ]);
    for (const r of all) {
      expect(JSON.stringify(r)).not.toContain("CT-SECRET");
      expect(JSON.stringify(r)).not.toContain("accessToken");
    }
  });
});
