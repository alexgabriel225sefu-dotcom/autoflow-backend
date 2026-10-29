"use client";
import { useMemo, useState } from "react";
import Link from "next/link";
import { Check } from "lucide-react";
import {
  api, type ApiError, type AutomationState, type CtraderStatus, type Me,
  type MinLotRead, type RuleDoc, type RuleSummary, type StrategyCatalogue, type SymbolsRead,
} from "@/lib/api";
import { invalidate, useRead } from "@/lib/use-api";
import { useDebounced } from "@/lib/use-debounced";
import { ConfirmAction } from "@/components/app/shell";
import { fireStartConfetti } from "@/components/app/start-confetti";
import { runAutomationControl } from "@/components/app/automation-control";
import { AUTOMATION_LEVELS } from "@/components/app/plain";
import { ErrorNotice, Spinner } from "@/components/app/state";
import { groupByFamily } from "../rules/new/strategy/catalog";
import {
  DAILY_LOSS_CEILING, EMPTY_CHOICE, LIVE_RISK_CAP, RISK_PICKS, ROW_LIMIT,
  TIMEFRAME_CHOICES, minLotNotice, minLotPath, missingChoices, riskAmounts, startState, symbolView,
  tradeBody, type TradeChoice,
} from "./trade-model";

/**
 * Trade: pick what to trade, how much to risk, and start.
 *
 * This is the product's front door. A client does not write rules here; they
 * choose an instrument, one of the engine's own strategies, a risk, and who
 * acts on a setup, and the page does the rest (a saved rule, an activation, a
 * start). The rule builder stays for people who want their own conditions.
 *
 * WHAT IS DELIBERATELY NOT HERE
 *  - Results of any strategy. The platform has no published backtest, and a
 *    number here would be invented. Each card says what the strategy does and
 *    what it will NOT trade, which is what the server can actually vouch for.
 *  - A balance. The browser is never handed one, so the money figures are an
 *    estimate from a size the client types, and say so.
 *  - Any way to start live that the server has not already allowed. The Start
 *    button is whatever `startState` says it is, from the server's answers.
 */

const pct = (v: string) => (v.trim() === "" ? "" : `${v.trim()}%`);
const money = (n: number | null) =>
  n === null ? "—" : n.toLocaleString("en-US", { style: "currency", currency: "USD" });

