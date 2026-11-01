import Link from "next/link";
import { ArrowRight, Check, Circle } from "lucide-react";
import { BorderBeam } from "@/components/ui/border-beam";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export type GuidedSetupStep = {
  id: "symbol" | "strategy" | "risk" | "account" | "start";
  title: string;
  description: string;
  href: string;
  complete: boolean;
};

type GuidedSetupProps = {
  steps: GuidedSetupStep[];
  accountSummary: string;
};

function stepState(step: GuidedSetupStep, currentId: GuidedSetupStep["id"] | null) {
  if (step.complete) return "complete";
  if (step.id === currentId) return "current";
  return "upcoming";
}

/**
 * A small, explicit setup path for the first useful dashboard visit.
 *
 * The dashboard still contains the full controls below. This card gives a
 * new client one next action without hiding the controls or inventing a
 * second source of truth for execution capability. The step states are
 * derived from the same reads the dashboard already makes.
 */
export function GuidedSetup({ steps, accountSummary }: GuidedSetupProps) {
  const currentId = steps.find((step) => !step.complete)?.id ?? null;
  const currentStep = steps.find((step) => step.id === currentId) ?? null;
  const completeCount = steps.filter((step) => step.complete).length;

  return (
    <Card
      className="relative mb-4 overflow-hidden border-[color:var(--a4t-line)] bg-[color:var(--a4t-surface)]"
      aria-labelledby="guided-setup-title"
      data-setup-complete={completeCount === steps.length ? "true" : "false"}
    >
      {currentStep ? (
        <BorderBeam
          size={160}
          duration={18}
          borderWidth={1}
          colorFrom="var(--a4t-link)"
          colorTo="var(--a4t-brand)"
          className="motion-reduce:hidden"
        />
      ) : null}
      <CardHeader className="relative z-[1] gap-2 pb-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle id="guided-setup-title" className="text-lg">
              Guided setup
            </CardTitle>
            <CardDescription>
              {completeCount === steps.length
                ? "Your setup is ready. You can review any step before starting."
                : `${completeCount} of ${steps.length} steps complete. Finish one step at a time.`}
            </CardDescription>
          </div>
          <span
            className="rounded-full border border-[color:var(--a4t-line)] px-2.5 py-1 text-xs text-[color:var(--a4t-muted)]"
            aria-label={`${completeCount} of ${steps.length} setup steps complete`}
          >
            {completeCount}/{steps.length}
          </span>
        </div>
        <p className="text-xs text-[color:var(--a4t-dim)]">{accountSummary}</p>
      </CardHeader>

      <CardContent className="relative z-[1] space-y-3">
        <ol className="grid gap-2 md:grid-cols-5" aria-label="Automation setup steps">
          {steps.map((step, index) => {
            const state = stepState(step, currentId);
            return (
              <li
                key={step.id}
                className="rounded-lg border border-[color:var(--a4t-line-soft)] bg-[color:var(--a4t-bg-2)] p-3"
                data-step={step.id}
                data-state={state}
              >
                <div className="flex items-start gap-2">
                  <span
                    className="mt-0.5 shrink-0 text-[color:var(--a4t-muted)]"
                    aria-hidden="true"
                  >
                    {step.complete ? <Check size={16} /> : <Circle size={16} />}
                  </span>
                  <div className="min-w-0">
                    <p className="text-xs font-semibold text-[color:var(--a4t-text)]">
                      <span className="mr-1 text-[color:var(--a4t-dim)]">{index + 1}.</span>
                      {step.title}
                    </p>
                    <p className="mt-1 text-xs leading-5 text-[color:var(--a4t-muted)]">
                      {step.description}
                    </p>
                  </div>
                </div>
              </li>
            );
          })}
        </ol>

        {currentStep ? (
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[color:var(--a4t-line-soft)] pt-3">
            <p className="text-sm text-[color:var(--a4t-muted)]">
              Next: <strong className="text-[color:var(--a4t-text)]">{currentStep.title}</strong>
            </p>
            <Button asChild size="sm">
              <Link href={currentStep.href} aria-label={`Open setup step: ${currentStep.title}`}>
                Open step <ArrowRight size={15} aria-hidden="true" />
              </Link>
            </Button>
          </div>
        ) : (
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[color:var(--a4t-line-soft)] pt-3">
            <p className="text-sm text-[color:var(--a4t-muted)]">
              All setup steps are complete. Starting is still a deliberate action.
            </p>
            <Button asChild size="sm">
              <Link href="#automation">Review automation</Link>
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
