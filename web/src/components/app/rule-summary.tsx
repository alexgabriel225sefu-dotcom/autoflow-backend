"use client";
/**
 * A rule, restated so a client can read back what they configured.
 *
 * WHY THIS IS NOT A HARD-CODED SENTENCE PER CONDITION
 *
 * The builder deliberately has no list of conditions — it renders itself from
 * /api/v1/conditions so it can never offer something the evaluator does not
 * implement. A phrasebook here would reintroduce exactly that duplication and
 * drift the first time a condition was added, and the drift would be silent:
 * a rule described as one thing and evaluated as another. So the phrase is
 * built from the spec's own parameter order, and the formatting below is
 * formatting only — it never decides what a condition means.
 */
import type { ConditionSpec, RuleDoc } from "@/lib/api";

const ACRONYMS = new Set(["ma", "rsi", "macd", "atr", "ema", "sma", "rr", "tp", "sl"]);
/** Joining words stay lowercase: "Price vs MA", not "Price Vs MA". */
const LOWER = new Set(["vs", "of", "on", "in", "to", "at", "by"]);

/** `price_vs_ma` → `Price vs MA`. Presentation, not meaning. */
export function humanise(id: string): string {
  return id.split(/[_\s]+/).map((w, i) => {
    const lw = w.toLowerCase();
    if (ACRONYMS.has(lw)) return w.toUpperCase();
    if (i > 0 && LOWER.has(lw)) return lw;
    return w.charAt(0).toUpperCase() + w.slice(1);
  }).join(" ");
}

type Cond = { id: string; params?: Record<string, unknown> };

/** `RSI(14, above, 55)` — the spec's parameter order, nothing invented. */
export function conditionPhrase(c: Cond, specs?: Record<string, ConditionSpec> | null): string {
  const spec = specs?.[c.id];
  const order = spec ? Object.keys(spec.params) : Object.keys(c.params ?? {});
  const vals = order
    .map((k) => c.params?.[k])
    .filter((v) => v !== undefined && v !== null && v !== "")
    .map((v) => (Array.isArray(v) ? v.join("/") : String(v)));
  return vals.length ? `${humanise(c.id)}(${vals.join(", ")})` : humanise(c.id);
}

function block(b: unknown, specs?: Record<string, ConditionSpec> | null): string | null {
  const blk = b as { combine?: string; conditions?: Cond[] } | undefined;
  const list = blk?.conditions ?? [];
  if (!list.length) return null;
  return list.map((c) => conditionPhrase(c, specs)).join(` ${blk?.combine ?? "AND"} `);
}

export function sizingPhrase(doc: Partial<RuleDoc>): string {
  const s = (doc.sizing ?? {}) as Record<string, unknown>;
  if (s.mode === "fixed_volume") return `${s.fixedVolume ?? "?"} lots per trade`;
  return `risk ${s.riskPercent ?? "?"}% per trade`;
}

export function stopPhrase(doc: Partial<RuleDoc>): string {
  const s = (doc.stopLoss ?? {}) as Record<string, unknown>;
  if (s.mode === "pips") return `stop ${s.pips ?? "?"} pips`;
  if (s.mode === "atr") return `stop ${s.atrMultiple ?? "?"}× ATR`;
  return "stop not set";
}

export function targetPhrase(doc: Partial<RuleDoc>): string | null {
  const t = (doc.takeProfit ?? {}) as Record<string, unknown>;
  if (t.mode === "rr" && t.rr) return `target ${t.rr}R`;
  if (t.mode === "pips" && t.pips) return `target ${t.pips} pips`;
  return null;
}

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export function schedulePhrase(doc: Partial<RuleDoc>): string | null {
  const s = (doc.schedule ?? {}) as Record<string, unknown>;
  const days = (s.days as number[] | undefined) ?? [];
  const wins = (s.windows as { from?: string; to?: string }[] | undefined) ?? [];
  const parts: string[] = [];
  // 0 = Monday, matching Python's weekday(), which is what the evaluator uses.
  if (days.length) parts.push(days.map((d) => DAYS[d] ?? `day ${d}`).join(", "));
  if (wins.length) parts.push(wins.map((w) => `${w.from}–${w.to} UTC`).join(", "));
  return parts.length ? parts.join(" ") : null;
}

/**
 * The whole rule as one sentence.
 *
 * Anything absent is said to be absent. A missing stop reads "stop not set",
 * never as silence, because the difference decides whether the rule can run
 * at all.
 */
export function ruleSentence(
  doc: Partial<RuleDoc>, specs?: Record<string, ConditionSpec> | null,
): string {
  const sides = String(doc.sides ?? "BOTH");
  const verb = sides === "BUY" ? "Buy" : sides === "SELL" ? "Sell" : "Buy or sell";
  const syms = (doc.symbols as string[] | undefined)?.join(", ") || "no instrument";
  const entry = block(doc.entry, specs);
  const exit = block(doc.exit, specs);

  let s = `${verb} ${syms} on ${doc.timeframe ?? "?"}`;
  s += entry ? ` when ${entry}` : " — no entry condition set";
  if (exit) s += `; exit when ${exit}`;
  s += `; ${sizingPhrase(doc)}; ${stopPhrase(doc)}`;
  const tgt = targetPhrase(doc);
  if (tgt) s += `; ${tgt}`;
  const sched = schedulePhrase(doc);
  if (sched) s += `; only ${sched}`;
  const limits = (doc.limits ?? {}) as Record<string, unknown>;
  if (limits.maxOpenPositions) s += `; at most ${limits.maxOpenPositions} open position${Number(limits.maxOpenPositions) === 1 ? "" : "s"}`;
  return `${s}.`;
}

