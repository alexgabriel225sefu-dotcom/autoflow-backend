"use client";
import { use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Check, ChevronLeft, ChevronRight, Save } from "lucide-react";
import { api, type ApiError, type ConditionSpec, type RuleDoc } from "@/lib/api";
import { invalidate } from "@/lib/use-api";
import {
  RuleForm, STEPS, fromDoc, toDoc, type Draft, type StepId,
} from "@/components/app/rule-form";
import { RuleSentence, RuleTerms } from "@/components/app/rule-summary";
import { ErrorNotice, Spinner } from "@/components/app/state";

/**
 * Editing a draft.
 *
 * WHY THIS PAGE DID NOT EXIST, AND WHAT THAT COST
 *
 * The UI could create a rule and never change it again. Not a new version,
 * not even the draft you had just saved — there was no route, no form bound
 * to an existing document, and nothing in `web/src` issued a PUT at all. So
 * the core loop stopped at its second step: build, activate, stuck. The rule
 * page even told the reader that "editing it creates a new version as a
 * draft", which was true of the server and false of the product.
 *
 * It is also why `PUT /rules/{id}` carried a defect for so long — the
 * endpoint existed, was tested, and had no caller to find it with.
 *
 * WHAT THIS SENDS
 *
 * Only the fields the form owns. `version`, `createdAt`, `activatedAt`, the
 * owner and the account are absent from `toDoc`, and the server re-asserts
 * them from the stored document. That is what makes a partial patch safe
 * here, and it is checked by rule-form-roundtrip.test.ts rather than assumed.
 *
 * WHAT IT REFUSES
 *
 * A rule that is not a DRAFT, because the server refuses it too and an editor
 * that lets you type into a frozen rule is a lie told in advance. And a rule
 * the form cannot represent faithfully — `fromDoc` names that case — because
 * loading it would delete what it could not carry on the next save.
 */
export default function EditRulePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();

  const [specs, setSpecs] = useState<Record<string, ConditionSpec> | null>(null);
  const [doc, setDoc] = useState<RuleDoc | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [refusal, setRefusal] = useState<string | null>(null);
  const [loadErr, setLoadErr] = useState<ApiError | null>(null);
  const [err, setErr] = useState<ApiError | null>(null);
  const [step, setStep] = useState<StepId>("basics");
  const [busy, setBusy] = useState(false);

  const set = useCallback(<K extends keyof Draft>(k: K, v: Draft[K]) => {
    setDraft((d) => (d ? { ...d, [k]: v } : d));
  }, []);

  useEffect(() => {
    void (async () => {
      const [specsRes, ruleRes] = await Promise.all([
        api<{ conditions: Record<string, ConditionSpec> }>("conditions"),
        api<{ rule: RuleDoc }>(`rules/${id}`),
      ]);
      if (!specsRes.ok) return setLoadErr(specsRes);
      if (!ruleRes.ok) return setLoadErr(ruleRes);
      setSpecs(specsRes.data.conditions);
      const rule = ruleRes.data.rule;
      setDoc(rule);
      if (rule.state !== "draft") {
        return setRefusal(
          `This rule is ${rule.state}. An active version is frozen — open a `
          + `new version from the rule page, and edit that draft.`);
      }
      const loaded = fromDoc(rule);
      if (!loaded.ok) return setRefusal(loaded.reason);
      setDraft(loaded.draft);
    })();
  }, [id]);

  async function save() {
    if (!draft) return;
    setBusy(true); setErr(null);
    const r = await api<{ rule: RuleDoc }>(`rules/${id}`,
                                           { method: "PUT", body: toDoc(draft) });
    setBusy(false);
    if (!r.ok) return setErr(r);
    // The list shows name, symbols and timeframe, all of which may have just
    // moved; the rule page is where we are going.
    invalidate("rules");
    router.push(`/rules/${id}`);
  }

  if (loadErr) {
    return <main><h1>Edit rule</h1><ErrorNotice error={loadErr} /></main>;
  }
  if (refusal) {
    return (
      <main>
        <h1>Edit rule</h1>
        <div className="notice notice-warn" role="status" style={{ marginTop: "var(--sp-3)" }}>
          <p>{refusal}</p>
          <Link className="btn btn-sm btn-ghost" href={`/rules/${id}`}>
            Back to the rule
          </Link>
        </div>
      </main>
    );
  }
  if (!specs || !draft || !doc) {
    return <main><h1>Edit rule</h1><Spinner label="Loading the rule" /></main>;
  }

  const index = STEPS.findIndex((s) => s.id === step);
  const isReview = step === "review";

  return (
    <main>
      <div className="page-head">
        <div>
          <h1>Edit {doc.name || "rule"}</h1>
          <span className="sub">
            Draft v{doc.version}. Saving changes the draft only — it trades
            nothing, and activation validates every field again on the server.
          </span>
        </div>
        <span className="pill pill-demo">Demo only</span>
      </div>

      <RuleSentence doc={toDoc(draft)} specs={specs} />

      <div className="workspace" style={{ marginTop: "var(--sp-3)" }}>
        <div>
          <nav className="steps" aria-label="Rule sections">
            {STEPS.map((s, i) => (
              <button
                key={s.id}
                type="button"
                aria-current={s.id === step ? "step" : undefined}
                onClick={() => setStep(s.id)}
              >
                <span className="n">
                  {i < index ? <Check style={{ width: 11, height: 11 }} aria-hidden /> : i + 1}
                </span>
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
            {/* One filled button per step, and it is the one that moves the
                flow forward — the same rule the builder follows. */}
            <button
              className={index < STEPS.length - 1 ? "btn btn-ghost" : "btn btn-lg"}
              onClick={save}
              disabled={busy}
            >
              <Save className="ico" aria-hidden /> {busy ? "Saving…" : "Save changes"}
            </button>
            <Link className="btn btn-ghost" href={`/rules/${id}`}>Cancel</Link>
          </div>
        </div>

        <aside className="inspector">
          <section className="card">
            <div className="card-head"><h2>What this changes</h2></div>
            <ol className="muted" style={{ fontSize: ".82rem", lineHeight: 1.7, paddingLeft: "1.1rem" }}>
              <li>The draft, and nothing else.</li>
              <li>No frozen version is touched, so anything already recorded
                  against one still points at terms that exist.</li>
              <li>Validation and preview run on the rule page.</li>
              <li>Activation is a separate, deliberate step.</li>
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
