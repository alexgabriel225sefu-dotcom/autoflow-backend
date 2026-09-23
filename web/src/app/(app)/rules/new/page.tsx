"use client";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Save } from "lucide-react";
import { api, type ApiError, type ConditionSpec, type RuleDoc } from "@/lib/api";
import { defaultsFor } from "@/components/app/condition-editor";
import { BLANK, RuleForm, toDoc, type Draft } from "@/components/app/rule-form";
import { RuleSentence } from "@/components/app/rule-summary";
import { ErrorNotice, Spinner } from "@/components/app/state";

export default function NewRulePage() {
  const router = useRouter();
  const [specs, setSpecs] = useState<Record<string, ConditionSpec> | null>(null);
  const [loadErr, setLoadErr] = useState<ApiError | null>(null);
  const [draft, setDraft] = useState<Draft>(BLANK);
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

  if (loadErr) {
    return <main><h1>New rule</h1><ErrorNotice error={loadErr} /></main>;
  }
  if (!specs) {
    return <main><h1>New rule</h1><Spinner label="Loading the condition library" /></main>;
  }

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
        <button className="btn" onClick={save} disabled={busy}>
          <Save className="ico" aria-hidden /> {busy ? "Saving…" : "Save draft"}
        </button>
      </div>

      {/* The rule read back as a sentence, updating as it is built. A client
          who cannot read their own rule has not really configured it. */}
      <RuleSentence doc={toDoc(draft)} specs={specs} />

      <div style={{ marginTop: ".85rem" }}>
        <RuleForm draft={draft} set={set} specs={specs} />
      </div>

      {err ? <ErrorNotice error={err} /> : null}

      <div className="btn-row" style={{ marginTop: "1rem" }}>
        <button className="btn btn-lg" onClick={save} disabled={busy}>
          <Save className="ico" aria-hidden /> {busy ? "Saving…" : "Save draft"}
        </button>
        <a className="btn btn-ghost btn-lg" href="/rules">Cancel</a>
      </div>
    </main>
  );
}
