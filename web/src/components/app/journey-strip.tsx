"use client";
/**
 * Where you are, in three steps: choose, start, watch.
 *
 * It says the same thing the first-run checklist says, in the fewest words,
 * and it never invents a fact. Each step is derived from a read the page makes
 * anyway; a read that has not answered leaves its step "unknown", which is
 * drawn as unknown and never as done.
 */
import Link from "next/link";
import { Check, Eye, ListChecks, Play } from "lucide-react";
import type { ApiResult, AutomationState, RuleSummary } from "@/lib/api";

export type JourneyState = "done" | "current" | "todo" | "unknown";
export type JourneyStep = {
  id: "choose" | "start" | "watch";
  title: string;
  hint: string;
  href: string;
  state: JourneyState;
};

type Reads = {
  auto: ApiResult<AutomationState> | null | undefined;
  rules: ApiResult<{ rules: RuleSummary[] }> | null | undefined;
};

export function journeySteps({ auto, rules }: Reads): JourneyStep[] {
  const autoOk = auto?.ok ? auto.data : null;
  const rulesOk = rules?.ok ? rules.data.rules : null;

  const hasRule = rulesOk ? rulesOk.some((r) => r.state !== "archived") : null;
  const started = autoOk ? autoOk.state !== "stopped" : null;
  const running = autoOk ? autoOk.state === "running" : null;

  const raw: Array<[JourneyStep["id"], string, string, string, boolean | null]> = [
    ["choose", "Choose a strategy", "Pick an instrument and a ready-made strategy.", "/trade", hasRule],
    ["start", "Start on demo", "One tap. No real money in this release.", "/trade", started],
    ["watch", "Watch it work", running ? "Running. Every decision is in your journal." : "Every decision lands in your journal.", "/journal", null],
  ];

  let currentTaken = false;
  return raw.map(([id, title, hint, href, done]) => {
    let state: JourneyState;
    if (id === "watch") {
      state = running === null ? "unknown" : running ? "current" : "todo";
      if (running) currentTaken = true;
    } else if (done === null) {
      state = "unknown";
    } else if (done) {
      state = "done";
    } else if (!currentTaken) {
      state = "current";
      currentTaken = true;
    } else {
      state = "todo";
    }
    return { id, title, hint, href, state };
  });
}

const ICON = { choose: ListChecks, start: Play, watch: Eye } as const;

export function JourneyStrip(props: Reads) {
  const steps = journeySteps(props);
  return (
    <nav className="jrn" aria-label="Your three steps">
      {steps.map((s, i) => {
        const Icon = ICON[s.id];
        return (
          <Link
            key={s.id} href={s.href} className="jrn-step" data-state={s.state}
            aria-current={s.state === "current" ? "step" : undefined}
            style={{ ["--i" as string]: i } as React.CSSProperties}
          >
            <span className="jrn-mark" aria-hidden="true">
              {s.state === "done" ? <Check size={16} strokeWidth={2.4} /> : <Icon size={16} strokeWidth={2.1} />}
            </span>
            <span className="jrn-text">
              <strong>{i + 1}. {s.title}</strong>
              <span>{s.hint}</span>
            </span>
          </Link>
        );
      })}
    </nav>
  );
}
