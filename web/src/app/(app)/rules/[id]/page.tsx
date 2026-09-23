"use client";
import { use, useEffect, useState } from "react";
import {
  Check, CircleAlert, Minus, Play, RefreshCw, ShieldCheck, Sparkles,
} from "lucide-react";
import { api, type ApiError, type AutomationState, type CandlesRead,
         type ConditionSpec, type CtraderStatus, type Me, type PreviewResult,
         type RuleDoc } from "@/lib/api";
import { useRead } from "@/lib/use-api";
import { ConfirmAction } from "@/components/app/shell";
import { ErrorNotice, LicencePill, ReadPanel, Spinner, StatusPill } from "@/components/app/state";
import { RuleSentence, RuleTerms, humanise } from "@/components/app/rule-summary";
import { TIMEFRAMES } from "@/components/app/rule-form";

/**
 * What a preview decided, as a first-class outcome.
 *
 * HOLD and REJECT are not empty states. HOLD means the rule ran and chose not
 * to act; REJECT means it could not run at all. Rendering either as a blank
 * panel would teach the client that "nothing appeared" and "nothing would
 * happen" are the same thing, and they are not — one of them is a bug in
 * their rule.
 */
function Verdict({ p, specs }: { p: PreviewResult; specs: Record<string, ConditionSpec> | null }) {
  const v = p.decision.verdict;
  const kind = v === "BUY" || v === "SELL" ? v.toLowerCase()
    : v === "REJECT" ? "reject" : v === "CLOSE" ? "close" : "hold";
  const cls = v === "BUY" ? "verdict-buy" : v === "SELL" ? "verdict-sell"
    : v === "CLOSE" ? "verdict-close"
    : v === "REJECT" ? "verdict-reject" : "verdict-hold";

  const headline = p.wouldTrade ? "SETUP" : v === "REJECT" ? "REJECT" : v;
  const note = p.wouldTrade
    ? `On this snapshot the rule would open a ${v} position. This preview placed nothing.`
    : v === "REJECT"
      ? `This rule could not run${p.decision.refusalCode ? ` (${p.decision.refusalCode})` : ""}. No order would be placed.`
      : "The rule ran and chose not to act. No order would be placed.";

  const met = p.decision.conditions.filter((c) => c.passed === true).length;
  const unknown = p.decision.conditions.filter((c) => c.passed === null).length;

  return (
    <div style={{ marginTop: ".9rem" }}>
      <div className="verdict-banner" data-kind={kind}>
        <div className="vb-body" style={{ flex: 1 }}>
          {/* `.verdict` marks a rendered decision. It appears only when one
              exists, which is what separates "no setup" from "no data". */}
          <p className={`verdict ${cls}`}>
            {headline}
            {p.wouldTrade ? <span className="muted" style={{ fontSize: "1rem" }}> · {v}</span> : null}
          </p>
          <p className="vb-note">{note}</p>
        </div>
        <div style={{ textAlign: "right", flex: "none" }}>
          <div className="label-xs">Conditions met</div>
          <div className="mono" style={{ fontSize: "1.1rem", fontWeight: 650 }}>
            {met}/{p.decision.conditions.length}
          </div>
          {unknown ? <div className="cond-unknown" style={{ fontSize: ".72rem" }}>{unknown} unknown</div> : null}
        </div>
      </div>

      <p className="muted" style={{ fontSize: ".85rem", margin: ".7rem 0 .3rem" }}>
        {p.decision.reason}
      </p>

      <div>
        {p.decision.conditions.map((c, i) => (
          <div className="cond-row" key={i}>
            <span className="cond-mark"
                  data-r={c.passed === true ? "pass" : c.passed === false ? "fail" : "unknown"}
                  aria-hidden>
              {c.passed === true ? <Check style={{ width: 12, height: 12 }} />
                : c.passed === false ? <Minus style={{ width: 12, height: 12 }} />
                : "?"}
            </span>
            <span style={{ flex: 1, minWidth: 0 }}>
              <span className="cond-name">{humanise(c.id)}</span>{" "}
              <span className={
                c.passed === true ? "cond-pass" : c.passed === false ? "cond-fail" : "cond-unknown"
              } style={{ fontSize: ".78rem", fontWeight: 600 }}>
                {c.passed === true ? "met" : c.passed === false ? "not met" : "unknown"}
              </span>
              <span className="cond-detail" style={{ display: "block" }}>{c.detail}</span>
              {specs?.[c.id]?.doc ? (
                <span className="dim" style={{ fontSize: ".74rem" }}>{specs[c.id].doc}</span>
              ) : null}
            </span>
          </div>
        ))}
      </div>

      {/* "unknown" is never folded into "not met". A condition that could not
          be computed is a different fact from one that was computed as false. */}
      {unknown ? (
        <p className="notice" style={{ fontSize: ".8rem" }}>
          {unknown} condition{unknown === 1 ? "" : "s"} could not be computed on
          this data — usually too little history. The engine treats unknown as
          unknown rather than as false.
        </p>
      ) : null}
    </div>
  );
}

