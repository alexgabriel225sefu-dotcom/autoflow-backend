"use client";
import { useMemo, useState } from "react";
import Link from "next/link";
import {
  api, type ApiError, type AutomationState, type CtraderStatus, type Me,
  type MinLotRead, type RuleDoc, type RuleSummary, type SetupLibrary, type SetupResult,
} from "@/lib/api";
import { invalidate, useRead } from "@/lib/use-api";
import { useDebounced } from "@/lib/use-debounced";
import { ConfirmAction } from "@/components/app/shell";
import { fireStartConfetti } from "@/components/app/start-confetti";
import { AUTOMATION_LEVELS } from "@/components/app/plain";
import { ErrorNotice, Spinner } from "@/components/app/state";
import { SegmentedControl } from "@/components/app/segmented";
import { CurrencyTicker } from "@/components/app/currency-ticker";
import { groupByFamily } from "../rules/new/strategy/catalog";
import { StrategyStep } from "./strategy-step";
import {
  DAILY_LOSS_CEILING, EMPTY_CHOICE, LIVE_RISK_CAP, RISK_PICKS, ROW_LIMIT,
  TIMEFRAME_CHOICES, accountAction, minLotNotice, minLotPath, riskAmounts,
  setupPayload, stepBlock, symbolView, type TradeChoice,
} from "./trade-model";

/**
 * Automation setup, one step at a time: symbols, strategy, risk, account, review.
 *
 * Nothing here decides that live may run. The account step shows the server's
 * state (request access, or waiting), and Start posts one body to
 * /automation/setup, which refuses the start again if the gate is closed.
 * No strategy card shows a result. There is no published backtest.
 */

const STEPS = ["Symbols", "Strategy", "Risk", "Account", "Review"] as const;
const pct = (v: string) => (v.trim() === "" ? "" : `${v.trim()}%`);

