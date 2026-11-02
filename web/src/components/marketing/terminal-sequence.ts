/**
 * The timing of the rule terminal, kept apart from React so it can be tested.
 *
 * A "step" is one visible change: step 0 is an empty prompt, steps
 * 1..rule.length type one more character of the rule, and each step after
 * that prints one more reply line. Every frame is a prefix of the final
 * content, so the animation can never show text the finished block does not.
 */
export type TerminalFrame = { typed: string; lines: string[]; done: boolean };

export function totalSteps(rule: string, reply: readonly string[]): number {
  return rule.length + reply.length;
}

export function frameAt(step: number, rule: string, reply: readonly string[]): TerminalFrame {
  const total = totalSteps(rule, reply);
  const s = Math.min(Math.max(0, Math.floor(step)), total);
  if (s <= rule.length) {
    return { typed: rule.slice(0, s), lines: [], done: s === total };
  }
  return { typed: rule, lines: reply.slice(0, s - rule.length), done: s === total };
}

/** Milliseconds to wait after showing `step` before showing the next one. */
export function delayAfter(step: number, rule: string): number {
  if (step === rule.length) return 520; // the "enter" beat
  if (step > rule.length) return 360; // one reply line at a time
  const ch = rule[step - 1] ?? "";
  return ch === ";" || ch === "," ? 110 : 20; // a brief beat at clause breaks
}