export function RuleSentence({
  doc, specs,
}: { doc: Partial<RuleDoc>; specs?: Record<string, ConditionSpec> | null }) {
  return (
    <p className="summary-line">
      <span className="label-xs" style={{ display: "block", marginBottom: ".35rem" }}>
        In words
      </span>
      {ruleSentence(doc, specs)}
    </p>
  );
}

/* ── the complete terms ───────────────────────────────────────────────── */

function Row({ k, v, note }: { k: string; v: React.ReactNode; note?: string }) {
  return (
    <tr>
      <th>{k}</th>
      <td>
        {v}
        {note ? <span className="field-note">{note}</span> : null}
      </td>
    </tr>
  );
}

function Conditions({
  b, specs, fallback,
}: { b: unknown; specs?: Record<string, ConditionSpec> | null; fallback: string }) {
  const blk = b as { combine?: string; conditions?: Cond[] } | undefined;
  const list = blk?.conditions ?? [];
  if (!list.length) return <span className="dim">{fallback}</span>;
  return (
    <span>
      {list.map((c, i) => (
        <span key={i}>
          {i > 0 ? (
            <span className="pill pill-muted" style={{ margin: "0 .35rem" }}>
              {blk?.combine ?? "AND"}
            </span>
          ) : null}
          <span className="mono">{conditionPhrase(c, specs)}</span>
        </span>
      ))}
    </span>
  );
}

/**
 * Every term of the rule, including the ones left at their default.
 *
 * A default that is never shown is a decision the client did not make and
 * cannot see. The rule page used to show four fields out of the document's
 * twenty, so the stop, the target and the risk a position would be opened
 * with were invisible.
 */
export function RuleTerms({
  doc, specs,
}: { doc: Partial<RuleDoc>; specs?: Record<string, ConditionSpec> | null }) {
  const order = (doc.order ?? {}) as Record<string, unknown>;
  const limits = (doc.limits ?? {}) as Record<string, unknown>;
  const trail = (doc.trailingStop ?? {}) as Record<string, unknown>;
  const be = (doc.breakEven ?? {}) as Record<string, unknown>;

  return (
    <table className="tbl tbl-kv">
      <tbody>
        <Row k="Instruments" v={(doc.symbols as string[] | undefined)?.join(", ") || <span className="dim">none</span>} />
        <Row k="Timeframe" v={String(doc.timeframe ?? "—")} />
        <Row k="Evaluated" v={doc.evaluateOn === "intrabar" ? "On every tick (intrabar)" : "On bar close"} />
        <Row k="Sides" v={String(doc.sides ?? "—")} />
        <Row k="Entry" v={<Conditions b={doc.entry} specs={specs} fallback="no entry condition" />} />
        <Row k="Exit" v={<Conditions b={doc.exit} specs={specs} fallback="managed by stop and target only" />} />
        <Row k="Sizing" v={sizingPhrase(doc)} />
        <Row k="Stop loss" v={stopPhrase(doc)} />
        <Row k="Take profit" v={targetPhrase(doc) ?? <span className="dim">none — the exit conditions or the stop close the trade</span>} />
        <Row
          k="Trailing stop"
          v={trail.enabled ? `${trail.atrMultiple ?? "?"}× ATR` : <span className="dim">off</span>}
          note={trail.enabled ? "Stored on the rule. The execution engine does not apply it yet." : undefined}
        />
        <Row
          k="Break even"
          v={be.enabled ? `at ${be.atR ?? "?"}R` : <span className="dim">off</span>}
          note={be.enabled ? "Stored on the rule. The execution engine does not apply it yet." : undefined}
        />
        <Row k="Max open positions" v={String(limits.maxOpenPositions ?? "—")} />
        <Row k="Max spread" v={limits.maxSpreadPips ? `${limits.maxSpreadPips} pips` : <span className="dim">no cap</span>} />
        <Row k="On limit" v={limits.onLimit === "flatten" ? "Close open positions" : "Block new entries"} />
        <Row k="Schedule" v={schedulePhrase(doc) ?? <span className="dim">any time the market is open</span>} />
        <Row
          k="Order type"
          v={String(order.type ?? "MARKET")}
          note={order.type && order.type !== "MARKET"
            ? "Only MARKET can be executed today; this rule would be refused at execution."
            : undefined}
        />
        <Row
          k="Max slippage"
          v={order.maxSlippagePoints ? `${order.maxSlippagePoints} points` : <span className="dim">not set</span>}
          note={order.maxSlippagePoints
            ? "Required by the rule and not supported by the execution path — orders would be refused rather than sent without it."
            : undefined}
        />
        <Row
          k="Order expiry"
          v={order.expiresAfterSec ? `${order.expiresAfterSec}s` : <span className="dim">not set</span>}
          note={order.expiresAfterSec
            ? "Required by the rule and not supported by the execution path — orders would be refused rather than sent without it."
            : undefined}
        />
      </tbody>
    </table>
  );
}