export default function RuleDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const rule = useRead<{ rule: RuleDoc }>(`rules/${id}`);
  const me = useRead<Me>("me");
  const ct = useRead<CtraderStatus>("ctrader/status");
  const auto = useRead<AutomationState>("automation", 20_000);

  const [specs, setSpecs] = useState<Record<string, ConditionSpec> | null>(null);
  const [problems, setProblems] = useState<string[] | null>(null);
  const [actErr, setActErr] = useState<ApiError | null>(null);
  const [bars, setBars] = useState<CandlesRead | null>(null);
  const [barsErr, setBarsErr] = useState<ApiError | null>(null);
  const [symbol, setSymbol] = useState("");
  const [timeframe, setTimeframe] = useState("");
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [previewErr, setPreviewErr] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void api<{ conditions: Record<string, ConditionSpec> }>("conditions")
      .then((r) => { if (r.ok) setSpecs(r.data.conditions); });
  }, []);

  const doc = rule.result?.ok ? rule.result.data.rule : null;
  const licence = me.result?.ok ? me.result.data.licence.state : undefined;
  const selected = ct.result?.ok ? ct.result.data.selected : null;
  const isDemo = selected?.mode === "demo";
  const running = auto.result?.ok ? auto.result.data : null;
  const runningThis = running?.state !== "stopped" && running?.ruleDocId === id;
  const ruleSymbols = (doc?.symbols as string[] | undefined) ?? [];
  const sym = symbol || ruleSymbols[0] || "";
  const tf = timeframe || String(doc?.timeframe ?? "1h");
  // The evaluator refuses a snapshot whose timeframe is not the rule's, so a
  // mismatch is flagged here rather than delivered as a puzzling REJECT.
  const tfMismatch = !!doc && tf !== String(doc.timeframe);

  async function validate() {
    setBusy(true); setActErr(null);
    const r = await api<{ valid: boolean; problems: string[] }>(
      `rules/${id}/validate`, { method: "POST" });
    setBusy(false);
    if (!r.ok) return setActErr(r);
    setProblems(r.data.problems);
  }

  async function activate() {
    setActErr(null);
    const r = await api(`rules/${id}/activate`, { method: "POST" });
    if (!r.ok) { setActErr(r); return `${r.code}`; }
    void rule.reload();
    return "Activated";
  }

  /**
   * Fetch real bars, then evaluate against exactly those.
   *
   * The two steps are kept apart on screen because they fail differently. If
   * the candles request fails, the preview is NOT run and no verdict is
   * shown: a HOLD rendered over a failed market read would say "no setup"
   * about data nobody ever received.
   */
  async function loadBars() {
    setBusy(true); setBarsErr(null); setBars(null); setPreview(null);
    const q = new URLSearchParams({ symbol: sym, timeframe: tf, limit: "300" });
    const r = await api<CandlesRead>(`accounts/${selected!.ctid}/candles?${q.toString()}`);
    setBusy(false);
    if (!r.ok) return setBarsErr(r);
    setBars(r.data);
  }

  async function runPreview() {
    if (!bars || bars.status !== "ok" || !bars.candles?.length) return;
    setBusy(true); setPreviewErr(null); setPreview(null);
    // ts comes from the DATA, not from this browser's clock: the snapshot
    // must describe the moment those bars describe, or every session and
    // weekday condition answers a question about now instead of about them.
    const last = bars.candles[bars.candles.length - 1];
    const ts = typeof last.time === "number" ? last.time : Math.floor(Date.now() / 1000);
    const r = await api<PreviewResult>(`rules/${id}/preview`, {
      method: "POST",
      body: {
        snapshot: {
          candles: bars.candles.map(({ open, high, low, close }) => ({ open, high, low, close })),
          ts, symbol: bars.symbol, timeframe: bars.timeframe,
        },
      },
    });
    setBusy(false);
    if (!r.ok) return setPreviewErr(r);
    setPreview(r.data);
  }

  async function control(action: "start" | "pause" | "resume" | "stop") {
    const body = action === "start" ? { ruleDocId: id } : undefined;
    const r = await api<AutomationState & { started?: boolean }>(
      `automation/${action}`, { method: "POST", body });
    void auto.reload();
    if (!r.ok) return `${r.code}: ${r.message}`;
    return `Automation is now ${r.data.state}`;
  }

  if (rule.result && !rule.result.ok) {
    return <main><h1>Rule</h1><ErrorNotice error={rule.result} /></main>;
  }
  if (!doc) return <main><h1>Rule</h1><Spinner /></main>;

  const statePill =
    doc.state === "active" ? "pill pill-ok"
      : doc.state === "draft" ? "pill pill-accent" : "pill pill-muted";

  return (
    <main>
      <div className="page-head">
        <div style={{ minWidth: 0 }}>
          <h1>{doc.name || "(untitled)"}</h1>
          <span className="btn-row" style={{ marginTop: ".35rem" }}>
            <span className={statePill}>{doc.state}</span>
            <span className="pill pill-muted mono">v{doc.version}</span>
            {runningThis ? <span className="pill pill-accent">automation {running?.state}</span> : null}
          </span>
        </div>
        <span className="btn-row">
          <button className="btn btn-ghost" onClick={validate} disabled={busy}>
            <ShieldCheck className="ico" aria-hidden /> Check this rule
          </button>
        </span>
      </div>

      <RuleSentence doc={doc} specs={specs} />

      {problems !== null ? (
        problems.length ? (
          <div className="notice notice-error" role="alert">
            <div className="notice-head"><strong>Not valid yet</strong></div>
            <ul className="problems">{problems.map((p) => <li key={p}>{p}</li>)}</ul>
          </div>
        ) : (
          <div className="notice notice-accent" role="status">
            <span className="pill pill-ok">Valid</span>{" "}
            Every field passes the server&rsquo;s own validation.
          </div>
        )
      ) : null}

      <div className="grid grid-main" style={{ marginTop: ".85rem" }}>
        {/* ── preview: the centre of the page ───────────────────────── */}
        <section className="card">
          <div className="card-head">
            <h2 style={{ display: "flex", alignItems: "center", gap: ".4rem" }}>
              <Sparkles className="ico" aria-hidden style={{ width: 15, height: 15 }} />
              Preview a decision
            </h2>
          </div>
          <p className="muted" style={{ fontSize: ".82rem", marginBottom: ".7rem" }}>
            Read-only. Bars are fetched from your connected account and the rule
            is evaluated against exactly those — nothing is placed, no order is
            created, and nothing is written to the execution journal.
          </p>

          {!selected ? (
            <div className="notice">
              <p>Select a cTrader account to fetch market data.</p>
              <a className="btn btn-sm" href="/accounts">Accounts</a>
            </div>
          ) : (
            <>
              <div className="grid grid-2">
                <label className="field"><span>Instrument</span>
                  <select value={sym} onChange={(e) => { setSymbol(e.target.value); setBars(null); setPreview(null); }}>
                    {ruleSymbols.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select></label>
                <label className="field"><span>Timeframe</span>
                  <select value={tf} onChange={(e) => { setTimeframe(e.target.value); setBars(null); setPreview(null); }}>
                    {TIMEFRAMES.map((t) => <option key={t} value={t}>{t}</option>)}
                  </select>
                  {tfMismatch ? (
                    <span className="field-note" style={{ color: "var(--a4t-short)" }}>
                      This rule runs on {String(doc.timeframe)}. Previewing on
                      another timeframe will be refused.
                    </span>
                  ) : null}
                </label>
              </div>
              <p className="dim" style={{ fontSize: ".75rem", marginBottom: ".6rem" }}>
                Account <span className="mono">#{selected.ctid}</span> ({selected.mode})
              </p>

              <div className="btn-row">
                <button className="btn btn-ghost" onClick={loadBars} disabled={busy || !sym}>
                  <RefreshCw className="ico" aria-hidden />
                  {busy && !bars ? "Fetching…" : "Fetch market data"}
                </button>
                <button className="btn" onClick={runPreview}
                        disabled={busy || !bars || bars.status !== "ok" || !bars.candles?.length}>
                  {busy && bars ? "Evaluating…" : "Preview"}
                </button>
              </div>

              {/* A failed market read is shown as a failed market read. The
                  preview is not run, so no verdict can be mistaken for one
                  reached on data that never arrived. */}
              {barsErr ? <ErrorNotice error={barsErr} onRetry={loadBars} /> : null}
              {bars && bars.status !== "ok" ? (
                <ReadPanel read={bars}><span /></ReadPanel>
              ) : null}

              {bars?.status === "ok" ? (
                <p className="dim" style={{ marginTop: ".6rem", fontSize: ".75rem" }}>
                  {/* Source and as-of, on screen. Numbers without a time are a
                      screenshot, not data. */}
                  Source: cTrader account <span className="mono">#{bars.accountId}</span> ·{" "}
                  {bars.count} bars of {bars.symbol} {bars.timeframe}
                  {bars.count !== bars.requested ? ` (asked for ${bars.requested})` : ""} ·{" "}
                  as of{" "}
                  <span className="mono">
                    {typeof bars.candles?.[bars.candles.length - 1]?.time === "number"
                      ? new Date(bars.candles[bars.candles.length - 1].time! * 1000).toISOString()
                      : "unknown"}
                  </span>
                </p>
              ) : null}

              {previewErr ? <ErrorNotice error={previewErr} /> : null}
              {preview ? <Verdict p={preview} specs={specs} /> : null}
            </>
          )}
        </section>

        <div>
          {/* ── activation ──────────────────────────────────────────── */}
          <section className="card">
            <div className="card-head">
              <h2>Activation</h2>
              <LicencePill state={licence} />
            </div>
            {doc.state === "draft" ? (
              licence !== "active" ? (
                /* No licence — no path to activation, and the reason is on
                   screen rather than discovered by pressing a button. */
                <div className="notice notice-warn">
                  <p>Activating a rule needs an active licence.</p>
                  <a className="btn btn-sm btn-ghost" href="/license">See your licence</a>
                </div>
              ) : (
                <ConfirmAction
                  label="Activate this rule"
                  question="Activate and freeze this version?"
                  onConfirm={activate}
                />
              )
            ) : (
              <p className="muted" style={{ fontSize: ".85rem" }}>
                This rule is {doc.state}. An active rule is frozen — editing it
                creates a new version as a draft, and the running version keeps
                its terms.
              </p>
            )}
            {actErr ? <ErrorNotice error={actErr} /> : null}
          </section>

          {/* ── automation ──────────────────────────────────────────── */}
          <section className="card">
            <div className="card-head">
              <h2 style={{ display: "flex", alignItems: "center", gap: ".4rem" }}>
                <Play className="ico" aria-hidden style={{ width: 14, height: 14 }} />
                Automation
              </h2>
              <StatusPill mode={selected?.mode} />
            </div>
            {!selected ? (
              <div className="notice">
                <p>Select a cTrader account first.</p>
                <a className="btn btn-sm btn-ghost" href="/accounts">Accounts</a>
              </div>
            ) : !isDemo ? (
              /* Not demo — no control that could start trading is rendered at
                 all. The backend refuses it too; this only avoids offering it. */
              <div className="notice notice-warn" role="alert">
                <p style={{ display: "flex", gap: ".4rem" }}>
                  <CircleAlert className="ico" aria-hidden style={{ width: 15, height: 15, flex: "none" }} />
                  The selected account is not a demo account. Automation runs on
                  demo accounts only.
                </p>
              </div>
            ) : (
              <>
                <p className="muted" style={{ fontSize: ".83rem", marginBottom: ".6rem" }}>
                  Demo account <span className="mono">#{selected.ctid}</span> ·{" "}
                  <strong style={{ color: "var(--a4t-text)" }}>{running?.state ?? "unknown"}</strong>
                </p>
                <div className="btn-row">
                  {running?.state === "stopped" || !runningThis ? (
                    <ConfirmAction
                      label="Start on demo"
                      question="Start automation for this rule?"
                      disabled={doc.state !== "active" || licence !== "active"}
                      disabledReason={doc.state !== "active"
                        ? "Activate the rule first"
                        : licence !== "active" ? "An active licence is required" : undefined}
                      onConfirm={() => control("start")}
                    />
                  ) : null}
                  {runningThis && running?.state === "running" ? (
                    <ConfirmAction label="Pause" question="Pause automation?"
                                   onConfirm={() => control("pause")} />
                  ) : null}
                  {runningThis && running?.state === "paused" ? (
                    <ConfirmAction label="Resume" question="Resume automation?"
                                   onConfirm={() => control("resume")} />
                  ) : null}
                  {runningThis && running?.state !== "stopped" ? (
                    <ConfirmAction label="Stop" danger question="Stop automation?"
                                   onConfirm={() => control("stop")} />
                  ) : null}
                </div>
              </>
            )}
          </section>
        </div>
      </div>

      {/* ── the complete document ──────────────────────────────────── */}
      <section className="card" style={{ marginTop: ".85rem" }}>
        <div className="card-head">
          <h2>Rule terms</h2>
          <span className="dim" style={{ fontSize: ".75rem" }}>
            Every field, including the ones left at their default
          </span>
        </div>
        <RuleTerms doc={doc} specs={specs} />
      </section>
    </main>
  );
}