export default function TradePage() {
  const lib = useRead<SetupLibrary>("automation/setup");
  const accounts = useRead<CtraderStatus>("ctrader/status");
  const me = useRead<Me>("me");
  const auto = useRead<AutomationState>("automation", 30_000);
  const broker = useRead<SymbolsReadish>("symbols");
  const myRules = useRead<{ rules: RuleSummary[] }>("rules");

  const [step, setStep] = useState(0);
  const [c, setC] = useState<TradeChoice>(EMPTY_CHOICE);
  const [family, setFamily] = useState("all");
  const [open, setOpen] = useState("");
  const [err, setErr] = useState<ApiError | null>(null);
  const [note, setNote] = useState("");
  const [pickErr, setPickErr] = useState<ApiError | null>(null);
  const [query, setQuery] = useState("");
  const [symClass, setSymClass] = useState("all");
  const [showAll, setShowAll] = useState(false);
  const [tab, setTab] = useState<"ready" | "mine">("ready");
  const [methodErr, setMethodErr] = useState<ApiError | null>(null);
  const set = <K extends keyof TradeChoice>(k: K, v: TradeChoice[K]) =>
    setC((x) => ({ ...x, [k]: v }));

  const status = accounts.result?.ok ? accounts.result.data : null;
  const execution = me.result?.ok ? me.result.data.execution : null;
  const action = accountAction(c.account, { status, execution });
  const amounts = riskAmounts({
    accountSize: c.capitalAllocated, riskPercent: c.riskPercent,
    dailyLossPercent: c.dailyLossPercent,
  });
  const minLot = useRead<MinLotRead>(useDebounced(
    step >= 2 ? minLotPath(c) : null, 400));
  const lotNotice = minLot.result?.ok ? minLotNotice(minLot.result.data, c) : null;
  const running = auto.result?.ok && auto.result.data.state === "running";
  const catalogue = lib.result?.ok ? lib.result.data : null;
  const strategies = useMemo(() => catalogue?.strategies ?? [], [catalogue]);
  const groups = useMemo(() => groupByFamily(strategies), [strategies]);
  const shown = family === "all" ? groups : groups.filter((g) => g.family === family);
  const overLiveCap = Number(c.riskPercent) > LIVE_RISK_CAP;
  const view = symbolView(broker.result?.ok ? broker.result.data : null,
                          query, symClass, showAll);
  const myMethods = (myRules.result?.ok ? myRules.result.data.rules : [])
    .filter((r) => !r.strategy && (r.entryConditions ?? 0) > 0);
  const shownReasons = [...new Set(view.rows.filter((r) => !r.tradeable && r.reason)
    .map((r) => r.reason as string))];
  const block = stepBlock(step, c);
  const levelLabel = AUTOMATION_LEVELS.find((l) => l.id === c.level)?.label;

  async function pickMethod(r: RuleSummary) {
    setMethodErr(null);
    const res = await api<{ rule: RuleDoc }>(`rules/${encodeURIComponent(r.ruleDocId)}`);
    if (!res.ok) return setMethodErr(res);
    const d = res.data.rule as Record<string, unknown>;
    setC((x) => ({
      ...x, strategy: null,
      custom: { ruleDocId: r.ruleDocId, name: r.name, entry: d.entry, exit: d.exit,
                sides: String(d.sides ?? "BOTH") },
    }));
  }

  async function pick(ctid: string | number) {
    setPickErr(null);
    const r = await api("ctrader/select", { method: "POST", body: { ctid } });
    if (!r.ok) return setPickErr(r);
    invalidate("ctrader/status", "accounts", "me", "automation");
    await accounts.reload();
  }

  function chooseAccount(intent: "demo" | "live") {
    set("account", intent);
    if (intent !== "demo" || !status) return;
    const demo = status.accounts.find((a) => a.mode === "demo");
    if (demo && String(status.selected?.ctid) !== String(demo.ctid)) void pick(demo.ctid);
  }

  function toggleAlso(id: string) {
    setC((x) => ({
      ...x,
      also: x.also.includes(id) ? x.also.filter((s) => s !== id) : [...x.also, id],
    }));
  }

  async function go(): Promise<string> {
    setErr(null); setNote("");
    let body;
    try { body = setupPayload(c); } catch { return "The setup is incomplete."; }
    const res = await api<SetupResult>("automation/setup", { method: "POST", body });
    if (!res.ok) { setErr(res); return "Not started."; }
    invalidate("rules", "me", "automation");
    if (!res.data.executed) {
      const live = res.data.live;
      setNote(live?.summary || live?.label || "Live was not started.");
      return live?.label || "Live was not started.";
    }
    fireStartConfetti();
    return res.data.account === "live" ? "Started on live." : "Started on demo.";
  }

  const summary = [
    c.symbol || null,
    c.strategy?.label ?? (c.custom ? `${c.custom.name} (my method)` : null),
    c.timeframe,
    c.riskPercent ? `${pct(c.riskPercent)} per trade` : null,
    levelLabel,
    c.account === "live" ? "Live" : c.account === "demo" ? "Demo" : null,
  ].filter(Boolean).join(" · ");

  return (
    <main className="trade">
      <div className="page-head">
        <div>
          <h1>Automation setup</h1>
          <span className="sub">
            Choose the symbols, a strategy, the risk, and the account.
            Nothing trades until you review it and press Start.
          </span>
        </div>
      </div>

      <div className="chips" role="tablist" aria-label="Setup steps">
        {STEPS.map((label, i) => (
          <button key={label} type="button" role="tab" className="chip"
                  aria-selected={step === i} disabled={i > step}
                  onClick={() => setStep(i)}>
            {i + 1} {label}
          </button>
        ))}
      </div>

      {step === 0 ? (
        <section className="card" aria-labelledby="t-market">
          <div className="card-head"><h2 id="t-market"><span className="step-no">1</span> Symbols</h2></div>
          <div className="field"><span>Instrument to trade</span>
            <input type="search" placeholder="Search your broker's instruments, e.g. EURUSD, XAU, US30"
                   aria-label="Search instruments" value={query}
                   onChange={(e) => setQuery(e.target.value)} />
          </div>
          {view.classes.length > 1 ? (
            <SegmentedControl
              label="Instrument class"
              value={symClass}
              onChange={setSymClass}
              options={[
                { value: "all", label: "All" },
                ...view.classes.map((k) => ({ value: k.id, label: `${k.label} · ${k.count}` })),
              ]}
            />
          ) : null}
          {!broker.result ? <Spinner label="Reading your broker's instruments" /> : null}
          <div className="chips chips-symbols" role="radiogroup" aria-label="Instrument">
            {view.rows.map((r) => (
              <button key={r.id} type="button" role="radio" className="chip"
                      aria-checked={c.symbol === r.id}
                      aria-disabled={!r.tradeable} disabled={!r.tradeable}
                      title={r.reason ?? undefined}
                      onClick={() => set("symbol", r.id)}>{r.id}</button>
            ))}
          </div>
          {view.rows.length === 0 && broker.result ? (
            <p className="muted trade-note">No instrument matches. Clear the search or the class.</p>
          ) : null}
          {view.matches > ROW_LIMIT ? (
            <p className="muted trade-note">Showing {ROW_LIMIT} of {view.matches}. Search to narrow it down.</p>
          ) : null}
          {view.source === "broker" && view.unsupported > 0 ? (
            <label className="field-inline" style={{ marginTop: ".4rem" }}>
              <input type="checkbox" checked={showAll}
                     onChange={(e) => setShowAll(e.target.checked)} />
              <span>Also list the {view.unsupported} the engine cannot trade yet</span>
            </label>
          ) : null}
          {shownReasons.length ? (
            <ul className="trade-note muted" style={{ paddingLeft: "1.1rem" }}>
              {shownReasons.map((t) => <li key={t}>{t}</li>)}
            </ul>
          ) : null}
          <p className="muted trade-note">
            {view.source === "broker"
              ? `Your broker lists ${view.total} instruments. ${view.total - view.unsupported} can be traded now; the rest are shown with the reason, not hidden.`
              : "Your broker's list could not be read, so this shows what the engine supports: forex with a USD leg, plus gold and silver."}
          </p>
          {c.symbol ? (
            <div className="field">
              <span>Also record <span className="hint">not traded in this release</span></span>
              <div className="chips" role="group" aria-label="Additional symbols">
                {view.rows.filter((r) => r.tradeable && r.id !== c.symbol).map((r) => (
                  <button key={r.id} type="button" className="chip"
                          aria-pressed={c.also.includes(r.id)}
                          onClick={() => toggleAlso(r.id)}>{r.id}</button>
                ))}
              </div>
              <span className="field-note">
                {catalogue?.tradedSymbolNote
                  ?? "This release trades the first symbol. Any others are recorded and are not watched."}
              </span>
            </div>
          ) : null}
          <div className="field"><span>Timeframe</span>
            <SegmentedControl
              label="Timeframe"
              value={c.timeframe}
              onChange={(v) => set("timeframe", v)}
              options={TIMEFRAME_CHOICES.map((t) => ({ value: t, label: t }))}
            />
          </div>
        </section>
      ) : null}

      {step === 1 ? (
        <StrategyStep
          lib={{ result: lib.result, reload: lib.reload }}
          strategies={strategies} groups={groups} shown={shown}
          family={family} setFamily={setFamily} tab={tab} setTab={setTab}
          myRules={{ result: myRules.result, reload: myRules.reload }}
          myMethods={myMethods} methodErr={methodErr} open={open} setOpen={setOpen}
          choice={c}
          onPick={(s) => setC((x) => ({ ...x, strategy: s, custom: null }))}
          onMethod={(r) => void pickMethod(r)}
        />
      ) : null}

      {step === 2 ? (
        <section className="card" aria-labelledby="t-risk">
          <div className="card-head"><h2 id="t-risk"><span className="step-no">3</span> Risk</h2></div>
          <div className="grid grid-2">
            <label className="field">
              <span>Capital allocated <span className="hint">account currency</span></span>
              <input type="number" min="1" step="100" aria-label="Capital allocated"
                     value={c.capitalAllocated}
                     onChange={(e) => set("capitalAllocated", e.target.value)} />
              <span className="field-note">
                The most this automation may size from. The server enforces it.
              </span>
            </label>
            <label className="field">
              <span>Max open positions</span>
              <input type="number" min="1" max="8" step="1" aria-label="Max open positions"
                     value={c.maxOpenPositions}
                     onChange={(e) => set("maxOpenPositions", e.target.value)} />
              <span className="field-note">A demo account holds one position at a time in this release.</span>
            </label>
          </div>
          <div className="field"><span>Risk per trade <span className="hint">% of the capital allocated</span></span>
            <div className="chips">
              <SegmentedControl
                label="Risk per trade"
                value={c.riskPercent}
                onChange={(v) => set("riskPercent", v)}
                options={RISK_PICKS.map((r) => ({ value: r, label: `${r}%` }))}
              />
              <input type="number" step="0.05" min="0.05" max="100" aria-label="Custom risk per trade, percent"
                     className="chip-input" value={c.riskPercent}
                     onChange={(e) => set("riskPercent", e.target.value)} />
            </div>
            {overLiveCap ? (
              <span className="field-note">
                A live account is capped at {LIVE_RISK_CAP}% per trade. This can start on demo, not on live.
              </span>
            ) : null}
          </div>
          <div className="grid grid-2">
            <label className="field"><span>Stop the day at <span className="hint">% down</span></span>
              <input type="number" step="0.5" min="0.5" max={DAILY_LOSS_CEILING}
                     aria-label="Stop the day at"
                     value={c.dailyLossPercent}
                     onChange={(e) => set("dailyLossPercent", e.target.value)} />
              <span className="field-note">
                No new entries once the day is this far down. The platform ceiling is {DAILY_LOSS_CEILING}%.
              </span>
            </label>
            <label className="field"><span>Stop loss <span className="hint">pips</span></span>
              <input type="number" min="1" max="500" step="1" aria-label="Stop loss pips"
                     value={c.stopLossPips}
                     onChange={(e) => set("stopLossPips", e.target.value)} />
            </label>
            <label className="field"><span>Take profit <span className="hint">pips</span></span>
              <input type="number" min="1" max="2000" step="1" aria-label="Take profit pips"
                     value={c.takeProfitPips}
                     onChange={(e) => set("takeProfitPips", e.target.value)} />
              <span className="field-note">Pips are the stop and target the engine uses exactly.</span>
            </label>
          </div>
          {lotNotice ? (
            <div className={lotNotice.tone === "warn" ? "notice notice-warn" : "field-note"}
                 role="status">{lotNotice.text}</div>
          ) : null}
          <p className="trade-est" aria-live="polite">
            Most one trade is sized to lose: <strong><CurrencyTicker value={amounts.perTrade} /></strong>
            {" · "}Day stops at: <strong><CurrencyTicker value={amounts.perDay} /></strong>
            <span className="muted"> (limits from the capital you allocated, not a forecast)</span>
          </p>
          <div className="field"><span>Who acts on a setup</span>
            <div className="level-grid" role="radiogroup" aria-label="Who acts on a setup">
              {AUTOMATION_LEVELS.map((l) => (
                <button key={l.id} type="button" role="radio" className="level"
                        aria-checked={c.level === l.id} onClick={() => set("level", l.id)}>
                  <strong>{l.label}</strong>
                  <span>{l.does} {l.doesNot}</span>
                </button>
              ))}
            </div>
            {!c.level ? <span className="field-note">Choose one. It is never picked for you.</span> : null}
          </div>
        </section>
      ) : null}

      {step === 3 ? (
        <section className="card" aria-labelledby="t-account">
          <div className="card-head"><h2 id="t-account"><span className="step-no">4</span> Account</h2></div>
          {accounts.result && !accounts.result.ok ? <ErrorNotice error={accounts.result} onRetry={accounts.reload} /> : null}
          {!accounts.result ? <Spinner label="Reading your accounts" /> : null}
          {status && !status.connected ? (
            <p>No broker connected yet. <Link href="/connect">Connect cTrader</Link> to run a strategy on an account.</p>
          ) : null}
          <div className="chips" role="radiogroup" aria-label="Account">
            <button type="button" role="radio" className="chip" data-mode="demo"
                    aria-checked={c.account === "demo"}
                    onClick={() => chooseAccount("demo")}>Demo</button>
            <button type="button" role="radio" className="chip" data-mode="live"
                    aria-checked={c.account === "live"}
                    onClick={() => chooseAccount("live")}>Live</button>
          </div>
          {status?.connected ? (
            <p className="muted trade-note">
              Connected: {status.accounts.map((a) => `#${a.ctid} ${a.mode === "live" ? "LIVE" : "demo"}`).join(", ") || "none"}.
            </p>
          ) : null}
          {pickErr ? <ErrorNotice error={pickErr} /> : null}
          {c.account === "live" && action.kind === "live_closed" ? (
            <div className="notice notice-warn" role="status">
              <strong>{action.label}.</strong> {action.reason}{" "}
              <Link href={action.href}>Open live access</Link>
            </div>
          ) : null}
          {c.account === "live" && action.kind === "live" ? (
            <p className="muted trade-note">
              The server has cleared live for account #{action.accountId}. A start still goes through the order gate.
            </p>
          ) : null}
          {c.account === "demo" && action.kind === "demo" ? (
            <p className="muted trade-note">Demo account #{action.accountId}. No live order is sent.</p>
          ) : null}
        </section>
      ) : null}

      {step === 4 ? (
        <section className="card" aria-labelledby="t-review">
          <div className="card-head"><h2 id="t-review"><span className="step-no">5</span> Review</h2></div>
          <dl className="trade-note">
            <div><dt>Symbols</dt><dd>{[c.symbol, ...c.also].filter(Boolean).join(", ") || "—"}</dd></div>
            <div><dt>Timeframe</dt><dd>{c.timeframe}</dd></div>
            <div><dt>Strategy</dt><dd>{c.strategy?.label ?? c.custom?.name ?? "—"}</dd></div>
            <div><dt>Capital allocated</dt><dd>{c.capitalAllocated || "—"}</dd></div>
            <div><dt>Risk per trade</dt><dd>{pct(c.riskPercent) || "—"}</dd></div>
            <div><dt>Max daily loss</dt><dd>{pct(c.dailyLossPercent) || "—"}</dd></div>
            <div><dt>Max open positions</dt><dd>{c.maxOpenPositions || "—"}</dd></div>
            <div><dt>Stop / target</dt><dd>{c.stopLossPips} / {c.takeProfitPips} pips</dd></div>
            <div><dt>Who acts</dt><dd>{levelLabel || "—"}</dd></div>
            <div><dt>Account</dt><dd>{c.account === "live" ? "Live" : c.account === "demo" ? "Demo" : "—"}</dd></div>
          </dl>
          <p className="muted trade-note">
            {catalogue?.tradedSymbolNote}
            {" "}{catalogue?.disclaimer
              ?? "Past performance does not guarantee future results."}
          </p>
          {lotNotice ? <div className="notice notice-warn" role="status">{lotNotice.text}</div> : null}
          {c.account === "live" && action.kind === "live_closed" ? (
            <div className="notice notice-warn" role="status">
              <strong>{action.label}.</strong> {action.reason}{" "}
              <Link href={action.href}>{action.label}</Link>
            </div>
          ) : null}
        </section>
      ) : null}

      {err ? <ErrorNotice error={err} /> : null}
      {note ? <div className="notice notice-warn" role="status">{note}</div> : null}

      <div className="trade-bar" role="region" aria-label="Setup">
        <div className="trade-bar-sum">
          <span className="label-xs">Step {step + 1} of {STEPS.length}</span>
          <span>{summary || "Nothing chosen yet"}</span>
        </div>
        <span className="btn-row">
          {step > 0 ? (
            <button type="button" className="btn btn-ghost" onClick={() => setStep((n) => n - 1)}>Back</button>
          ) : null}
          {step < 4 ? (
            <button type="button" className="btn" disabled={!!block}
                    onClick={() => setStep((n) => n + 1)}>Continue</button>
          ) : action.kind === "demo" || action.kind === "live" ? (
            <ConfirmAction
              label={action.label}
              question={action.kind === "live"
                ? `Start on LIVE account #${action.accountId}? Real money moves.`
                : `Start on demo account #${action.accountId}?`}
              onConfirm={go}
              disabled={!!stepBlock(2, c) || !!running || !c.symbol}
              disabledReason={running
                ? "Automation is already running. Stop it from the dashboard before starting another."
                : stepBlock(2, c) ?? undefined}
              danger={action.kind === "live"}
            />
          ) : action.kind === "live_closed" ? (
            <Link className="btn" href={action.href}>{action.label}</Link>
          ) : (
            <Link className="btn" href="/connect">{action.label}</Link>
          )}
        </span>
        {step < 4 && block ? <span className="muted" style={{ fontSize: ".8rem" }}>{block}</span> : null}
      </div>
    </main>
  );
}

/** The symbols read, named here so the page does not import the type twice. */
type SymbolsReadish = Parameters<typeof symbolView>[0];
