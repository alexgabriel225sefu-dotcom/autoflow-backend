"use client";
import { useCallback, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ChevronLeft, Save, ShieldAlert, SlidersHorizontal } from "lucide-react";
import {
  api, type ApiError, type RuleDoc, type StrategyCatalogue,
} from "@/lib/api";
import { useRead } from "@/lib/use-api";
import { BLANK, RuleForm, toDoc, type Draft, type StepId } from "@/components/app/rule-form";
import { ErrorNotice, Spinner } from "@/components/app/state";
import { groupByFamily, NoStrategyChosen, presetRuleBody } from "./catalog";

/**
 * Picking one of the engine's ready-made strategies.
 *
 * WHY THIS IS ITS OWN ROUTE AND NOT A STEP IN THE BUILDER
 *
 * The builder next door has eleven steps and five of them are about
 * conditions — Entry, Exit, and the Review and sentence that read them back.
 * A preset decides its own entries and exits, so inside the builder those
 * five would render as controls that do nothing, and a control that does
 * nothing is the exact defect this product was rewritten to stop. The two
 * paths share the HALF that is about money (instrument, timeframe, risk,
 * stop, target, management, limits) and have disjoint decision halves, so
 * they are siblings under /rules/new rather than one screen with a mode
 * switch. `RuleForm` is reused for the shared half, so there is one
 * implementation of the risk fields and not two.
 *
 * WHAT THE CLIENT READS BEFORE CHOOSING
 *
 * Every card shows what the strategy trades, how it decides, and — the field
 * that actually matters — what it REFUSES. Five of the fifteen refuse nothing
 * beyond "the setup is not there", and their cards say so in those words.
 * None of this is written here: it comes from /api/v1/strategies, which the
 * server derives from the registry, so the picker cannot offer a strategy the
 * engine does not have or describe one it does not run.
 *
 * WHY SAVING TAKES TWO CALLS
 *
 * POST /rules builds the blank server-side and copies a fixed list of fields
 * from the body; `strategy` is not on that list, so the preset is written by
 * the PUT that follows. If the PUT fails, this page says so and does NOT
 * navigate — the draft exists but has no strategy and no conditions, which is
 * a rule that cannot be activated, and the client needs to know that rather
 * than find it at the activate button.
 */

const SHARED_STEPS: { id: StepId; label: string }[] = [
  { id: "basics", label: "Market" },
  { id: "risk", label: "Risk" },
  { id: "stop", label: "Stop loss" },
  { id: "target", label: "Take profit" },
  { id: "management", label: "Management" },
  { id: "limits", label: "Limits" },
  { id: "schedule", label: "Schedule" },
];