export default function TradePage() {
  const cat = useRead<StrategyCatalogue>("strategies");
  const accounts = useRead<CtraderStatus>("ctrader/status");
  const me = useRead<Me>("me");
  const auto = useRead<AutomationState>("automation", 30_000);
  const broker = useRead<SymbolsRead>("symbols");
  const myRules = useRead<{ rules: RuleSummary[] }>("rules");

  const [c, setC] = useState<TradeChoice>(EMPTY_CHOICE);
  const [family, setFamily] = useState<string>("all");
  const [open, setOpen] = useState<string>("");
  const [err, setErr] = useState<ApiError | null>(null);
  const [orphan, setOrphan] = useState<string>("");
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
  const start = startState({ status, execution });
  const missing = missingChoices(c);
  const amounts = riskAmounts(c);
  // Whether the broker's smallest order would risk more than the chosen
  // percentage. Asked once the choices settle, never on every keystroke.
  const minLot = useRead<MinLotRead>(useDebounced(minLotPath(c), 400));
  const lotNotice = minLot.result?.ok ? minLotNotice(minLot.result.data, c) : null;
  const running = auto.result?.ok && auto.result.data.state === "running";
  const catalogue = cat.result?.ok ? cat.result.data : null;
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

  /** Load the client's own rule and take its conditions as the method. */
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

  /** Save, activate and start, stopping at the first thing that refuses and
   *  saying which step it was. Never reports a start the server did not make. */
  async function go(): Promise<string> {
    setErr(null); setOrphan("");
    let body;
    try { body = tradeBody(c); } catch { return "Choose a strategy first."; }

    const created = await api<{ rule: RuleDoc }>("rules", { method: "POST", body });
    if (!created.ok) { setErr(created); return "Not started: the rule could not be saved."; }
    const id = created.data.rule.ruleDocId;

    const saved = await api(`rules/${id}`, { method: "PUT", body });
    if (!saved.ok) {
      setErr(saved); setOrphan(id);
      return "Not started: the strategy could not be saved onto the rule.";
    }
    const activated = await api(`rules/${id}/activate`, { method: "POST" });
    if (!activated.ok) {
      setErr(activated); setOrphan(id);
      return "Not started: the rule was saved but could not be activated.";
    }
    invalidate("rules", "me");
    const res = await runAutomationControl("start", {
      ruleDocId: id, reload: auto.reload,
    });
    if (!res.ok) setOrphan(id);
    else fireStartConfetti();
    return res.text;
  }

  const ready = missing.length === 0;
  const blockedBy = !ready ? `Still to choose: ${missing.join(", ")}.`
    : running ? "Automation is already running. Stop it from the dashboard before starting another."
    : null;

  const summary = [
    c.symbol || null,
    c.strategy?.label ?? (c.custom ? `${c.custom.name} (my method)` : null), c.timeframe,
    c.riskPercent ? `${pct(c.riskPercent)} per trade` : null,
    AUTOMATION_LEVELS.find((l) => l.id === c.level)?.label,
  ].filter(Boolean).join(" · ");

  return (
    <main className="trade">
      <div className="page-head">
        <div>
          <h1>Trade</h1>
          <span className="sub">
            Choose what to trade and how much to risk. Nothing trades until you press Start.
          </span>
        </div>
      </div>

      <section className="card" aria-labelledby="t-market">
        <div className="card-head"><h2 id="t-market"><span className="step-no">1</span> Market</h2></div>
        <div className="field"><span>Instrument</span>
          <input type="search" placeholder="Search your broker's instruments, e.g. EURUSD, XAU, US30"
                 aria-label="Search instruments" value={query}
                 onChange={(e) => setQuery(e.target.value)} />
        </div>
        {view.classes.length > 1 ? (
          <div className="chips" role="radiogroup" aria-label="Instrument class">
            <button type="button" role="radio" className="chip" aria-checked={symClass === "all"}
                    onClick={() => setSymClass("all")}>All</button>
            {view.classes.map((k) => (
              <button key={k.id} type="button" role="radio" className="chip"
                      aria-checked={symClass === k.id}
                      onClick={() => setSymClass(k.id)}>{k.label} · {k.count}</button>
            ))}
          </div>
        ) : null}
        {!broker.result ? <Spinner label="Reading your broker's instruments" /> : null}
        <div className="chips chips-symbols" role="radiogroup" aria-label="Instrument">
          {view.rows.map((r) => (
            <button key={r.id} type="button" role="radio" className="chip"
                    aria-checked={c.symbol === r.id}
                    aria-disabled={!r.tradeable}
                    disabled={!r.tradeable}
                    title={r.reason ?? undefined}
                    onClick={() => set("symbol", r.id)}>{r.id}</button>
          ))}
        </div>
        {view.rows.length === 0 && broker.result ? (
          <p className="muted trade-note">No instrument matches. Clear the search or the class.</p>
        ) : null}
        {view.matches > ROW_LIMIT ? (
          <p className="muted trade-note">
            Showing {ROW_LIMIT} of {view.matches}. Search to narrow it down.
          </p>
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
        <div className="field"><span>Timeframe</span>
          <div className="chips" role="radiogroup" aria-label="Timeframe">
            {TIMEFRAME_CHOICES.map((t) => (
              <button key={t} type="button" role="radio" className="chip"
                      aria-checked={c.timeframe === t}
                      onClick={() => set("timeframe", t)}>{t}</button>
            ))}
          </div>
        </div>
      </section>

      <section className="card" aria-labelledby="t-strategy">
        <div className="card-head">
          <h2 id="t-strategy"><span className="step-no">2</span> Strategy</h2>
          <span className="dim" style={{ fontSize: ".75rem" }}>
            {strategies.length ? `${strategies.length} strategies` : ""}
          </span>
        </div>
        {cat.result && !cat.result.ok ? <ErrorNotice error={cat.result} onRetry={cat.reload} /> : null}
        {!cat.result ? <Spinner label="Reading the engine's strategies" /> : null}
        {cat.result?.ok && strategies.length === 0 ? (
          <div className="notice notice-warn" role="alert">
            The strategy list could not be read, so there is nothing to choose from.
          </div>
        ) : null}
        <div className="chips" role="tablist" aria-label="Where the method comes from">
          <button type="button" role="tab" className="chip" aria-selected={tab === "ready"}
                  onClick={() => setTab("ready")}>
            Ready-made{strategies.length ? ` · ${strategies.length}` : ""}
          </button>
          <button type="button" role="tab" className="chip" aria-selected={tab === "mine"}
                  onClick={() => setTab("mine")}>
            My methods{myMethods.length ? ` · ${myMethods.length}` : ""}
          </button>
        </div>
        {tab === "mine" ? (
          <div role="tabpanel" aria-label="My methods">
            <p className="muted trade-note">
              A method of your own is a set of entry and exit conditions you built.
              The instrument, risk and account come from this page, and the conditions
              are taken from the method as they are now.
            </p>
            {myRules.result && !myRules.result.ok ? <ErrorNotice error={myRules.result} onRetry={myRules.reload} /> : null}
            {myMethods.length === 0 && myRules.result?.ok ? (
              <p>You have not built a method yet.</p>
            ) : null}
            <div className="strat-grid" role="radiogroup" aria-label="My methods">
              {myMethods.map((r) => (
                <div key={r.ruleDocId} className="strat" data-chosen={c.custom?.ruleDocId === r.ruleDocId}>
                  <button type="button" role="radio" className="strat-pick"
                          aria-checked={c.custom?.ruleDocId === r.ruleDocId}
                          onClick={() => void pickMethod(r)}>
                    <span className="strat-title">
                      <strong>{r.name || "Untitled method"}</strong>
                      {c.custom?.ruleDocId === r.ruleDocId ? <Check className="ico" aria-hidden /> : null}
                    </span>
                    <span className="strat-what">
                      {r.entryConditions} entry and {r.exitConditions ?? 0} exit condition
                      {(r.entryConditions ?? 0) + (r.exitConditions ?? 0) === 1 ? "" : "s"}
                    </span>
                    <span className="strat-refuses">
                      Built on {r.symbols?.join(", ") || "no instrument"} · {r.timeframe}
                    </span>
                  </button>
                  <Link className="btn btn-ghost btn-sm" href={`/rules/${r.ruleDocId}`}>Open the method</Link>
                </div>
              ))}
            </div>
            {methodErr ? <ErrorNotice error={methodErr} /> : null}
            <p className="trade-note">
              <Link className="btn btn-ghost btn-sm" href="/rules/new">Build a new method</Link>
            </p>
          </div>
        ) : null}
        {tab === "ready" && groups.length > 1 ? (
          <div className="chips" role="radiogroup" aria-label="Strategy family">
            <button type="button" role="radio" className="chip" aria-checked={family === "all"}
                    onClick={() => setFamily("all")}>All</button>
            {groups.map((g) => (
              <button key={g.family} type="button" role="radio" className="chip"
                      aria-checked={family === g.family}
                      onClick={() => setFamily(g.family)}>{g.label}</button>
            ))}
          </div>
        ) : null}
        {tab === "ready" ? (
        <div className="strat-grid" role="radiogroup" aria-label="Strategy">
          {shown.flatMap((g) => g.strategies).map((s) => (
            <div key={s.id} className="strat" data-chosen={c.strategy?.id === s.id}>
              <button type="button" role="radio" className="strat-pick"
                      aria-checked={c.strategy?.id === s.id}
                      onClick={() => setC((x) => ({ ...x, strategy: s, custom: null }))}>
                <span className="strat-title">
                  <strong>{s.label}</strong>
                  {c.strategy?.id === s.id ? <Check className="ico" aria-hidden /> : null}
                </span>
                <span className="strat-what">{s.what}</span>
                <span className="strat-refuses">
                  <strong>Will not trade:</strong> {s.refuses}
                </span>
              </button>
              <button type="button" className="btn btn-ghost btn-sm"
                      aria-expanded={open === s.id}
                      onClick={() => setOpen(open === s.id ? "" : s.id)}>
                {open === s.id ? "Hide how it decides" : "How it decides"}
              </button>
              {open === s.id ? <p className="strat-decides">{s.decides}</p> : null}
            </div>
          ))}
        </div>
        ) : null}
        <p className="muted trade-note">
          Past behaviour does not predict future results, and no result is shown here
          because none has been published. Each card says what the strategy does and
          what it will not trade.
        </p>
      </section>

      <section className="card" aria-labelledby="t-risk">
        <div className="card-head"><h2 id="t-risk"><span className="step-no">3</span> Risk</h2></div>
        <div className="field"><span>Risk per trade <span className="hint">% of balance</span></span>
          <div className="chips" role="radiogroup" aria-label="Risk per trade">
            {RISK_PICKS.map((r) => (
              <button key={r} type="button" role="radio" className="chip"
                      aria-checked={c.riskPercent === r}
                      onClick={() => set("riskPercent", r)}>{r}%</button>
            ))}
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
            <input type="number" step="0.5" min="0.5" max={DAILY_LOSS_CEILING} placeholder="account default"
                   value={c.dailyLossPercent}
                   onChange={(e) => set("dailyLossPercent", e.target.value)} />
            <span className="field-note">
              No new entries once the day is this far down. The platform&apos;s own ceiling is {DAILY_LOSS_CEILING}%.
            </span></label>
          <label className="field"><span>Account size <span className="hint">optional, for the estimate</span></span>
            <input type="number" min="0" step="100" placeholder="e.g. 10000" value={c.accountSize}
                   onChange={(e) => set("accountSize", e.target.value)} />
            <span className="field-note">Used only below. It is not read from your broker and is not saved.</span></label>
        </div>
        {lotNotice ? (
          <div className={lotNotice.tone === "warn" ? "notice notice-warn" : "field-note"}
               role="status">{lotNotice.text}</div>
        ) : null}
        <p className="trade-est" aria-live="polite">
          Most one trade is sized to lose: <strong>{money(amounts.perTrade)}</strong>
          {" · "}Day stops at: <strong>{money(amounts.perDay)}</strong>
          <span className="muted"> (limits from the size you typed, not a forecast)</span>
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

      <section className="card" aria-labelledby="t-account">
        <div className="card-head"><h2 id="t-account"><span className="step-no">4</span> Account</h2></div>
        {accounts.result && !accounts.result.ok ? <ErrorNotice error={accounts.result} onRetry={accounts.reload} /> : null}
        {!accounts.result ? <Spinner label="Reading your accounts" /> : null}
        {status && !status.connected ? (
          <p>No broker connected yet. <Link href="/connect">Connect cTrader</Link> to run a strategy on an account.</p>
        ) : null}
        {status?.connected ? (
          <div className="chips" role="radiogroup" aria-label="Account">
            {status.accounts.map((a) => (
              <button key={String(a.ctid)} type="button" role="radio" className="chip"
                      data-mode={a.mode}
                      aria-checked={String(status.selected?.ctid) === String(a.ctid)}
                      onClick={() => void pick(a.ctid)}>
                #{String(a.ctid)} · {a.mode === "live" ? "LIVE" : "Demo"}
              </button>
            ))}
          </div>
        ) : null}
        {pickErr ? <ErrorNotice error={pickErr} /> : null}
        {start.kind === "live_closed" ? (
          <div className="notice notice-warn" role="status">
            <strong>{start.label}.</strong> {start.reason}{" "}
            <Link href={start.href}>Open live access</Link>
          </div>
        ) : null}
      </section>

      {err ? <ErrorNotice error={err} /> : null}
      {orphan ? (
        <div className="notice notice-warn" role="alert">
          The rule was saved but did not start. <Link href={`/rules/${orphan}`}>Open it</Link> to
          see where it stopped.
        </div>
      ) : null}

      <div className="trade-bar" role="region" aria-label="Start">
        <div className="trade-bar-sum">
          <span className="label-xs">Your setup</span>
          <span>{summary || "Nothing chosen yet"}</span>
        </div>
        {start.kind === "demo" || start.kind === "live" ? (
          <ConfirmAction
            label={start.label}
            question={start.kind === "live"
              ? `Start on LIVE account #${start.accountId}? Real money moves.`
              : `Start on demo account #${start.accountId}?`}
            onConfirm={go}
            disabled={!ready || !!running}
            disabledReason={blockedBy ?? undefined}
            danger={start.kind === "live"}
          />
        ) : start.kind === "live_closed" ? (
          <Link className="btn" href={start.href}>{start.label}</Link>
        ) : (
          <Link className="btn" href="/connect">{start.label}</Link>
        )}
      </div>
    </main>
  );
}
