"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Check, ChevronLeft, ChevronRight, Save } from "lucide-react";
import { api, type ApiError, type ConditionSpec, type RuleDoc } from "@/lib/api";
import { defaultsFor } from "@/components/app/condition-editor";
import { BLANK, RuleForm, STEPS, toDoc, type Draft, type StepId } from "@/components/app/rule-form";
import { RuleSentence, RuleTerms } from "@/components/app/rule-summary";
import { ErrorNotice, Spinner } from "@/components/app/state";

/**
 * The rule builder, one step at a time.
 *
 * Progressive disclosure, not hidden fields. Every step is reachable from the
 * rail at any point, Review shows the whole document, and nothing is dropped
 * because a step was never opened — an unvisited field still takes a value,
 * and Review states that value rather than implying it.
 *
 * The conditions come from /api/v1/conditions. There is no list of conditions
 * in this project, so the builder cannot offer one the evaluator does not
 * implement.
 */
export default function NewRulePage() {
  const router = useRouter();
  const [specs, setSpecs] = useState<Record<string, ConditionSpec> | null>(null);
  const [loadErr, setLoadErr] = useState<ApiError | null>(null);
  const [draft, setDraft] = useState<Draft>(BLANK);
  const [step, setStep] = useState<StepId>("basics");
  const [err, setErr] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  const set = useCallback(<K extends keyof Draft>(k: K, v: Draft[K]) => {
    setDraft((d) => ({ ...d, [k]: v }));
  }, []);

  useEffect(() => {
    void api<{ conditions: Record<string, ConditionSpec> }>("conditions").then((r) => {
      if (!r.ok) return setLoadErr(r);
      setSpecs(r.data.conditions);
      const first = Object.keys(r.data.conditions).sort()[0];
      if (first) {
        setDraft((d) => ({
          ...d,
          entry: [{ id: first, params: defaultsFor(r.data.conditions[first]) }],
        }));
      }
    });
  }, []);

  async function save() {
    setBusy(true); setErr(null);
    const r = await api<{ rule: RuleDoc }>("rules", { method: "POST", body: toDoc(draft) });
    setBusy(false);
    if (!r.ok) return setErr(r);
    router.push(`/rules/${r.data.rule.ruleDocId}`);
  }

  if (loadErr) return <main><h1>New rule</h1><ErrorNotice error={loadErr} /></main>;
  if (!specs) return <main><h1>New rule</h1><Spinner label="Loading the condition library" /></main>;

  const index = STEPS.findIndex((s) => s.id === step);
  const isReview = step === "review";

  return (
    <main>
      <div className="page-head">
        <div>
          <h1>New rule</h1>
          <span className="sub">
            Saved as a draft. Nothing trades until you activate it, and
            activation validates every field again on the server.
          </span>
        </div>
        <span className="pill pill-demo">Demo only</span>
      </div>

      {/* The rule read back as a sentence, updating as it is built. A client
          who cannot read their own rule has not really configured it. */}
      <RuleSentence doc={toDoc(draft)} specs={specs} />

      <div className="workspace" style={{ marginTop: "var(--sp-3)" }}>
        <div>
          {/* The rail is navigation, not a gate: every step is reachable at
              any time, because a trader fixing the stop should not have to
              walk back through entry conditions to get there. */}
          <nav className="steps" aria-label="Rule sections">
            {STEPS.map((s, i) => (
              <button
                key={s.id}
                type="button"
                aria-current={s.id === step ? "step" : undefined}
                onClick={() => setStep(s.id)}
              >
                <span className="n">{i < index ? <Check style={{ width: 11, height: 11 }} aria-hidden /> : i + 1}</span>
                {s.label}
              </button>
            ))}
          </nav>

          {isReview ? (
            <section className="card">
              <div className="card-head">
                <h2>Review</h2>
                <span className="dim" style={{ fontSize: ".75rem" }}>
                  Every field, including the ones left at their default
                </span>
              </div>
              <RuleTerms doc={toDoc(draft)} specs={specs} />
              <p className="muted" style={{ fontSize: ".8rem", marginTop: "var(--sp-3)" }}>
                Saving creates a draft. Validation and preview run on the rule
                page, and activation is a separate, deliberate step.
              </p>
            </section>
          ) : (
            <RuleForm draft={draft} set={set} specs={specs} step={step} />
          )}

          {err ? <ErrorNotice error={err} /> : null}

          <div className="btn-row" style={{ marginTop: "var(--sp-4)" }}>
            <button
              type="button" className="btn btn-ghost"
              disabled={index === 0}
              onClick={() => setStep(STEPS[Math.max(0, index - 1)].id)}
            >
              <ChevronLeft className="ico" aria-hidden /> Back
            </button>
            {index < STEPS.length - 1 ? (
              <button
                type="button" className="btn"
                onClick={() => setStep(STEPS[index + 1].id)}
              >
                Next: {STEPS[index + 1].label} <ChevronRight className="ico" aria-hidden />
              </button>
            ) : null}
            <button className="btn btn-lg" onClick={save} disabled={busy}>
              <Save className="ico" aria-hidden /> {busy ? "Saving…" : "Save draft"}
            </button>
            <Link className="btn btn-ghost" href="/rules">Cancel</Link>
          </div>
        </div>

        <aside className="inspector">
          <section className="card">
            <div className="card-head"><h2>What happens next</h2></div>
            <ol className="muted" style={{ fontSize: ".82rem", lineHeight: 1.7, paddingLeft: "1.1rem" }}>
              <li>Save this as a draft.</li>
              <li>Validate it — the server checks every field again.</li>
              <li>Preview it against real bars from your account.</li>
              <li>Activate it. The version is then frozen.</li>
              <li>Start automation on a demo account.</li>
            </ol>
          </section>

          <section className="card card-flat">
            <p className="muted" style={{ fontSize: ".8rem", lineHeight: 1.6 }}>
              <strong style={{ color: "var(--a4t-text)" }}>Demo only.</strong>{" "}
              Live trading is not available in this release. Saving or
              activating a rule places nothing by itself.
            </p>
          </section>
        </aside>
      </div>
    </main>
  );
}
