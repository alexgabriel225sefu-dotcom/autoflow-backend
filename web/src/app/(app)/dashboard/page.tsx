"use client";
/**
 * The dashboard answers five questions, in this order:
 *
 *   1. What account am I using?
 *   2. Is automation running?
 *   3. What rule is active?
 *   4. What did the system decide?
 *   5. Was an order placed?
 *
 * Everything else is one click away. The previous version led with four
 * counters and the word STOPPED, which is accurate and answers none of them.
 *
 * No state on this page is optimistic. A control that changes whether money
 * can move goes through ConfirmAction and shows the API's own answer, and a
 * read that failed shows why it failed rather than an empty list.
 */
import { useState } from "react";
import Link from "next/link";
import { Activity, Plug, RefreshCw } from "lucide-react";
import { api, type ApiError } from "@/lib/api";
import { invalidate, useRead, whenSynced } from "@/lib/use-api";
import { ConfirmAction } from "@/components/app/shell";
import {
  AccountLimitNotice, ErrorNotice, ExecutionBadge, PlanNotice, Spinner,
  TrialNotice,
} from "@/components/app/state";
import { PendingApproval } from "@/components/app/pending-approval";
import { DataTable, Num, Side, When } from "@/components/app/table";
import { outcomeOf, plainAutomation, plainDecision, plainLicence, plainRead, toneClass, tonePill } from "@/components/app/plain";
import { MarketPanel } from "@/components/chart/market-panel";
import type {
  AutomationState, CtraderStatus, JournalPage, Me, OrdersRead,
  Position, PositionsRead, RuleSummary,
} from "@/lib/api";

/** A read that failed, said plainly, with the action that fixes it. */
function Unavailable({ status, reason }: { status: string; reason?: string }) {
  const p = plainRead(status, reason);
  if (!p) return null;
  return (
    <div className={p.tone === "short" ? "notice notice-warn" : "notice"} role="status">
      <p style={{ fontWeight: 600 }}>{p.label}</p>
      {p.detail ? <p className="muted" style={{ fontSize: ".82rem" }}>{p.detail}</p> : null}
      {/* QUIET, because this panel is not the one asking.
          Every panel reports its own read, which is the point — an empty
          table must never stand in for "we could not look". But on a first
          visit all four of them are not-connected at once, and when each
          carried a filled button the screen showed four identical shouting
          calls to action with no way to tell which one to press. The
          Automation panel keeps the filled one; these offer the same fix
          without competing with it. */}
      {status === "not_connected" ? (
        <Link className="btn btn-ghost btn-sm" href="/connect">Connect cTrader</Link>
      ) : status === "reauth_required" ? (
        <Link className="btn btn-ghost btn-sm" href="/connect">Reconnect cTrader</Link>
      ) : null}
    </div>
  );
}

