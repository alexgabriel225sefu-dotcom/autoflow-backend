"use client";
import type { WhyRead } from "@/lib/api";
import { useRead } from "@/lib/use-api";
import { ErrorNotice } from "./state";
import { When } from "./table";

/**
 * “Why isn't it trading?” — the question a waiting client actually asks.
 *
 * The Telegram bot answered it with /why. Without it, a bot that is working
 * and refusing every candidate looks identical to one that is broken. The
 * reason and its sentence come from the server; this card only shows them.
 *
 * Two lists, kept apart on purpose: what the loop refused since it last
 * started (fast, but lost on a restart) and the persistent decision log
 * (has the instrument, survives a restart). An empty list is worded as
 * "nothing recorded", never as "there was no reason".
 */
export function WhyCard() {
  const why = useRead<WhyRead>("automation/why", 30_000);
  const raw = why.result?.ok ? why.result.data : null;
  // A reply of the wrong shape is reported, not rendered: an explanation that
  // crashes the dashboard is the worst place for the page to fail.
  const wellFormed = !!raw && typeof raw.summary === "string"
    && Array.isArray(raw.skips) && Array.isArray(raw.recorded);
  const w = wellFormed ? raw : null;

  return (
    <section className="card" aria-label="Why it is or is not trading">
      <div className="card-head">
        <h2>Why no trade right now</h2>
      </div>
      {why.result && !why.result.ok
        ? <ErrorNotice error={why.result} onRetry={why.reload} /> : null}
      {!why.result ? <p className="muted">Reading the engine…</p> : null}
      {raw && !wellFormed ? (
        <p className="muted">The explanation came back in a form this page cannot read.</p>
      ) : null}
      {w ? (
        <>
          <p data-reason={w.reason}>{w.summary}</p>
          {w.marketOpen !== null ? (
            <p className="muted" style={{ fontSize: ".8rem" }}>
              Market: {w.marketOpen ? "open" : "closed"}
            </p>
          ) : null}

          {w.skips.length ? (
            <>
              <h3 style={{ fontSize: ".85rem", marginTop: "var(--sp-3)" }}>
                Refused since it last started
                {w.skipsToday != null ? ` (${w.skipsToday} today)` : ""}
              </h3>
              <ul className="plain-list">
                {w.skips.slice(0, 5).map((s, i) => (
                  <li key={`${s.time}-${i}`}>
                    <span className="dim">{s.time}</span> — {s.reason}
                  </li>
                ))}
              </ul>
            </>
          ) : null}

          {w.recorded.length ? (
            <>
              <h3 style={{ fontSize: ".85rem", marginTop: "var(--sp-3)" }}>
                From the decision log
              </h3>
              <ul className="plain-list">
                {w.recorded.slice(0, 5).map((r, i) => (
                  <li key={`${r.at}-${i}`}>
                    {r.at ? <span className="dim"><When ts={r.at} /></span> : null}
                    {r.symbol ? <span className="muted"> · {r.symbol}</span> : null}
                    {" — "}{r.reason}
                  </li>
                ))}
              </ul>
            </>
          ) : null}

          {!w.skips.length && !w.recorded.length ? (
            <p className="muted" style={{ fontSize: ".8rem" }}>
              {w.recordedReadable
                ? "No refusals recorded yet. That is not a verdict on the engine: a restart clears the live list, and the log fills as it checks."
                : "The decision log could not be read just now."}
            </p>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
