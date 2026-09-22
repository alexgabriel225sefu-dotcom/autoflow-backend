"use client";
/**
 * The pieces that render backend state honestly.
 *
 * Each of these exists because the obvious JSX gets it wrong. `{positions.map(...)}`
 * over an undefined list renders nothing, which looks exactly like an account
 * with no positions — so `ReadPanel` refuses to render children at all unless
 * the backend said status "ok", and shows the real reason otherwise.
 */
import type { ApiError, ReadState } from "@/lib/api";

export function StatusPill({ mode }: { mode?: "demo" | "live" | null }) {
  if (!mode) return <span className="pill pill-muted">No account selected</span>;
  return (
    <span className={mode === "live" ? "pill pill-live" : "pill pill-demo"}>
      {mode === "live" ? "LIVE" : "DEMO"}
    </span>
  );
}

export function LicencePill({ state }: { state?: string }) {
  const label: Record<string, string> = {
    active: "Licensed", expired: "Licence expired",
    revoked: "Licence withdrawn", none: "No licence",
  };
  return (
    <span className={state === "active" ? "pill pill-ok" : "pill pill-warn"}>
      {label[state ?? "none"] ?? "No licence"}
    </span>
  );
}

export function ErrorNotice({ error, onRetry }: { error: ApiError; onRetry?: () => void }) {
  return (
    <div className="notice notice-error" role="alert">
      <div className="notice-head">
        <strong>{error.code}</strong>
        {error.status ? <span className="muted"> · HTTP {error.status}</span> : null}
      </div>
      {/* The backend's own words. Not a friendlier sentence we invented: the
          operator needs the real reason, and the client deserves it. */}
      <p>{error.message}</p>
      {error.problems?.length ? (
        <ul className="problems">{error.problems.map((p) => <li key={p}>{p}</li>)}</ul>
      ) : null}
      {onRetry ? <button className="btn btn-ghost" onClick={onRetry}>Try again</button> : null}
    </div>
  );
}

type ReadLike = { connected: boolean; status: ReadState; reason?: string };

/**
 * Renders children ONLY when the backend confirmed status "ok".
 *
 * Every other state gets its own message. "reauth_required" gets the
 * reconnect action, because that is the only thing that fixes it, and
 * "unavailable" shows the backend's reason rather than an empty table that
 * would read as "nothing here".
 */
export function ReadPanel({
  read, children, emptyLabel, onReconnect,
}: {
  read: ReadLike;
  children: React.ReactNode;
  emptyLabel?: string;
  onReconnect?: () => void;
}) {
  if (read.status === "ok") return <>{children}</>;
  if (read.status === "not_connected") {
    return (
      <div className="notice">
        <p>No cTrader account is connected.</p>
        <a className="btn" href="/connect">Connect cTrader</a>
      </div>
    );
  }
  if (read.status === "reauth_required") {
    return (
      <div className="notice notice-warn" role="alert">
        <p>{read.reason ?? "Your cTrader authorisation has expired."}</p>
        <a className="btn" href="/connect" onClick={onReconnect}>Reconnect cTrader</a>
      </div>
    );
  }
  return (
    <div className="notice notice-error" role="alert">
      <p>Could not read your account.</p>
      <p className="muted">{read.reason ?? "The broker did not answer."}</p>
      <p className="muted">{emptyLabel ? "" : ""}</p>
    </div>
  );
}

export function Empty({ label }: { label: string }) {
  return <p className="empty">{label}</p>;
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return <p className="muted" role="status">{label}…</p>;
}
