"use client";
import { useRead } from "@/lib/use-api";
import { ErrorNotice, Spinner } from "@/components/app/state";

/**
 * Which linked accounts are demo, which are live, and why. The type is cTrader's
 * and the sentences are the server's; this prints them. An account whose type
 * was not reported is shown as unverified, never as demo.
 */
const LABEL = { demo: "Demo", live: "Live", unverified: "Not verified" } as const;

export function AccountKinds() {
  const r = useRead<import("@/lib/api").AccountKindsRead>("account-kinds", 60_000);
  const d = r.result?.ok ? r.result.data : null;
  return (
    <section className="card" aria-label="Account types">
      <div className="card-head"><h2>Demo or live</h2></div>
      {r.loading && !r.result ? <Spinner /> : null}
      {r.result && !r.result.ok ? <ErrorNotice error={r.result} onRetry={r.reload} /> : null}
      {d && !d.connected ? <p className="empty">No cTrader account is connected.</p> : null}
      {d?.connected ? (
        <>
          <p className="muted" style={{ fontSize: ".82rem" }}>
            {d.summary.demo} demo · {d.summary.live} live · {d.summary.unverified} not verified
          </p>
          <ul className="plain-list">
            {d.accounts.map((a) => (
              <li key={String(a.ctid)} data-kind={a.kind}>
                <strong className="mono">#{a.ctid}</strong>{" "}
                <span className={a.kind === "live" ? "pill pill-warn" : a.kind === "demo" ? "pill pill-ok" : "pill pill-muted"}>
                  {LABEL[a.kind]}
                </span>
                {a.selected ? <span className="pill pill-accent"> Selected</span> : null}
                <span className="muted" style={{ display: "block", fontSize: ".8rem" }}>{a.basis}</span>
                <span style={{ display: "block", fontSize: ".82rem" }}>{a.liveText}</span>
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </section>
  );
}
