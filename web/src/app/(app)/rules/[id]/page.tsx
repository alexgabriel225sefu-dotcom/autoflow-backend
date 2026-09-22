"use client";
import { use, useState } from "react";
import { api, type ApiError, type AutomationState, type CandlesRead,
         type CtraderStatus, type Me, type PreviewResult,
         type RuleDoc } from "@/lib/api";
import { useRead } from "@/lib/use-api";
import { ConfirmAction } from "@/components/app/shell";
import { ErrorNotice, LicencePill, ReadPanel, Spinner, StatusPill } from "@/components/app/state";

function Verdict({ p }: { p: PreviewResult }) {
  const v = p.decision.verdict;
  const cls = v === "BUY" ? "verdict-buy" : v === "SELL" ? "verdict-sell" : "verdict-hold";
  return (
    <div>
      <p className={`verdict ${cls}`}>{v}</p>
      {/* HOLD and REJECT are labelled as non-executable in words, not left
          for the reader to infer from a greyer colour. */}
      {!p.wouldTrade ? (
        <p className="muted">
          {v === "REJECT"
            ? `This rule could not run${p.decision.refusalCode ? ` (${p.decision.refusalCode})` : ""}. No order would be placed.`
            : "The rule ran and chose not to act. No order would be placed."}
        </p>
      ) : (
        <p className="muted">
          On this snapshot the rule would open a position. This preview placed
          nothing.
        </p>
      )}
      <p className="muted">{p.decision.reason}</p>
      <table className="tbl">
        <thead><tr><th>Condition</th><th>Result</th><th>Detail</th></tr></thead>
        <tbody>
          {p.decision.conditions.map((c, i) => (
            <tr key={i}>
              <td>{c.id}</td>
              <td className={c.passed === true ? "cond-pass" : c.passed === false ? "cond-fail" : "cond-unknown"}>
                {c.passed === true ? "met" : c.passed === false ? "not met" : "unknown"}
              </td>
              <td className="muted">{c.detail}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function RuleDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const rule = useRead<{ rule: RuleDoc }>(`rules/${id}`);
  const me = useRead<Me>("me");
  const ct = useRead<CtraderStatus>("ctrader/status");
  const auto = useRead<AutomationState>("automation", 20_000);

  const [problems, setProblems] = useState<string[] | null>(null);
  const [actErr, setActErr] = useState<ApiError | null>(null);
  const [bars, setBars] = useState<CandlesRead | null>(null);
  const [barsErr, setBarsErr] = useState<ApiError | null>(null);
  const [symbol, setSymbol] = useState("");
  const [timeframe, setTimeframe] = useState("");
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [previewErr, setPreviewErr] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

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
    const q = new URLSearchParams({
      symbol: sym, timeframe: tf, limit: "300",
    });
    const r = await api<CandlesRead>(
      `accounts/${selected!.ctid}/candles?${q.toString()}`);
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
          candles: bars.candles.map(({ open, high, low, close }) =>
            ({ open, high, low, close })),
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

  return (
    <main>
      <div className="card-head">
        <h1>{doc.name || "(untitled)"}</h1>
        <span className="muted mono">v{doc.version} · {doc.state}</span>
      </div>

      <section className="card">
        <h2>Configuration</h2>
        <table className="tbl">
          <tbody>
            <tr><th>Instruments</th><td>{(doc.symbols ?? []).join(", ")}</td></tr>
            <tr><th>Timeframe</th><td>{doc.timeframe}</td></tr>
            <tr><th>Sides</th><td>{String(doc.sides)}</td></tr>
            <tr><th>State</th><td>{doc.state}</td></tr>
          </tbody>
        </table>
        {doc.state !== "draft" ? (
          <p className="muted">
            An active rule is frozen. Editing it creates a new version as a
            draft; the running version keeps its terms.
          </p>
        ) : null}
      </section>

      <section className="card">
        <h2>Validate</h2>
        <button className="btn btn-ghost" onClick={validate} disabled={busy}>
          Check this rule
        </button>
        {problems !== null ? (
          problems.length ? (
            <div className="notice notice-error" role="alert">
              <p>This rule is not valid yet:</p>
              <ul className="problems">{problems.map((p) => <li key={p}>{p}</li>)}</ul>
            </div>
          ) : <p className="pill pill-ok" style={{ marginTop: ".5rem" }}>Valid</p>
        ) : null}
      </section>

      <section className="card">
        <h2>Preview a decision</h2>
        <p className="muted">
          Read-only. Bars are fetched from your connected account and the rule
          is evaluated against exactly those — nothing is placed, no order is
          created, and nothing is written to the execution journal.
        </p>

        {!selected ? (
          <p className="notice">
            Select a cTrader account to fetch market data.{" "}
            <a href="/accounts">Accounts</a>
          </p>
        ) : (
          <>
            <div className="grid grid-2">
              <label className="field"><span>Account</span>
                <input readOnly value={`#${selected.ctid} (${selected.mode})`} /></label>
              <label className="field"><span>Instrument</span>
                <select value={sym} onChange={(e) => { setSymbol(e.target.value); setBars(null); setPreview(null); }}>
                  {ruleSymbols.map((s) => <option key={s} value={s}>{s}</option>)}
                </select></label>
              <label className="field"><span>Timeframe</span>
                <select value={tf} onChange={(e) => { setTimeframe(e.target.value); setBars(null); setPreview(null); }}>
                  {["1m", "5m", "15m", "30m", "1h", "4h", "1d"].map((t) =>
                    <option key={t} value={t}>{t}</option>)}
                </select>
                {tfMismatch ? (
                  <span className="muted">
                    This rule runs on {String(doc.timeframe)}. Previewing on
                    another timeframe will be refused.
                  </span>
                ) : null}
              </label>
            </div>

            <div className="btn-row">
              <button className="btn btn-ghost" onClick={loadBars} disabled={busy || !sym}>
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
              <p className="muted" style={{ marginTop: ".5rem" }}>
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
            {preview ? <div style={{ marginTop: "1rem" }}><Verdict p={preview} /></div> : null}
          </>
        )}
      </section>

      <section className="card">
        <h2>Activation</h2>
        <div className="card-head">
          <LicencePill state={licence} />
          <StatusPill mode={selected?.mode} />
        </div>
        {doc.state === "draft" ? (
          licence !== "active" ? (
            /* No licence — no path to activation, and the reason is on screen
               rather than discovered by pressing a button. */
            <p className="notice notice-warn">
              Activating a rule needs an active licence.{" "}
              <a href="/license">See your licence</a>
            </p>
          ) : (
            <ConfirmAction
              label="Activate this rule"
              question="Activate and freeze this version?"
              onConfirm={activate}
            />
          )
        ) : <p className="muted">This rule is {doc.state}.</p>}
        {actErr ? <ErrorNotice error={actErr} /> : null}
      </section>

      <section className="card">
        <h2>Automation (demo)</h2>
        {!selected ? (
          <p className="notice">
            Select a cTrader account first. <a href="/accounts">Accounts</a>
          </p>
        ) : !isDemo ? (
          /* Not demo — no control that could start trading is rendered at
             all. The backend refuses it too; this only avoids offering it. */
          <p className="notice notice-warn">
            The selected account is not a demo account. Automation runs on demo
            accounts only.
          </p>
        ) : (
          <>
            <p className="muted">
              Running on demo account <span className="mono">#{selected.ctid}</span>.
              Status: <strong>{running?.state ?? "unknown"}</strong>
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
    </main>
  );
}