export default function PickStrategyPage() {
  const router = useRouter();
  const cat = useRead<StrategyCatalogue>("strategies");
  const [chosen, setChosen] = useState<string>("");
  const [open, setOpen] = useState<string>("");
  const [draft, setDraft] = useState<Draft>(BLANK);
  const [err, setErr] = useState<ApiError | null>(null);
  const [failed, setFailed] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [orphan, setOrphan] = useState<string>("");

  const set = useCallback(<K extends keyof Draft>(k: K, v: Draft[K]) => {
    setDraft((d) => ({ ...d, [k]: v }));
  }, []);

  async function save() {
    setBusy(true); setErr(null); setFailed("");
    let body;
    try {
      body = presetRuleBody(toDoc(draft), chosen);
    } catch (e) {
      setBusy(false);
      setFailed(e instanceof NoStrategyChosen
        ? "Choose a strategy first — a rule with no strategy and no "
          + "conditions could never be activated."
        : String(e));
      return;
    }

    // Step one: the draft. The server builds the blank and ignores `strategy`.
    const created = await api<{ rule: RuleDoc }>("rules",
                                                 { method: "POST", body });
    if (!created.ok) { setBusy(false); return setErr(created); }
    const id = created.data.rule.ruleDocId;

    // Step two: the strategy itself. Said out loud when it fails, because the
    // draft from step one is already saved and is not yet usable.
    const saved = await api<{ rule: RuleDoc }>(`rules/${id}`,
                                               { method: "PUT", body });
    setBusy(false);
    if (!saved.ok) {
      setOrphan(id);
      return setErr(saved);
    }
    router.push(`/rules/${id}`);
  }

  if (cat.result && !cat.result.ok) {
    return (
      <main>
        <h1>Choose a strategy</h1>
        <ErrorNotice error={cat.result} onRetry={cat.reload} />
      </main>
    );
  }
  if (!cat.result?.ok) {
    return (
      <main>
        <h1>Choose a strategy</h1>
        <Spinner label="Reading the engine's strategy registry" />
      </main>
    );
  }

  const { strategies, withheld, unclassified } = cat.result.data;
  const groups = groupByFamily(strategies);
  const picked = strategies.find((s) => s.id === chosen) ?? null;

  return (
    <main>
      <div className="page-head">
        <div>
          <h1>Choose a strategy</h1>
          <span className="sub">
            One of the engine&apos;s own strategies decides the entries and
            exits. You still set the instrument, the risk, the stop and the
            limits — and nothing trades until you activate it.
          </span>
        </div>
        <span className="pill pill-demo">Demo only</span>
      </div>

      {/* The other half of the fork. A client who wants their own conditions
          is one click away, not in a different part of the product. */}
      <div className="notice notice-accent">
        <SlidersHorizontal className="ico" aria-hidden />{" "}
        Want your own entry and exit conditions instead?{" "}
        <Link href="/rules/new">Build a rule</Link>. A rule and a strategy are
        the same document with one field different, so switching later is a
        new version, not a new rule.
      </div>

      {strategies.length === 0 ? (
        // Not an empty list presented as a fact about the product. The server
        // answers with nothing only when the registry could not be read, and
        // saying so is the honest version of this screen.
        <div className="notice notice-warn" role="alert">
          The engine&apos;s strategy registry could not be read, so there is
          nothing to choose from. Building a rule still works.
        </div>
      ) : null}

      <div className="workspace" style={{ marginTop: "var(--sp-3)" }}>
        <div>
          {groups.map((group) => (
            <section className="card" key={group.family}
                     style={{ marginBottom: "var(--sp-3)" }}>
              <div className="card-head"><h2>{group.label}</h2></div>
              {group.strategies.map((s) => {
                const isOpen = open === s.id;
                const isChosen = chosen === s.id;
                return (
                  <div className="record" key={s.id}>
                    <div className="record-head">
                      <div className="record-title">
                        <label className="field-inline">
                          <input
                            type="radio"
                            name="strategy"
                            value={s.id}
                            checked={isChosen}
                            onChange={() => { setChosen(s.id); setFailed(""); }}
                          />
                          <strong>{s.label}</strong>
                        </label>
                      </div>
                      <span className="pill pill-muted">v{s.version}</span>
                    </div>

                    <p style={{ fontSize: ".85rem", lineHeight: 1.6 }}>
                      {s.what}
                    </p>

                    {/* What it refuses is shown WITHOUT expanding, because it
                        is the half a client has to read and a detail nobody
                        opens is a detail nobody read. */}
                    <p className="muted"
                       style={{ fontSize: ".8rem", lineHeight: 1.6 }}>
                      <strong style={{ color: "var(--a4t-text)" }}>
                        Will not trade:
                      </strong>{" "}
                      {s.refuses}
                    </p>

                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      aria-expanded={isOpen}
                      onClick={() => setOpen(isOpen ? "" : s.id)}
                    >
                      {isOpen ? "Hide how it decides" : "How it decides"}
                    </button>

                    {isOpen ? (
                      <div className="tbl-kv" style={{ marginTop: ".6rem" }}>
                        <p style={{ fontSize: ".8rem", lineHeight: 1.65 }}>
                          {s.decides}
                        </p>
                        {/* The code the description was written from. A claim
                            about money that cannot be checked is a claim. */}
                        <p className="dim mono" style={{ fontSize: ".72rem" }}>
                          {s.source}
                        </p>
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </section>
          ))}

          {/* The shared half. Same component as the rule builder, so the risk
              fields have one implementation. Conditions are deliberately
              absent: this strategy decides those. */}
          <section className="card">
            <div className="card-head">
              <h2>Your terms</h2>
              <span className="dim" style={{ fontSize: ".75rem" }}>
                The strategy decides when to trade. These decide how much.
              </span>
            </div>
            {/* TWO FIELDS IN "Basics" DO NOTHING FOR A PRESET, AND SAYING SO
                HERE IS CHEAPER THAN PRETENDING OTHERWISE.
                `sides` is read by the rule evaluator to decide which way a
                set of satisfied conditions points; a strategy decides its own
                side, so the engine never consults it. `Evaluate` is reported
                as not applied for every rule already — the loop checks on its
                own polling cycle. Both are still recorded on the document,
                and the rule page lists what the engine will not act on. */}
            <p className="muted" style={{ fontSize: ".78rem", lineHeight: 1.6 }}>
              Sides and Evaluate are recorded on the rule and are not acted on
              when a strategy decides: it picks its own direction, and the loop
              checks on its polling cycle rather than at the instant a candle
              closes. Everything else below reaches the engine.
            </p>
            {SHARED_STEPS.map((s) => (
              <div key={s.id} style={{ marginBottom: "var(--sp-3)" }}>
                <RuleForm draft={draft} set={set} specs={{}} step={s.id} />
              </div>
            ))}
          </section>

          {failed ? (
            <div className="notice notice-warn" role="alert">{failed}</div>
          ) : null}
          {err ? <ErrorNotice error={err} /> : null}
          {orphan ? (
            <div className="notice notice-warn" role="alert">
              The draft was created but the strategy was not saved onto it, so{" "}
              <Link href={`/rules/${orphan}`}>that rule</Link> has no strategy
              and no conditions and cannot be activated as it stands. Try
              saving again, or open it and delete it.
            </div>
          ) : null}

          <div className="btn-row" style={{ marginTop: "var(--sp-3)" }}>
            <Link className="btn btn-ghost" href="/rules">
              <ChevronLeft className="ico" aria-hidden /> Cancel
            </Link>
            <button
              className="btn"
              onClick={save}
              disabled={busy || !chosen}
            >
              <Save className="ico" aria-hidden />{" "}
              {busy ? "Saving…" : "Save draft"}
            </button>
          </div>
        </div>

        <aside className="inspector">
          <section className="card">
            <div className="card-head"><h2>What happens next</h2></div>
            <ol className="muted" style={{ fontSize: ".82rem", lineHeight: 1.7,
                                           paddingLeft: "1.1rem" }}>
              <li>Save this as a draft.</li>
              <li>Validate it — the server checks every field again.</li>
              <li>Activate it. The version is then frozen.</li>
              <li>Start automation on a demo account.</li>
            </ol>
            <p className="muted" style={{ fontSize: ".8rem", lineHeight: 1.6 }}>
              There is no preview step here. A preview runs your conditions
              against bars you supply, and a strategy has none — the engine
              decides on its own data.
            </p>
          </section>

          {picked ? (
            <section className="card card-flat">
              <div className="card-head"><h2>Chosen</h2></div>
              <p style={{ fontSize: ".85rem" }}>
                <strong>{picked.label}</strong>
                <span className="dim mono"> ({picked.id} v{picked.version})</span>
              </p>
              <p className="muted" style={{ fontSize: ".8rem", lineHeight: 1.6 }}>
                Recorded on the rule and on every trade it produces, so a
                position can be traced back to this exact version.
              </p>
            </section>
          ) : null}

          {withheld.length ? (
            <section className="card card-flat">
              <div className="card-head">
                <h2>
                  <ShieldAlert className="ico" aria-hidden /> Not on this list
                </h2>
              </div>
              {/* Spelled out rather than omitted. Somebody who used the
                  Telegram bot knows these exist, and silence reads like an
                  oversight where a reason reads like a decision. */}
              {withheld.map((w) => (
                <p key={w.id} className="muted"
                   style={{ fontSize: ".78rem", lineHeight: 1.6 }}>
                  <strong style={{ color: "var(--a4t-text)" }}>{w.label}</strong>{" "}
                  <span className="dim mono">({w.id})</span> — {w.reason}
                </p>
              ))}
            </section>
          ) : null}

          {unclassified?.length ? (
            <section className="card card-flat">
              <p className="muted" style={{ fontSize: ".78rem", lineHeight: 1.6 }}>
                The engine registers {unclassified.length} strategy
                {unclassified.length === 1 ? "" : "ies"} this release has no
                description for, so they are not offered:{" "}
                <span className="mono">{unclassified.join(", ")}</span>.
              </p>
            </section>
          ) : null}
        </aside>
      </div>
    </main>
  );
}
