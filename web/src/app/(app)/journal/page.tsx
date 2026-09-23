"use client";
import { useState } from "react";
import { useRead } from "@/lib/use-api";
import { ErrorNotice, Spinner } from "@/components/app/state";
import { When } from "@/components/app/table";
import { humanise } from "@/components/app/rule-summary";
import type { JournalEntry, JournalPage } from "@/lib/api";

const STATUSES = [
  "", "evaluated", "hold", "reject", "execution_requested", "order_sent",
  "order_confirmed", "order_rejected", "position_closed", "broker_error",
  "automation_started", "automation_paused", "automation_stopped",
];
const PAGE = 25;

/** The statuses where the engine ran and deliberately placed nothing. */
const QUIET = new Set(["hold", "reject"]);
/** The statuses that mean something went wrong at the broker or in the rule. */
const BAD = new Set(["order_rejected", "broker_error", "reject"]);

function tone(e: JournalEntry): string {
  const v = e.decision?.verdict;
  if (v === "BUY") return "side-long";
  if (v === "SELL") return "side-short";
  if (e.status && BAD.has(e.status)) return "cond-fail";
  return "";
}

export default function JournalView() {
  const [status, setStatus] = useState("");
  const [symbol, setSymbol] = useState("");
  const [offset, setOffset] = useState(0);
  const qs = new URLSearchParams({ limit: String(PAGE), offset: String(offset) });
  if (status) qs.set("status", status);
  if (symbol.trim()) qs.set("symbol", symbol.trim());
  const r = useRead<JournalPage>(`journal?${qs.toString()}`);

  return (
    <main>
      <div className="page-head">
        <div>
          <h1>Journal</h1>
          <span className="sub">
            Every evaluation, including the ones that decided to do nothing.
          </span>
        </div>
        {r.result?.ok ? (
          <span className="pill pill-muted">{r.result.data.total} entries</span>
        ) : null}
      </div>

      <section className="card">
        <div className="grid grid-2">
          <label className="field" style={{ marginBottom: 0 }}>
            <span>Status</span>
            <select value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }}>
              {STATUSES.map((s) => (
                <option key={s} value={s}>{s ? humanise(s) : "All"}</option>
              ))}
            </select>
          </label>
          <label className="field" style={{ marginBottom: 0 }}>
            <span>Symbol</span>
            <input value={symbol} placeholder="EURUSD"
                   onChange={(e) => { setSymbol(e.target.value); setOffset(0); }} />
          </label>
        </div>
      </section>

      {r.loading && !r.result ? <Spinner /> : null}
      {r.result && !r.result.ok ? <ErrorNotice error={r.result} onRetry={r.reload} /> : null}
      {r.result?.ok ? (
        r.result.data.entries.length ? (
          <>
            {/* The journal is a record, not a grid of numbers: each entry gets
                the room to say what was decided and why, on both widths. */}
            <div className="records">
              {r.result.data.entries.map((e) => (
                <article className="record" key={e.entryId}>
                  <div className="record-head">
                    <span className="record-title">
                      <span className={tone(e)}>
                        {e.decision?.verdict ?? humanise(e.status ?? e.kind)}
                      </span>
                      {e.symbol ? <span className="muted"> · {e.symbol}</span> : null}
                    </span>
                    <span className="dim" style={{ fontSize: ".74rem" }}><When ts={e.ts} /></span>
                  </div>

                  <p className="muted" style={{ fontSize: ".82rem" }}>
                    {e.error ?? e.decision?.reason ?? humanise(e.status ?? e.kind)}
                  </p>

                  {e.decision?.conditions?.length ? (
                    <div className="btn-row" style={{ marginTop: ".45rem" }}>
                      {e.decision.conditions.map((c, i) => (
                        <span
                          key={i}
                          className={
                            c.passed === true ? "pill pill-ok"
                              : c.passed === false ? "pill pill-warn" : "pill pill-muted"
                          }
                          title={c.detail}
                        >
                          {humanise(c.id)}
                        </span>
                      ))}
                    </div>
                  ) : null}

                  <div className="btn-row" style={{ marginTop: ".45rem" }}>
                    {e.status && QUIET.has(e.status) ? (
                      <span className="pill pill-muted">No order placed</span>
                    ) : null}
                    {e.decision?.refusalCode ? (
                      <span className="pill pill-warn">{e.decision.refusalCode}</span>
                    ) : null}
                    {e.ruleDocId ? (
                      <a className="pill pill-accent mono" href={`/rules/${e.ruleDocId}`}>
                        rule {e.ruleDocId.slice(0, 8)}
                      </a>
                    ) : null}
                    {e.accountId ? (
                      <span className="pill pill-muted mono">#{e.accountId}</span>
                    ) : null}
                  </div>
                </article>
              ))}
            </div>

            <div className="btn-row" style={{ marginTop: ".85rem" }}>
              <button className="btn btn-ghost btn-sm" disabled={offset === 0}
                      onClick={() => setOffset(Math.max(0, offset - PAGE))}>Previous</button>
              <button className="btn btn-ghost btn-sm" disabled={!r.result.data.hasMore}
                      onClick={() => setOffset(offset + PAGE)}>Next</button>
              <span className="dim" style={{ fontSize: ".78rem" }}>
                {offset + 1}–{offset + r.result.data.entries.length} of {r.result.data.total}
              </span>
            </div>
          </>
        ) : (
          <section className="card">
            <p className="empty">Nothing recorded for this filter.</p>
          </section>
        )
      ) : null}
    </main>
  );
}
