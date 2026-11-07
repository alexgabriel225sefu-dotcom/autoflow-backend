import type { RuleDoc, StrategyPreset } from "@/lib/api";

/**
 * The two decisions the strategy picker makes, kept out of the page so they
 * can be tested without a DOM, an API or a session.
 *
 * WHY THESE TWO AND NOT MORE
 *
 * Everything else the picker renders comes from the server exactly as it
 * arrives — the label, the description, what each strategy refuses, which
 * ones are withheld and why. A browser that reshaped any of that would be a
 * second copy of a fact the server owns, and the first time a strategy is
 * added or renamed the two would disagree. These two are genuinely the
 * browser's: how the list is arranged, and what gets sent when a client
 * picks one.
 */

/**
 * The order families are shown in. Readable to unreadable, roughly: the
 * adaptive one first because it is the one a client who does not know what to
 * pick should pick, then the two classic directions, then the structural
 * reads, then the two that need the most explaining.
 *
 * This is a PREFERENCE, not a filter — see `groupByFamily`.
 */
export const FAMILY_ORDER = [
  "adaptive", "trend", "reversion", "breakout", "momentum", "structure",
  "statistical",
] as const;

const FAMILY_LABELS: Record<string, string> = {
  adaptive: "Adaptive",
  trend: "Trend",
  reversion: "Mean reversion",
  breakout: "Breakout",
  momentum: "Momentum",
  structure: "Market structure",
  statistical: "Statistical",
};

/** A family's heading. An unknown family is shown under its own raw name
 *  rather than something invented for it, or dropped. */
export function familyLabel(family: string): string {
  return FAMILY_LABELS[family] ?? family;
}

export type FamilyGroup = {
  family: string;
  label: string;
  strategies: StrategyPreset[];
};

/**
 * The server's list, grouped for display.
 *
 * TWO PROPERTIES, BOTH DELIBERATE.
 *
 * NOTHING IS DROPPED. A family this file has never heard of is appended with
 * its raw name instead of being filtered out. The whole point of serving the
 * catalogue from the registry is that a strategy added to the engine shows
 * up here; a browser-side list of known families would quietly undo that, and
 * the symptom would be a strategy the client cannot find and nobody can
 * explain.
 *
 * ORDER WITHIN A FAMILY IS THE SERVER'S. It sorts by family then id, and
 * re-sorting here would be the same second copy of somebody else's fact.
 */
export function groupByFamily(strategies: StrategyPreset[]): FamilyGroup[] {
  const byFamily = new Map<string, StrategyPreset[]>();
  for (const s of strategies ?? []) {
    const family = s?.family || "other";
    const bucket = byFamily.get(family);
    if (bucket) bucket.push(s);
    else byFamily.set(family, [s]);
  }
  const known = FAMILY_ORDER.filter((f) => byFamily.has(f)) as string[];
  const unknown = [...byFamily.keys()].filter(
    (f) => !(FAMILY_ORDER as readonly string[]).includes(f),
  );
  return [...known, ...unknown].map((family) => ({
    family,
    label: familyLabel(family),
    strategies: byFamily.get(family) ?? [],
  }));
}

export class NoStrategyChosen extends Error {
  constructor() {
    super("a preset rule needs a strategy — refusing to send one without");
    this.name = "NoStrategyChosen";
  }
}

/**
 * The rule document to send when a client picks a strategy.
 *
 * The mirror of `strategy_catalog.apply_to` on the server, and the server is
 * the one that is enforced: it refuses a preset document that carries
 * conditions, and refuses a strategy id it does not offer. This exists so the
 * browser sends a document that will be accepted, not so the browser is
 * trusted.
 *
 * THE CONDITIONS ARE EMPTIED. A preset decides its own entries and exits, so
 * a condition left on the document would be a term the client can read on
 * their rule page and the engine will never consult. A client who built half
 * a rule and then picked a strategy is exactly the case this matters for, and
 * their conditions go.
 *
 * IT THROWS ON A MISSING ID rather than sending the document without one.
 * Without a strategy and without conditions, the draft is a rule that cannot
 * be activated — "entry.conditions: at least one condition is required" — and
 * the client would be looking at a saved rule that is already a dead end. A
 * thrown error the page can report is the better of the two.
 *
 * Never mutates `doc`.
 */
export function presetRuleBody(
  doc: Partial<RuleDoc>,
  strategyId: string,
): Partial<RuleDoc> {
  if (!strategyId || !strategyId.trim()) throw new NoStrategyChosen();
  const entry = (doc?.entry ?? {}) as Record<string, unknown>;
  const exit = (doc?.exit ?? {}) as Record<string, unknown>;
  return {
    ...doc,
    strategy: strategyId.trim(),
    entry: { ...entry, conditions: [] },
    exit: { ...exit, conditions: [] },
  } as Partial<RuleDoc>;
}
