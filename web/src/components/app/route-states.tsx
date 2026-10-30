"use client";
/**
 * What a route shows when it is loading, broken or missing.
 *
 * Nothing from the thrown error is rendered: in production Next replaces a
 * server error's message with a digest for exactly that reason, and a client
 * error's message can carry internals. Only the digest (a hash that matches a
 * server log line) is offered, as a reference to quote.
 */
import Link from "next/link";

export function digestOf(error: unknown): string | null {
  if (typeof error !== "object" || error === null) return null;
  const d = (error as { digest?: unknown }).digest;
  return typeof d === "string" && d ? d : null;
}

export function RouteError({
  error, retry,
}: { error: unknown; retry: () => void }) {
  const ref = digestOf(error);
  return (
    <main>
      <section className="card" role="alert">
        <div className="card-head"><h2>Something went wrong</h2></div>
        <p className="muted">
          This page could not be shown. Nothing was changed on your account or
          at your broker by this error.
        </p>
        {ref ? <p className="dim mono" style={{ fontSize: ".78rem" }}>Reference: {ref}</p> : null}
        <div className="btn-row" style={{ marginTop: ".7rem" }}>
          <button className="btn" onClick={() => retry()}>Try again</button>
          <Link className="btn btn-ghost" href="/dashboard">Back to the dashboard</Link>
          <Link className="btn btn-ghost" href="/help">Help</Link>
        </div>
      </section>
    </main>
  );
}

export function RouteNotFound() {
  return (
    <main>
      <section className="card">
        <div className="card-head"><h2>Page not found</h2></div>
        <p className="muted">
          There is nothing at this address. It may have moved, or the link may
          be mistyped.
        </p>
        <div className="btn-row" style={{ marginTop: ".7rem" }}>
          <Link className="btn" href="/dashboard">Back to the dashboard</Link>
          <Link className="btn btn-ghost" href="/">Home</Link>
        </div>
      </section>
    </main>
  );
}

export function RouteLoading() {
  return (
    <main aria-busy="true">
      <p className="muted" role="status" style={{ padding: ".75rem 0", fontSize: ".85rem" }}>
        Loading…
      </p>
      <section className="card" aria-hidden>
        <span className="skel" style={{ display: "block", width: "40%", height: "1.2em" }} />
        <span className="skel" style={{ display: "block", width: "100%", height: "5em", marginTop: ".8rem" }} />
      </section>
    </main>
  );
}