export default function Dashboard() {
  const me = useRead<Me>("me", 120_000);
  const ct = useRead<CtraderStatus>("ctrader/status", 60_000);
  const auto = useRead<AutomationState>("automation", 20_000);
  const pos = useRead<PositionsRead>("positions", 30_000);
  const ord = useRead<OrdersRead>("orders", 60_000);
  const jr = useRead<JournalPage>("journal?limit=8", 30_000);
  const rules = useRead<{ rules: RuleSummary[] }>("rules", 120_000);
  const [busy, setBusy] = useState(false);
  // A refusal from the account picker. Its own state rather than a shared
  // one: it must survive the status reload that follows, which is the
  // moment the old code lost it.
  const [selectErr, setSelectErr] = useState<ApiError | null>(null);
  const [emergencyOpen, setEmergencyOpen] = useState(false);

  const account = ct.result?.ok ? ct.result.data : null;
  const selected = account?.selected ?? null;
  const running = auto.result?.ok ? auto.result.data : null;
  const licence = me.result?.ok ? me.result.data.licence.state : undefined;
  // The server's verdict, used as given. See ExecutionBadge for why this is
  // not recombined from `licence` and `selected.mode` here.
  const execution = me.result?.ok ? me.result.data.execution : null;
  const allRules = rules.result?.ok ? rules.result.data.rules : [];
  const activeRule = allRules.find((r) => r.ruleDocId === running?.ruleDocId)
    ?? allRules.find((r) => r.state === "active")
    ?? null;

  const lastSync = Math.max(...[ct, auto, pos, jr].map((r) => r.lastSync ?? 0)) || null;
  const autoPlain = plainAutomation(running?.state, !!activeRule);
  const licPlain = plainLicence(licence);
  const isDemo = selected?.mode === "demo";
  // A live account the SERVER has cleared, and cleared for live specifically.
  // Both halves matter: `canAutomate` alone could be a verdict about the demo
  // account the client just switched away from, because the picker and `me`
  // refresh on different clocks.
  const liveCleared =
    execution?.accountMode === "live" && execution.canAutomate === true;
  const runningThis = running && running.state !== "stopped";

  /**
   * Choosing which connected account to use.
   *
   * The result used to be thrown away: `await api(...)` with nothing read
   * from it, then a reload. So a refusal produced NOTHING — the dropdown
   * snapped back, the strip still said "No account selected", and the
   * reader was given no reason and no retry. The owner hit it on a phone
   * on 2026-10-04, where the server was answering
   * `429 RATE_LIMITED retryAfterSec=42` because select shared a bucket with
   * the OAuth round he had just spent. The rate limit is fixed; this is the
   * reason he could not see it, and it would have hidden the next failure
   * just as well.
   *
   * `me` is invalidated with the status because `execution` is derived from
   * which account is selected — canAutomate and the DEMO badge both move.
   */
  async function select(ctid: number | string) {
    setBusy(true);
    setSelectErr(null);
    const r = await api("ctrader/select", { method: "POST", body: { ctid } });
    setBusy(false);
    if (!r.ok) setSelectErr(r);
    invalidate("ctrader/status", "accounts", "me");
  }

  async function control(action: "start" | "pause" | "resume" | "stop") {
    const body = action === "start" && activeRule
      ? { ruleDocId: activeRule.ruleDocId } : undefined;
    const r = await api<AutomationState>(`automation/${action}`, { method: "POST", body });
    // By endpoint, not by this page's private copies. The app shell polls
    // `automation` too, for the status strip, and reloading only the local
    // read left the strip claiming STOPPED while this panel said running.
    invalidate("automation", "journal?limit=8", "me");
    // Reload this mounted copy before ConfirmAction closes its confirmation
    // prompt. Otherwise a refused Stop can leave the page claiming RUNNING
    // (or a successful Start claiming STOPPED) until the polling interval.
    await auto.reload();
    if (!r.ok) return `${r.code}: ${r.message}`;
    return outcomeOf(r.data);
  }

  async function stopAndCloseDemo(): Promise<string> {
    if (!selected || selected.mode !== "demo") return "Emergency close is available only for the selected demo account.";
    const stop = await api<AutomationState>("automation/stop", { method: "POST" });
    if (!stop.ok) return `${stop.code}: ${stop.message}`;
    const current = pos.result?.ok && pos.result.data.status === "ok" ? pos.result.data.positions ?? [] : [];
    for (const p of current) {
      const closed = await api(`accounts/${selected.ctid}/positions/${p.positionId}/close`, { method: "POST" });
      if (!closed.ok) return `${closed.code}: ${closed.message}`;
    }
    const after = await api<PositionsRead>("positions");
    invalidate("automation", "positions", "journal?limit=8", "me");
    await auto.reload();
    await pos.reload();
    if (after.ok && after.data.status === "ok" && (after.data.positions ?? []).length === 0) return "Confirmed flat.";
    const remaining = after.ok ? (after.data.positions ?? []).map((p) => String(p.positionId)).join(", ") : "the broker read failed";
    return `Not confirmed flat. Remaining positions: ${remaining || "unknown"}.`;
  }

  return (
    <main className="dashboard-terminal">
      <div className="page-head">
        <div>
          <h1>Dashboard</h1>
          <span className="sub">Last synced {whenSynced(lastSync)}</span>
        </div>
        <button className="btn btn-ghost btn-sm" onClick={() => { void ct.reload(); void auto.reload(); void pos.reload(); void jr.reload(); }}>
          <RefreshCw className="ico" aria-hidden /> Refresh
        </button>
      </div>

      <div className="workspace">
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--sp-3)" }}>

          {/* ── 0: the one thing on this screen with a deadline ──────────
              A setup the rule proposed at the Approval Required level opens
              only if the client agrees, and it expires five minutes after it
              was found. So it leads — above the account, above the running
              state — and it renders nothing at all when none is waiting,
              which is most of the time.

              It reads `approvals` itself rather than taking a prop. Nothing
              else on this page needs that read, and a pending proposal has
              to be answerable from wherever it is shown. */}
          <PendingApproval />

          {/* ── 1 + 2: which account, and is it running ─────────────── */}
          <section className="card">
            <div className="card-head">
              <h2>Automation</h2>
              <span className="btn-row">
                <ExecutionBadge execution={execution} />
                {licence === "revoked" ? (
                  <Link className={tonePill(licPlain.tone)} href="/license">
                    Licence: {licPlain.label}
                  </Link>
                ) : null}
              </span>
            </div>

            {ct.result && !ct.result.ok ? <ErrorNotice error={ct.result} onRetry={ct.reload} /> : null}

            {/* The trial clock, above the pricing sentence it belongs to.
                The server has always reported the days left; until this was
                here, nothing in the browser read them, so the free period
                ran out without the client ever seeing it count down. */}
            <TrialNotice execution={execution} />

            {/* What this release costs and what it cannot do, in the
                server's words. It sits above the account picker because it
                is the answer to the question somebody has before they
                connect anything. */}
            <PlanNotice execution={execution} />

            {account === null ? <Spinner label="Checking your broker link" />
              : !account.connected ? (
                <div className="notice">
                  <p style={{ fontWeight: 600 }}>cTrader account not connected</p>
                  <p className="muted" style={{ fontSize: ".82rem" }}>
                    Orders are placed through an account you connect yourself.
                    Nothing runs until one is connected and selected.
                  </p>
                  <Link className="btn btn-sm" href="/connect">
                    <Plug className="ico" aria-hidden /> Connect cTrader
                  </Link>
                </div>
              ) : (
                <>
                  <label className="field">
                    <span>Account</span>
                    <select
                      value={selected ? String(selected.ctid) : ""}
                      disabled={busy}
                      onChange={(e) => { if (e.target.value) void select(e.target.value); }}
                    >
                      <option value="" disabled>Choose an account</option>
                      {account.accounts.map((a) => (
                        <option
                          key={String(a.ctid)}
                          value={String(a.ctid)}
                          /* A live account is never selectable here. The
                             backend refuses it too; this only avoids
                             offering it. */
                          disabled={a.mode === "live" && !account.liveAllowed}
                        >
                          #{a.ctid} — {a.mode === "live" ? "live (not available)" : "demo"}
                        </option>
                      ))}
                    </select>
                  </label>

                  {/* The server's own words. Silence here is what made the
                      account unselectable without saying so: the picker
                      snapped back, the strip still read "No account
                      selected", and nothing on screen said why. */}
                  {/* The account-limit refusal has somewhere to go, so it
                      renders as the notice that carries the link and its
                      disclosure rather than as a red line with no way
                      forward. Switching accounts is possible from here as
                      well as from the Accounts page, and a client who hit the
                      limit here would otherwise read a reason and be given
                      nothing to do about it. One shared component, so the
                      disclosure cannot drift between the two screens. */}
                  {selectErr?.code === "ACCOUNT_LIMIT" ? (
                    <AccountLimitNotice error={selectErr} />
                  ) : selectErr ? (
                    <ErrorNotice error={selectErr}
                                 onRetry={selected ? undefined : () => setSelectErr(null)} />
                  ) : null}

                  <div
                    className="verdict-banner"
                    data-kind={autoPlain.tone === "long" ? "buy" : undefined}
                    style={{ marginTop: "var(--sp-2)" }}
                  >
                    <Activity
                      className="ico" aria-hidden
                      style={{ width: 20, height: 20, flex: "none", color: "var(--a4t-link)" }}
                    />
                    <div className="vb-body" style={{ flex: 1 }}>
                      <p className={`verdict ${toneClass(autoPlain.tone)}`} style={{ fontSize: "1.15rem" }}>
                        {autoPlain.label}
                      </p>
                      {autoPlain.detail ? <p className="vb-note">{autoPlain.detail}</p> : null}
                    </div>
                  </div>

                  {!selected ? (
                    <p className="muted" style={{ fontSize: ".82rem", marginTop: "var(--sp-2)" }}>
                      Choose an account above before starting.
                    </p>
                  ) : !isDemo && !liveCleared ? (
                    <div className="notice notice-warn" role="alert">
                      {/* WHY THIS IS NOT JUST `!isDemo` ANY MORE.
                          A hardcoded refusal was right while no deployment
                          could execute live. It stopped being right the day
                          one could: it would have shown a paying client, on
                          a deployment with the switch open, that live is
                          unavailable — and hidden the Start button from them
                          entirely. The browser would have been overruling a
                          server that said yes.
                          `liveCleared` requires the server's verdict to be
                          about THIS mode. The picker and `me` poll on
                          different clocks, so a verdict describing the demo
                          account must not unlock controls for a live one;
                          requiring accountMode === "live" is what rules that
                          out. The fallback sentence is unchanged and still
                          pinned to the Python source by content.test.ts. */}
                      {execution && execution.accountMode === "live"
                        && execution.message
                        ? execution.message
                        : "Live trading is not available in this release."}
                    </div>
                  ) : (
                    <div className="btn-row" style={{ marginTop: "var(--sp-3)" }}>
                      {!runningThis ? (
                        <ConfirmAction
                          label="Start"
                          question={activeRule ? `Start watching with "${activeRule.name || "this rule"}"?` : "Start?"}
                          disabled={!activeRule || !execution?.canAutomate}
                          disabledReason={
                            !activeRule ? "Activate a rule first"
                              : !execution?.canAutomate
                                ? execution?.message ?? "Access is being checked"
                                : undefined
                          }
                          onConfirm={() => control("start")}
                        />
                      ) : null}
                      {/* A PAUSE STOPS THE WHOLE LOOP, not just new entries.
                          While paused there is no trailing stop, no
                          break-even and no exit condition — an open position
                          keeps only what the broker already holds. */}
                      {running?.state === "running" ? (
                        <ConfirmAction label="Pause"
                                       question="Pause automation? Anything already open stops being managed too — it keeps only the stop-loss your broker holds."
                                       onConfirm={() => control("pause")} />
                      ) : null}
                      {running?.state === "paused" ? (
                        <ConfirmAction label="Resume" question="Resume automation?" onConfirm={() => control("resume")} />
                      ) : null}
                      {/* SAYS WHAT STOP DOES NOT DO, BEFORE IT IS PRESSED.
                          "Stop automation?" invited the reading that it also
                          closes what is open, which it does not — and finding
                          that out afterwards, from a sentence under a button,
                          is finding it out too late. */}
                      {runningThis ? (
                        <ConfirmAction label="Stop" danger
                                       question="Stop automation? Anything already open stays at your broker — this closes nothing."
                                       onConfirm={() => control("stop")} />
                      ) : null}
                      {isDemo ? (
                        <button className="btn btn-ghost" type="button" onClick={() => setEmergencyOpen((v) => !v)} aria-expanded={emergencyOpen}>
                          Emergency
                        </button>
                      ) : null}
                    </div>
                  )}
                  {emergencyOpen && isDemo ? (
                    <div className="notice notice-warn" role="region" aria-label="Emergency controls">
                      <strong>Emergency controls</strong>
                      <p className="muted">Each action has a separate confirmation. Stop only leaves broker positions open.</p>
                      <div className="btn-row">
                        <ConfirmAction label="Stop only" danger
                          question="Stop automation only? Existing demo positions remain open at cTrader."
                          onConfirm={() => control("stop")} />
                        <ConfirmAction label="Stop and close positions" danger
                          question="Stop automation and close every open demo position by position ID?"
                          onConfirm={stopAndCloseDemo} />
                      </div>
                    </div>
                  ) : null}
                </>
              )}
          </section>

          {/* ── 3: the market the active rule is watching ───────────── */}
          <MarketPanel
            title="Market"
            ctid={selected?.ctid ?? null}
            mode={selected?.mode ?? null}
            symbols={(activeRule?.symbols as string[] | undefined) ?? []}
            timeframe={activeRule?.timeframe}
          />

          {/* ── 4 + 5: what did it decide, and was anything placed ──── */}
          <section className="card">
            <div className="card-head">
              <h2>What the rule decided</h2>
              <Link className="link-sm" href="/journal">Full journal →</Link>
            </div>
            <p className="muted" style={{ fontSize: ".8rem", marginBottom: "var(--sp-3)" }}>
              Every check is recorded, including the ones that decided to do
              nothing.
            </p>
            {jr.result && !jr.result.ok ? <ErrorNotice error={jr.result} onRetry={jr.reload} /> : null}
            {jr.result?.ok ? (
              jr.result.data.entries.length ? (
                <div className="records">
                  {jr.result.data.entries.map((e) => {
                    const p = plainDecision(e);
                    return (
                      <article className="record" key={e.entryId}>
                        <div className="record-head">
                          <span className="record-title">
                            <span className={toneClass(p.tone)}>{p.label}</span>
                            {e.symbol ? <span className="muted"> · {e.symbol}</span> : null}
                          </span>
                          <span className="dim" style={{ fontSize: ".74rem" }}><When ts={e.ts} /></span>
                        </div>
                        {p.detail ? (
                          <p className="muted" style={{ fontSize: ".82rem" }}>{p.detail}</p>
                        ) : null}
                      </article>
                    );
                  })}
                </div>
              ) : (
                <p className="empty">
                  Nothing recorded yet. Once automation is watching, every
                  check appears here.
                </p>
              )
            ) : jr.result ? null : <Spinner />}
          </section>
        </div>

        {/* ── inspector ───────────────────────────────────────────────── */}
        <aside className="inspector">

          {/* 3: what rule is active */}
          <section className="card">
            <div className="card-head">
              <h2>Active rule</h2>
              <Link className="link-sm" href="/rules">All rules →</Link>
            </div>
            {rules.result && !rules.result.ok ? <ErrorNotice error={rules.result} /> : null}
            {rules.result?.ok ? (
              activeRule ? (
                <>
                  <p style={{ fontWeight: 600 }}>
                    <Link href={`/rules/${activeRule.ruleDocId}`}>
                      {activeRule.name || "(untitled)"}
                    </Link>
                  </p>
                  <div className="btn-row" style={{ marginTop: "var(--sp-2)" }}>
                    <span className="pill pill-muted">{(activeRule.symbols ?? []).join(", ") || "no market"}</span>
                    <span className="pill pill-muted">{activeRule.timeframe}</span>
                    <span className="pill pill-muted mono">v{activeRule.version}</span>
                  </div>
                  <p className="dim" style={{ fontSize: ".78rem", marginTop: "var(--sp-2)" }}>
                    Open the rule to preview what it would decide right now.
                  </p>
                </>
              ) : (
                <div className="notice">
                  <p>No active rule.</p>
                  <Link className="btn btn-sm" href="/rules/new">Create a rule</Link>
                </div>
              )
            ) : <Spinner />}
          </section>

          {/* 5: positions and orders, from the broker or not at all */}
          <section className="card">
            <div className="card-head">
              <h2>Open positions</h2>
              <Link className="link-sm" href="/positions">All →</Link>
            </div>
            {pos.result && !pos.result.ok ? <ErrorNotice error={pos.result} onRetry={pos.reload} /> : null}
            {pos.result?.ok ? (
              pos.result.data.status === "ok" ? (
                <DataTable<Position>
                  rows={pos.result.data.positions ?? []}
                  rowKey={(p) => String(p.positionId)}
                  /* Only ever said after status ok, so it is a fact the
                     broker confirmed rather than a guess. */
                  empty="No open positions."
                  cardTitle={(p) => p.symbol}
                  cardBadge={(p) => <Side side={p.side} />}
                  columns={[
                    { key: "symbol", header: "Symbol", cell: (p) => p.symbol },
                    { key: "side", header: "Side", cell: (p) => <Side side={p.side} />, hideOnCard: true },
                    { key: "units", header: "Units", num: true, cell: (p) => <Num value={p.units} /> },
                    { key: "entry", header: "Entry", num: true, cell: (p) => <Num value={p.entryPrice} /> },
                  ]}
                />
              ) : (
                <Unavailable status={pos.result.data.status} reason={pos.result.data.reason} />
              )
            ) : <Spinner />}
          </section>

          <section className="card">
            <div className="card-head">
              <h2>Pending orders</h2>
              <Link className="link-sm" href="/orders">All →</Link>
            </div>
            {ord.result && !ord.result.ok ? <ErrorNotice error={ord.result} onRetry={ord.reload} /> : null}
            {ord.result?.ok ? (
              ord.result.data.status === "ok" ? (
                (ord.result.data.orders ?? []).length ? (
                  <p>{(ord.result.data.orders ?? []).length} waiting at the broker.</p>
                ) : <p className="empty">No pending orders.</p>
              ) : (
                <Unavailable status={ord.result.data.status} reason={ord.result.data.reason} />
              )
            ) : <Spinner />}
          </section>

          <section className="card card-flat">
            <p className="muted" style={{ fontSize: ".8rem", lineHeight: 1.6 }}>
              <strong style={{ color: "var(--a4t-text)" }}>Demo only.</strong>{" "}
              Live trading is not available in this release. Orders are placed
              on the cTrader account you connected, and you can disconnect it
              at any time.
            </p>
          </section>
        </aside>
      </div>
    </main>
  );
}
