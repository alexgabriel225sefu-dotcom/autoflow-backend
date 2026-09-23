"use client";
/**
 * The rule editor — the whole document, not the part that was easy.
 *
 * The previous builder submitted name, symbols, timeframe, sides, entry and
 * exit. Everything else took a server default: 1.0% risk, a 1.5× ATR stop, a
 * 2.0 RR target, one open position. A client could not see those numbers and
 * could not change them, which sits badly against a product whose promise is
 * to respect the limits the client switched on.
 *
 * Fields the engine does not honour yet are shown and labelled as such rather
 * than hidden, and fields that would make execution refuse the order say so
 * next to the input instead of at the first failed trade.
 */
import type { ConditionSpec, RuleDoc } from "@/lib/api";
import { ConditionEditor, defaultsFor, type ConditionValue } from "./condition-editor";

export const TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"];
const DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export type Draft = {
  name: string;
  symbols: string;
  timeframe: string;
  sides: string;
  evaluateOn: string;
  entryCombine: string;
  entry: ConditionValue[];
  exitCombine: string;
  exit: ConditionValue[];
  sizingMode: string;
  riskPercent: string;
  fixedVolume: string;
  slMode: string;
  slAtrMultiple: string;
  slPips: string;
  tpMode: string;
  tpRr: string;
  tpPips: string;
  trailEnabled: boolean;
  trailAtrMultiple: string;
  beEnabled: boolean;
  beAtR: string;
  maxOpenPositions: string;
  maxDailyTrades: string;
  maxExposurePercent: string;
  maxSpreadPips: string;
  onLimit: string;
  days: number[];
  windowFrom: string;
  windowTo: string;
  orderType: string;
  maxSlippagePoints: string;
  expiresAfterSec: string;
};

/** The same defaults the server would apply, made visible instead of implied. */
export const BLANK: Draft = {
  name: "", symbols: "EURUSD", timeframe: "1h", sides: "BOTH", evaluateOn: "bar_close",
  entryCombine: "AND", entry: [], exitCombine: "OR", exit: [],
  sizingMode: "risk_percent", riskPercent: "1.0", fixedVolume: "0.1",
  slMode: "atr", slAtrMultiple: "1.5", slPips: "20",
  tpMode: "rr", tpRr: "2.0", tpPips: "40",
  trailEnabled: false, trailAtrMultiple: "2.0",
  beEnabled: false, beAtR: "1.0",
  maxOpenPositions: "1", maxDailyTrades: "", maxExposurePercent: "", maxSpreadPips: "",
  onLimit: "block",
  days: [], windowFrom: "", windowTo: "",
  orderType: "MARKET", maxSlippagePoints: "", expiresAfterSec: "",
};

const num = (v: string): number | undefined => {
  const t = v.trim();
  if (t === "") return undefined;
  const n = Number(t);
  return Number.isNaN(n) ? undefined : n;
};

/** A draft as the document shape the API and the summary both understand. */
export function toDoc(d: Draft): Partial<RuleDoc> {
  const windows = d.windowFrom && d.windowTo ? [{ from: d.windowFrom, to: d.windowTo }] : [];
  return {
    name: d.name,
    symbols: d.symbols.split(",").map((s) => s.trim()).filter(Boolean),
    timeframe: d.timeframe,
    sides: d.sides,
    evaluateOn: d.evaluateOn,
    entry: { combine: d.entryCombine, conditions: d.entry },
    exit: { combine: d.exitCombine, conditions: d.exit },
    order: {
      type: d.orderType,
      maxSlippagePoints: num(d.maxSlippagePoints) ?? null,
      expiresAfterSec: num(d.expiresAfterSec) ?? null,
    },
    sizing: d.sizingMode === "fixed_volume"
      ? { mode: "fixed_volume", fixedVolume: num(d.fixedVolume) ?? null, riskPercent: null }
      : { mode: "risk_percent", riskPercent: num(d.riskPercent) ?? null, fixedVolume: null },
    stopLoss: d.slMode === "pips"
      ? { mode: "pips", pips: num(d.slPips) ?? null, atrMultiple: null }
      : { mode: "atr", atrMultiple: num(d.slAtrMultiple) ?? null, pips: null },
    takeProfit: d.tpMode === "none"
      ? { mode: null, rr: null, pips: null }
      : d.tpMode === "pips"
        ? { mode: "pips", pips: num(d.tpPips) ?? null, rr: null }
        : { mode: "rr", rr: num(d.tpRr) ?? null, pips: null },
    trailingStop: { enabled: d.trailEnabled, atrMultiple: d.trailEnabled ? num(d.trailAtrMultiple) ?? null : null },
    breakEven: { enabled: d.beEnabled, atR: d.beEnabled ? num(d.beAtR) ?? null : null },
    limits: {
      maxOpenPositions: num(d.maxOpenPositions) ?? 1,
      maxDailyTrades: num(d.maxDailyTrades) ?? null,
      maxExposurePercent: num(d.maxExposurePercent) ?? null,
      maxSpreadPips: num(d.maxSpreadPips) ?? null,
      onLimit: d.onLimit,
    },
    schedule: { timezone: "UTC", days: d.days, windows },
  } as Partial<RuleDoc>;
}

