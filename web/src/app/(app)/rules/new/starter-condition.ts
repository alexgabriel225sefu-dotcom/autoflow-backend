import type { ConditionSpec } from "@/lib/api";

/**
 * The condition the rule builder opens with.
 *
 * It must IMPLY A DIRECTION. The builder used to take the alphabetically
 * first one, which is `atr` — a volatility filter that says when to trade and
 * never which way — while `sides` defaults to BOTH. The evaluator refuses that
 * combination with DIRECTION_AMBIGUOUS even when the condition is satisfied,
 * so the rule every new client was handed could not trade, and nothing said
 * so: it saved, validated and activated, and then did nothing.
 *
 * WHICH conditions are directional is the server's fact, read from
 * `impliesDirection`. A list of ids kept here would be a second copy of it,
 * drifting the first time a condition is added.
 *
 * Falls back to the first id when the server marks none — an older API, say.
 * Worse than ideal, never a form that cannot open.
 */
export function starterCondition(
  conditions: Record<string, ConditionSpec>,
): string | undefined {
  const ids = Object.keys(conditions).sort();
  return ids.find((id) => conditions[id]?.impliesDirection) ?? ids[0];
}
