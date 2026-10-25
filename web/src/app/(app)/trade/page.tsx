"use client";
import { useMemo, useState } from "react";
import Link from "next/link";
import { Check } from "lucide-react";
import {
  api, type ApiError, type AutomationState, type CtraderStatus, type Me,
  type RuleDoc, type StrategyCatalogue,
} from "@/lib/api";
import { invalidate, useRead } from "@/lib/use-api";
import { ConfirmAction } from "@/components/app/shell";
import { runAutomationControl } from "@/components/app/automation-control";
import { AUTOMATION_LEVELS } from "@/components/app/plain";
import { ErrorNotice, Spinner } from "@/components/app/state";
import { groupByFamily } from "../rules/new/strategy/catalog";
import {
  DAILY_LOSS_CEILING, EMPTY_CHOICE, LIVE_RISK_CAP, RISK_PICKS, SYMBOLS,
  TIMEFRAME_CHOICES, missingChoices, riskAmounts, startState, tradeBody,
  type TradeChoice,
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

  const [c, setC] = useState<TradeChoice>(EMPTY_CHOICE);
  const [family, setFamily] = useState<string>("all");
  const [open, setOpen] = useState<string>("");
  const [err, setErr] = useState<ApiError | null>(null);
  const [orphan, setOrphan] = useState<string>("");
  const [pickErr, setPickErr] = useState<ApiError | null>(null);
  const set = <K extends keyof TradeChoice>(k: K, v: TradeChoice[K]) =>
    setC((x) => ({ ...x, [k]: v }));

  const status = accounts.result?.ok ? accounts.result.data : null;
  const execution = me.result?.ok ? me.result.data.execution : null;
  const start = startState({ status, execution });
  const missing = missingChoices(c);
  const amounts = riskAmounts(c);
  const running = auto.result?.ok && auto.result.data.state === "running";
  const catalogue = cat.result?.ok ? cat.result.data : null;
  const strategies = useMemo(() => catalogue?.strategies ?? [], [catalogue]);
  const groups = useMemo(() => groupByFamily(strategies), [strategies]);
  const shown = family === "all" ? groups : groups.filter((g) => g.family === family);
  const overLiveCap = Number(c.riskPercent) > LIVE_RISK_CAP;

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
    return res.text;
  }

  const ready = missing.length === 0;
  const blockedBy = !ready ? `Still to choose: ${missing.join(", ")}.`
    : running ? "Automation is already running. Stop it from the dashboard before starting another."
    : null;

  const summary = [
    c.symbol ? SYMBOLS.find((s) => s.id === c.symbol)?.label : null,
    c.strategy?.label, c.timeframe,
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
        {(["Forex", "Metals"] as const).map((g) => (
          <div className="field" key={g}><span>{g}</span>
            <div className="chips" role="radiogroup" aria-label={g}>
              {SYMBOLS.filter((s) => s.group === g).map((s) => (
                <button key={s.id} type="button" role="radio" className="chip"
                        aria-checked={c.symbol === s.id}
                        onClick={() => set("symbol", s.id)}>{s.label}</button>
              ))}
            </div>
          </div>
        ))}
        <div className="field"><span>Timeframe</span>
          <div className="chips" role="radiogroup" aria-label="Timeframe">
            {TIMEFRAME_CHOICES.map((t) => (
              <button key={t} type="button" role="radio" className="chip"
                      aria-checked={c.timeframe === t}
                      onClick={() => set("timeframe", t)}>{t}</button>
            ))}
          </div>
        </div>
        <p className="muted trade-note">
          Forex pairs with a USD leg, plus gold and silver. Indices are not offered:
          the engine has no exchange calendars for them.
        </p>
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
        {groups.length > 1 ? (
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
        <div className="strat-grid" role="radiogroup" aria-label="Strategy">
          {shown.flatMap((g) => g.strategies).map((s) => (
            <div key={s.id} className="strat" data-chosen={c.strategy?.id === s.id}>
              <button type="button" role="radio" className="strat-pick"
                      aria-checked={c.strategy?.id === s.id}
                      onClick={() => set("strategy", s)}>
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