function Seg({
  value, options, onChange, tones,
}: {
  value: string;
  options: string[];
  onChange: (v: string) => void;
  tones?: Record<string, "long" | "short">;
}) {
  return (
    <div className="seg" role="group">
      {options.map((o) => (
        <button key={o} type="button" aria-pressed={value === o}
                data-tone={tones?.[o]} onClick={() => onChange(o)}>
          {o}
        </button>
      ))}
    </div>
  );
}

function Section({
  title, note, children,
}: { title: string; note?: string; children: React.ReactNode }) {
  return (
    <section className="card">
      <div className="card-head" style={{ marginBottom: note ? ".3rem" : ".7rem" }}>
        <h2>{title}</h2>
      </div>
      {note ? (
        <p className="muted" style={{ fontSize: ".8rem", marginBottom: ".7rem" }}>{note}</p>
      ) : null}
      {children}
    </section>
  );
}

function ConditionList({
  title, specs, combine, onCombine, list, onList, emptyNote,
}: {
  title: string;
  specs: Record<string, ConditionSpec>;
  combine: string;
  onCombine: (v: string) => void;
  list: ConditionValue[];
  onList: (v: ConditionValue[]) => void;
  emptyNote: string;
}) {
  const first = Object.keys(specs).sort()[0];
  return (
    <section className="card">
      <div className="card-head">
        <h2>{title}</h2>
        <span className="btn-row">
          <span className="label-xs">Combine</span>
          <Seg value={combine} options={["AND", "OR"]} onChange={onCombine} />
        </span>
      </div>
      {list.length === 0 ? <p className="empty">{emptyNote}</p> : null}
      {list.map((c, i) => (
        <ConditionEditor
          key={i} specs={specs} value={c}
          onChange={(v) => onList(list.map((x, j) => (j === i ? v : x)))}
          onRemove={() => onList(list.filter((_, j) => j !== i))}
        />
      ))}
      <button
        type="button" className="btn btn-ghost btn-sm"
        style={{ marginTop: ".5rem" }}
        onClick={() => onList([...list, { id: first, params: defaultsFor(specs[first]) }])}
      >
        + Add condition
      </button>
    </section>
  );
}

