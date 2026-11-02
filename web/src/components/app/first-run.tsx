"use client";
/**
 * The first-run checklist.
 *
 * Every step is derived from a fact the API already returned. There is no
 * stored "I did this" flag and no optimistic tick: a step is done because the
 * server said so, todo because the server said the opposite, and UNKNOWN when
 * the read behind it has not answered or failed. Unknown is shown as unknown,
 * never as done and never as todo.
 *
 * The card renders nothing until every read has answered once (so a returning
 * client does not see it flash), and nothing again when every step is done.
 */
import Link from "next/link";
import { Check, Circle, HelpCircle } from "lucide-react";
import type { ApiResult, AutomationState, CtraderStatus, Me, RuleSummary } from "@/lib/api";

export type StepState = "done" | "todo" | "unknown";
export type FirstRunStep = {
  id: "email" | "connect" | "account" | "strategy" | "start";
  label: string;
  hint: string;
  href: string;
  state: StepState;
};

type Reads = {
  me: ApiResult<Me> | null | undefined;
  ct: ApiResult<CtraderStatus> | null | undefined;
  auto: ApiResult<AutomationState> | null | undefined;
  rules: ApiResult<{ rules: RuleSummary[] }> | null | undefined;
};

export function firstRunSteps({ me, ct, auto, rules }: Reads): FirstRunStep[] {
  const meOk = me?.ok ? me.data : null;
  const ctOk = ct?.ok ? ct.data : null;
  const autoOk = auto?.ok ? auto.data : null;
  const rulesOk = rules?.ok ? rules.data.rules : null;

  const email: StepState = meOk ? (meOk.user.emailVerified ? "done" : "todo") : "unknown";
  const connect: StepState = ctOk ? (ctOk.connected ? "done" : "todo") : "unknown";
  const account: StepState = ctOk ? (ctOk.connected && ctOk.selected ? "done" : "todo") : "unknown";
  const strategy: StepState = rulesOk
    ? (rulesOk.some((r) => r.state !== "archived") ? "done" : "todo") : "unknown";
  const start: StepState = autoOk ? (autoOk.state === "stopped" ? "todo" : "done") : "unknown";

  return [
    { id: "email", label: "Confirm your email", state: email, href: "/settings",
      hint: "Connecting cTrader and activating a rule need a confirmed address." },
    { id: "connect", label: "Connect cTrader", state: connect, href: "/connect",
      hint: "You authorise your own account; we never see your broker password." },
    { id: "account", label: "Pick a demo account", state: account, href: "/accounts",
      hint: "The selected account is the one every read and order uses." },
    { id: "strategy", label: "Choose a strategy on Trade", state: strategy, href: "/trade",
      hint: "Pick an instrument and a ready-made strategy, then set your risk." },
    { id: "start", label: "Press Start", state: start, href: "/trade",
      hint: "Runs on demo accounts only in this release." },
  ];
}

/** True once every read has answered at least once, successfully or not. */
function answered(r: Reads): boolean {
  return !!(r.me && r.ct && r.auto && r.rules);
}

export function FirstRunChecklist(props: Reads) {
  if (!answered(props)) return null;
  const steps = firstRunSteps(props);
  if (steps.every((s) => s.state === "done")) return null;
  const done = steps.filter((s) => s.state === "done").length;
  // The step to do next: the first one that is not done.
  const next = steps.find((s) => s.state !== "done");

  return (
    <section className="card" aria-label="Getting started">
      <div className="card-head">
        <h2>Getting started</h2>
        <span className="dim" style={{ fontSize: ".75rem" }}>{done} of {steps.length} done</span>
      </div>
      <ol style={{ listStyle: "none", padding: 0, margin: 0, display: "grid", gap: ".55rem" }}>
        {steps.map((s) => (
          <li key={s.id} data-step={s.id} data-state={s.state}
              style={{ display: "flex", gap: ".6rem", alignItems: "flex-start" }}>
            <span aria-hidden style={{ flex: "none", marginTop: 2 }}>
              {s.state === "done" ? <Check className="ico" style={{ width: 15, height: 15 }} />
                : s.state === "unknown" ? <HelpCircle className="ico" style={{ width: 15, height: 15 }} />
                : <Circle className="ico" style={{ width: 15, height: 15 }} />}
            </span>
            <span style={{ flex: 1 }}>
              {s.state === "done" ? (
                <span className="muted" style={{ textDecoration: "line-through" }}>{s.label}</span>
              ) : (
                <Link href={s.href} style={s === next ? { fontWeight: 600 } : undefined}>{s.label}</Link>
              )}
              <span className="sr-only">
                {s.state === "done" ? " (done)" : s.state === "unknown" ? " (could not check)" : " (to do)"}
              </span>
              {s.state === "unknown" ? (
                <span className="dim" style={{ display: "block", fontSize: ".78rem" }}>
                  Could not check this just now.
                </span>
              ) : s.state === "todo" ? (
                <span className="dim" style={{ display: "block", fontSize: ".78rem" }}>{s.hint}</span>
              ) : null}
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}
