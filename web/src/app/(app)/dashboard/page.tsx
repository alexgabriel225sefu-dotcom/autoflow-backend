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
import { api } from "@/lib/api";
import { useRead, whenSynced } from "@/lib/use-api";
import { ConfirmAction } from "@/components/app/shell";
import { ErrorNotice, ExecutionBadge, PlanNotice, Spinner } from "@/components/app/state";
import { DataTable, Num, Side, When } from "@/components/app/table";
import { plainAutomation, plainDecision, plainLicence, plainRead, toneClass, tonePill } from "@/components/app/plain";
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
      {status === "not_connected" ? (
        <Link className="btn btn-sm" href="/connect">Connect cTrader</Link>
      ) : status === "reauth_required" ? (
        <Link className="btn btn-sm" href="/connect">Reconnect cTrader</Link>
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
  const runningThis = running && running.state !== "stopped";

  async function select(ctid: number | string) {
    setBusy(true);
    await api("ctrader/select", { method: "POST", body: { ctid } });
    setBusy(false);
    void ct.reload();
  }

  async function control(action: "start" | "pause" | "resume" | "stop") {
    const body = action === "start" && activeRule
      ? { ruleDocId: activeRule.ruleDocId } : undefined;
    const r = await api<AutomationState>(`automation/${action}`, { method: "POST", body });
    void auto.reload();
    void jr.reload();
    if (!r.ok) return `${r.code}: ${r.message}`;
    return `Automation is now ${r.data.state}`;
  }

  return (
    <main>
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
                  ) : !isDemo ? (
                    <div className="notice notice-warn" role="alert">
                      {/* The account picker's state is what opens this
                          notice, and `me` is polled on a different clock, so
                          the sentence is a constant rather than whatever
                          verdict happens to be in hand. It is the same
                          sentence the server refuses with — content.test.ts
                          asserts that against the Python source. */}
                      Live trading is not available in this release.
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
                      {running?.state === "running" ? (
                        <ConfirmAction label="Pause" question="Pause automation?" onConfirm={() => control("pause")} />
                      ) : null}
                      {running?.state === "paused" ? (
                        <ConfirmAction label="Resume" question="Resume automation?" onConfirm={() => control("resume")} />
                      ) : null}
                      {runningThis ? (
                        <ConfirmAction label="Stop" danger question="Stop automation?" onConfirm={() => control("stop")} />
                      ) : null}
                    </div>
                  )}
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