export function RuleForm({
  draft, set, specs,
}: {
  draft: Draft;
  set: <K extends keyof Draft>(k: K, v: Draft[K]) => void;
  specs: Record<string, ConditionSpec>;
}) {
  const d = draft;

  return (
    <>
      <Section title="Basics">
        <div className="grid grid-2">
          <label className="field"><span>Name</span>
            <input value={d.name} placeholder="EURUSD trend continuation"
                   onChange={(e) => set("name", e.target.value)} /></label>
          <label className="field">
            <span>Instruments <span className="hint">comma separated</span></span>
            <input value={d.symbols} placeholder="EURUSD, XAUUSD"
                   onChange={(e) => set("symbols", e.target.value)} /></label>
        </div>
        <div className="grid grid-2">
          <label className="field"><span>Timeframe</span>
            <select value={d.timeframe} onChange={(e) => set("timeframe", e.target.value)}>
              {TIMEFRAMES.map((t) => <option key={t} value={t}>{t}</option>)}
            </select></label>
          <div className="field"><span>Sides</span>
            <Seg value={d.sides} options={["BUY", "SELL", "BOTH"]}
                 tones={{ BUY: "long", SELL: "short" }}
                 onChange={(v) => set("sides", v)} />
            {d.sides === "BOTH" ? (
              <span className="field-note">
                With BOTH, the conditions must imply a direction or the engine
                refuses rather than guessing a side.
              </span>
            ) : null}
          </div>
        </div>
        <div className="field"><span>Evaluate</span>
          <Seg value={d.evaluateOn} options={["bar_close", "intrabar"]}
               onChange={(v) => set("evaluateOn", v)} />
          <span className="field-note">
            {d.evaluateOn === "intrabar"
              ? "An intrabar evaluation can fire on a price the bar never closes at."
              : "On bar close: the decision is taken on a price the bar actually ended at."}
          </span>
        </div>
      </Section>

      <ConditionList
        title="Entry conditions" specs={specs}
        combine={d.entryCombine} onCombine={(v) => set("entryCombine", v)}
        list={d.entry} onList={(v) => set("entry", v)}
        emptyNote="No entry condition yet. A rule with none cannot open anything."
      />

      <ConditionList
        title="Exit conditions" specs={specs}
        combine={d.exitCombine} onCombine={(v) => set("exitCombine", v)}
        list={d.exit} onList={(v) => set("exit", v)}
        emptyNote="No exit condition. The stop and target will close the trade."
      />

      <Section
        title="Risk and size"
        note="How large a position this rule opens. Risk percent derives the size from the stop distance, so the stop and the size are one decision."
      >
        <div className="field"><span>Sizing</span>
          <Seg value={d.sizingMode} options={["risk_percent", "fixed_volume"]}
               onChange={(v) => set("sizingMode", v)} />
        </div>
        <div className="grid grid-2">
          {d.sizingMode === "risk_percent" ? (
            <label className="field"><span>Risk per trade <span className="hint">% of balance</span></span>
              <input type="number" step="0.1" min="0.1" max="100" value={d.riskPercent}
                     onChange={(e) => set("riskPercent", e.target.value)} /></label>
          ) : (
            <label className="field"><span>Volume <span className="hint">lots</span></span>
              <input type="number" step="0.01" min="0.01" value={d.fixedVolume}
                     onChange={(e) => set("fixedVolume", e.target.value)} /></label>
          )}
        </div>
      </Section>

      <Section
        title="Stop loss"
        note="Not optional. Without a stop the position has no defined worst case and the size cannot be derived from risk."
      >
        <div className="field"><span>Stop</span>
          <Seg value={d.slMode} options={["atr", "pips"]} onChange={(v) => set("slMode", v)} />
        </div>
        <div className="grid grid-2">
          {d.slMode === "atr" ? (
            <label className="field"><span>ATR multiple</span>
              <input type="number" step="0.1" min="0.1" value={d.slAtrMultiple}
                     onChange={(e) => set("slAtrMultiple", e.target.value)} /></label>
          ) : (
            <label className="field"><span>Distance <span className="hint">pips</span></span>
              <input type="number" step="1" min="1" value={d.slPips}
                     onChange={(e) => set("slPips", e.target.value)} /></label>
          )}
        </div>
      </Section>

      <Section title="Take profit" note="Optional. A rule may manage its exit with exit conditions instead.">
        <div className="field"><span>Target</span>
          <Seg value={d.tpMode} options={["rr", "pips", "none"]} onChange={(v) => set("tpMode", v)} />
        </div>
        <div className="grid grid-2">
          {d.tpMode === "rr" ? (
            <label className="field"><span>Reward : risk</span>
              <input type="number" step="0.1" min="0.1" value={d.tpRr}
                     onChange={(e) => set("tpRr", e.target.value)} />
              <span className="field-note">A multiple of the stop distance.</span></label>
          ) : d.tpMode === "pips" ? (
            <label className="field"><span>Distance <span className="hint">pips</span></span>
              <input type="number" step="1" min="1" value={d.tpPips}
                     onChange={(e) => set("tpPips", e.target.value)} /></label>
          ) : (
            <p className="muted" style={{ fontSize: ".82rem" }}>
              No target. The trade closes on an exit condition or on the stop.
            </p>
          )}
        </div>
      </Section>

      <Section
        title="Trade management"
        note="Stored on the rule and shown in its terms. The execution engine does not apply these yet, so they are recorded rather than enforced."
      >
        <label className="field-inline">
          <input type="checkbox" checked={d.trailEnabled}
                 onChange={(e) => set("trailEnabled", e.target.checked)} />
          <span>Trailing stop</span>
        </label>
        {d.trailEnabled ? (
          <label className="field" style={{ maxWidth: 260 }}>
            <span>Trail distance <span className="hint">ATR multiple</span></span>
            <input type="number" step="0.1" min="0.1" value={d.trailAtrMultiple}
                   onChange={(e) => set("trailAtrMultiple", e.target.value)} />
          </label>
        ) : null}
        <label className="field-inline">
          <input type="checkbox" checked={d.beEnabled}
                 onChange={(e) => set("beEnabled", e.target.checked)} />
          <span>Move stop to break even</span>
        </label>
        {d.beEnabled ? (
          <label className="field" style={{ maxWidth: 260 }}>
            <span>Trigger <span className="hint">R multiple</span></span>
            <input type="number" step="0.1" min="0.1" value={d.beAtR}
                   onChange={(e) => set("beAtR", e.target.value)} />
          </label>
        ) : null}
      </Section>

      <Section title="Limits" note="What this rule refuses to exceed. Leave a field empty for no cap.">
        <div className="grid grid-2">
          <label className="field"><span>Max open positions</span>
            <input type="number" step="1" min="1" value={d.maxOpenPositions}
                   onChange={(e) => set("maxOpenPositions", e.target.value)} /></label>
          <label className="field"><span>Max spread <span className="hint">pips</span></span>
            <input type="number" step="0.1" min="0" placeholder="no cap" value={d.maxSpreadPips}
                   onChange={(e) => set("maxSpreadPips", e.target.value)} />
            <span className="field-note">Entries are blocked while the spread is wider.</span></label>
          <label className="field"><span>Max trades per day</span>
            <input type="number" step="1" min="1" placeholder="no cap" value={d.maxDailyTrades}
                   onChange={(e) => set("maxDailyTrades", e.target.value)} />
            <span className="field-note">Recorded on the rule; not enforced by the engine yet.</span></label>
          <label className="field"><span>Max exposure <span className="hint">% of balance</span></span>
            <input type="number" step="1" min="1" placeholder="no cap" value={d.maxExposurePercent}
                   onChange={(e) => set("maxExposurePercent", e.target.value)} />
            <span className="field-note">Recorded on the rule; not enforced by the engine yet.</span></label>
        </div>
        <div className="field"><span>When a limit is hit</span>
          <Seg value={d.onLimit} options={["block", "flatten"]} onChange={(v) => set("onLimit", v)} />
          <span className="field-note">
            {d.onLimit === "flatten"
              ? "Close open positions as well as refusing new entries."
              : "Refuse new entries and keep managing the open ones."}
          </span>
        </div>
      </Section>

      <Section title="Schedule" note="All times are UTC, which is also what the evaluator uses. Leave empty to run whenever the market is open.">
        <div className="field"><span>Trading days</span>
          <div className="btn-row">
            {DAY_LABELS.map((lbl, i) => (
              <button
                key={lbl} type="button"
                className={d.days.includes(i) ? "btn btn-sm" : "btn btn-ghost btn-sm"}
                aria-pressed={d.days.includes(i)}
                onClick={() => set("days", d.days.includes(i)
                  ? d.days.filter((x) => x !== i)
                  : [...d.days, i].sort((a, b) => a - b))}
              >
                {lbl}
              </button>
            ))}
          </div>
          <span className="field-note">
            {d.days.length ? "Outside these days the rule refuses to enter." : "Every day."}
          </span>
        </div>
        <div className="grid grid-2">
          <label className="field"><span>Window from <span className="hint">HH:MM UTC</span></span>
            <input placeholder="07:00" value={d.windowFrom}
                   onChange={(e) => set("windowFrom", e.target.value)} /></label>
          <label className="field"><span>Window to <span className="hint">HH:MM UTC</span></span>
            <input placeholder="16:00" value={d.windowTo}
                   onChange={(e) => set("windowTo", e.target.value)} /></label>
        </div>
      </Section>

      <Section title="Order" note="How the order reaches the broker.">
        <div className="field"><span>Order type</span>
          <Seg value={d.orderType} options={["MARKET", "LIMIT", "STOP"]}
               onChange={(v) => set("orderType", v)} />
          {d.orderType !== "MARKET" ? (
            <span className="field-note" style={{ color: "var(--a4t-short)" }}>
              Only MARKET can be executed today. A rule set to {d.orderType} will
              be refused at execution rather than sent as a different order.
            </span>
          ) : null}
        </div>
        <div className="grid grid-2">
          <label className="field"><span>Max slippage <span className="hint">points</span></span>
            <input type="number" step="1" min="0" placeholder="not set" value={d.maxSlippagePoints}
                   onChange={(e) => set("maxSlippagePoints", e.target.value)} />
            {d.maxSlippagePoints.trim() ? (
              <span className="field-note" style={{ color: "var(--a4t-short)" }}>
                The execution path cannot honour this yet, so orders would be
                refused rather than sent without the ceiling you asked for.
              </span>
            ) : null}
          </label>
          <label className="field"><span>Expires after <span className="hint">seconds</span></span>
            <input type="number" step="1" min="1" placeholder="not set" value={d.expiresAfterSec}
                   onChange={(e) => set("expiresAfterSec", e.target.value)} />
            {d.expiresAfterSec.trim() ? (
              <span className="field-note" style={{ color: "var(--a4t-short)" }}>
                The execution path cannot honour this yet, so orders would be
                refused rather than sent without an expiry.
              </span>
            ) : null}
          </label>
        </div>
      </Section>
    </>
  );
}
