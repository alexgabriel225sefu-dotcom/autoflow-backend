"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, type ConditionSpec, type RuleDoc } from "@/lib/api";
import { ConditionEditor, defaultsFor, type ConditionValue } from "@/components/app/condition-editor";
import { ErrorNotice, Spinner } from "@/components/app/state";
import type { ApiError } from "@/lib/api";

export default function NewRulePage() {
  const router = useRouter();
  const [specs, setSpecs] = useState<Record<string, ConditionSpec> | null>(null);
  const [loadErr, setLoadErr] = useState<ApiError | null>(null);
  const [name, setName] = useState("");
  const [symbols, setSymbols] = useState("EUR_USD");
  const [timeframe, setTimeframe] = useState("1h");
  const [sides, setSides] = useState("BUY");
  const [entry, setEntry] = useState<ConditionValue[]>([]);
  const [exit, setExit] = useState<ConditionValue[]>([]);
  const [entryCombine, setEntryCombine] = useState("AND");
  const [exitCombine, setExitCombine] = useState("OR");
  const [err, setErr] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void api<{ conditions: Record<string, ConditionSpec> }>("conditions").then((r) => {
      if (r.ok) {
        setSpecs(r.data.conditions);
        const first = Object.keys(r.data.conditions).sort()[0];
        if (first) {
          setEntry([{ id: first, params: defaultsFor(r.data.conditions[first]) }]);
          setExit([{ id: first, params: defaultsFor(r.data.conditions[first]) }]);
        }
      } else setLoadErr(r);
    });
  }, []);

  async function save() {
    setBusy(true); setErr(null);
    const r = await api<{ rule: RuleDoc }>("rules", {
      method: "POST",
      body: {
        name, timeframe, sides,
        symbols: symbols.split(",").map((s) => s.trim()).filter(Boolean),
        entry: { combine: entryCombine, conditions: entry },
        exit: { combine: exitCombine, conditions: exit },
      },
    });
    setBusy(false);
    if (!r.ok) return setErr(r);
    router.push(`/rules/${r.data.rule.ruleDocId}`);
  }

  if (loadErr) return <main><h1>New rule</h1><ErrorNotice error={loadErr} /></main>;
  if (!specs) return <main><h1>New rule</h1><Spinner label="Loading the condition library" /></main>;

  const add = (set: (f: (v: ConditionValue[]) => ConditionValue[]) => void) => {
    const first = Object.keys(specs).sort()[0];
    set((v) => [...v, { id: first, params: defaultsFor(specs[first]) }]);
  };

  return (
    <main>
      <h1>New rule</h1>
      <p className="muted">
        Saved as a draft. Nothing trades until you activate it, and activation
        validates every field again on the server.
      </p>

      <section className="card">
        <h2>Basics</h2>
        <div className="grid grid-2">
          <label className="field"><span>Name</span>
            <input value={name} onChange={(e) => setName(e.target.value)} /></label>
          <label className="field"><span>Instruments (comma separated)</span>
            <input value={symbols} onChange={(e) => setSymbols(e.target.value)} /></label>
          <label className="field"><span>Timeframe</span>
            <select value={timeframe} onChange={(e) => setTimeframe(e.target.value)}>
              {["1m", "5m", "15m", "30m", "1h", "4h", "1d"].map((t) =>
                <option key={t} value={t}>{t}</option>)}
            </select></label>
          <label className="field"><span>Sides</span>
            <select value={sides} onChange={(e) => setSides(e.target.value)}>
              {["BUY", "SELL", "BOTH"].map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
            {sides === "BOTH" ? (
              <span className="muted">
                With BOTH, the conditions must imply a direction or the engine
                refuses rather than guessing a side.
              </span>
            ) : null}
          </label>
        </div>
      </section>

      <section className="card">
        <div className="card-head">
          <h2>Entry conditions</h2>
          <label className="field" style={{ margin: 0 }}>
            <span>Combine</span>
            <select value={entryCombine} onChange={(e) => setEntryCombine(e.target.value)}>
              <option>AND</option><option>OR</option>
            </select>
          </label>
        </div>
        {entry.map((c, i) => (
          <ConditionEditor key={i} specs={specs} value={c}
            onChange={(v) => setEntry(entry.map((x, j) => (j === i ? v : x)))}
            onRemove={() => setEntry(entry.filter((_, j) => j !== i))} />
        ))}
        <button className="btn btn-ghost" onClick={() => add(setEntry)}>Add condition</button>
      </section>

      <section className="card">
        <div className="card-head">
          <h2>Exit conditions</h2>
          <label className="field" style={{ margin: 0 }}>
            <span>Combine</span>
            <select value={exitCombine} onChange={(e) => setExitCombine(e.target.value)}>
              <option>AND</option><option>OR</option>
            </select>
          </label>
        </div>
        {exit.map((c, i) => (
          <ConditionEditor key={i} specs={specs} value={c}
            onChange={(v) => setExit(exit.map((x, j) => (j === i ? v : x)))}
            onRemove={() => setExit(exit.filter((_, j) => j !== i))} />
        ))}
        <button className="btn btn-ghost" onClick={() => add(setExit)}>Add condition</button>
      </section>

      {err ? <ErrorNotice error={err} /> : null}
      <button className="btn" onClick={save} disabled={busy}>
        {busy ? "Saving…" : "Save draft"}
      </button>
    </main>
  );
}
