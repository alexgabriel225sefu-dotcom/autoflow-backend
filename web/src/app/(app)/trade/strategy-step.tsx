"use client";
import Link from "next/link";
import { Check } from "lucide-react";
import type { ApiError, RuleSummary, SetupLibrary, StrategyPreset } from "@/lib/api";
import { ErrorNotice, Spinner } from "@/components/app/state";
import { SegmentedControl } from "@/components/app/segmented";
import { onSpot } from "@/components/app/spotlight";
import type { FamilyGroup } from "../rules/new/strategy/catalog";
import type { CustomMethod, TradeChoice } from "./trade-model";

/**
 * Step 2. Every offered strategy, what it refuses, the candles it reads, and
 * the fact that no backtest figure is published. Withheld strategies are
 * shown with the reason they cannot be chosen.
 */
export function StrategyStep({
  lib, strategies, groups, shown, family, setFamily, tab, setTab,
  myRules, myMethods, methodErr, open, setOpen, choice, onPick, onMethod,
}: {
  lib: { result: { ok: true; data: SetupLibrary } | { ok: false } | null; reload: () => void };
  strategies: StrategyPreset[];
  groups: FamilyGroup[];
  shown: FamilyGroup[];
  family: string;
  setFamily: (v: string) => void;
  tab: "ready" | "mine";
  setTab: (v: "ready" | "mine") => void;
  myRules: { result: { ok: true } | { ok: false } | null; reload: () => void };
  myMethods: RuleSummary[];
  methodErr: ApiError | null;
  open: string;
  setOpen: (id: string) => void;
  choice: TradeChoice;
  onPick: (s: StrategyPreset) => void;
  onMethod: (r: RuleSummary) => void;
}) {
  const catalogue = lib.result && lib.result.ok ? lib.result.data : null;
  const custom = choice.custom as CustomMethod | null;
  return (
    <section className="card" aria-labelledby="t-strategy">
      <div className="card-head">
        <h2 id="t-strategy"><span className="step-no">2</span> Strategy</h2>
        <span className="dim" style={{ fontSize: ".75rem" }}>
          {strategies.length ? `${strategies.length} strategies` : ""}
        </span>
      </div>
      {lib.result && !lib.result.ok ? <ErrorNotice error={lib.result as ApiError} onRetry={lib.reload} /> : null}
      {!lib.result ? <Spinner label="Reading the engine's strategies" /> : null}
      {lib.result && lib.result.ok && strategies.length === 0 ? (
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
            The instrument, risk and account come from this setup.
          </p>
          {myRules.result && !myRules.result.ok
            ? <ErrorNotice error={myRules.result as ApiError} onRetry={myRules.reload} /> : null}
          {myMethods.length === 0 && myRules.result && myRules.result.ok
            ? <p>You have not built a method yet.</p> : null}
          <div className="strat-grid" role="radiogroup" aria-label="My methods">
            {myMethods.map((r) => (
              <div key={r.ruleDocId} className="strat spot" data-chosen={custom?.ruleDocId === r.ruleDocId}
                   onPointerMove={onSpot} onPointerDown={onSpot}>
                <button type="button" role="radio" className="strat-pick"
                        aria-checked={custom?.ruleDocId === r.ruleDocId}
                        onClick={() => onMethod(r)}>
                  <span className="strat-title">
                    <strong>{r.name || "Untitled method"}</strong>
                    {custom?.ruleDocId === r.ruleDocId ? <Check className="ico" aria-hidden /> : null}
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
        <SegmentedControl
          label="Strategy family"
          value={family}
          onChange={setFamily}
          options={[
            { value: "all", label: "All" },
            ...groups.map((g) => ({ value: g.family, label: g.label })),
          ]}
        />
      ) : null}
      {tab === "ready" ? (
        <div className="strat-grid" role="radiogroup" aria-label="Strategy">
          {shown.flatMap((g) => g.strategies).map((s) => (
            <div key={s.id} className="strat spot" data-chosen={choice.strategy?.id === s.id}
                 onPointerMove={onSpot} onPointerDown={onSpot}>
              <button type="button" role="radio" className="strat-pick"
                      aria-checked={choice.strategy?.id === s.id}
                      onClick={() => onPick(s)}>
                <span className="strat-title">
                  <strong>{s.label}</strong>
                  {choice.strategy?.id === s.id ? <Check className="ico" aria-hidden /> : null}
                </span>
                <span className="strat-what">{s.what}</span>
                <span className="strat-refuses"><strong>Will not trade:</strong> {s.refuses}</span>
                <span className="strat-refuses">
                  <strong>Timeframe:</strong> {s.timeframeNote || "Runs on the timeframe you chose."}
                </span>
                <span className="strat-refuses">
                  {s.backtest
                    ? `Stored backtest: ${s.backtest.trades} closed trades. ${s.backtest.note}`
                    : "No stored backtest."}
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
      {(catalogue?.withheld ?? []).filter((w) => w.kind !== "rule_builder").map((w) => (
        <div key={w.id} className="record" style={{ marginTop: ".6rem" }}>
          <strong>{w.label}</strong>
          <p className="muted" style={{ margin: ".3rem 0 0" }}>{w.reason}</p>
        </div>
      ))}
      <p className="muted trade-note">
        No stored backtest is published for these strategies.
        {" "}{catalogue?.disclaimer ?? "Past performance does not guarantee future results."}
      </p>
    </section>
  );
}
