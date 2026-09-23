"use client";
/**
 * The pieces that render backend state honestly.
 *
 * Each of these exists because the obvious JSX gets it wrong. `{positions.map(...)}`
 * over an undefined list renders nothing, which looks exactly like an account
 * with no positions — so `ReadPanel` refuses to render children at all unless
 * the backend said status "ok", and shows the real reason otherwise.
 *
 * The redesign changed how these look, not what they claim. A refusal still
 * carries the backend's own code and words.
 */
import { CircleAlert, Plug, RefreshCw, TriangleAlert } from "lucide-react";
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
        <CircleAlert className="ico" aria-hidden
                     style={{ width: 12, height: 12, verticalAlign: "-2px", marginRight: 4 }} />
        <strong>{error.code}</strong>
        {error.status ? <span className="muted"> · HTTP {error.status}</span> : null}
      </div>
      {/* The backend's own words. Not a friendlier sentence we invented: the
          operator needs the real reason, and the client deserves it. */}
      <p>{error.message}</p>
      {error.problems?.length ? (
        <ul className="problems">{error.problems.map((p) => <li key={p}>{p}</li>)}</ul>
      ) : null}
      {onRetry ? (
        <button className="btn btn-ghost btn-sm" onClick={onRetry} style={{ marginTop: ".6rem" }}>
          <RefreshCw className="ico" aria-hidden /> Try again
        </button>
      ) : null}
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
        <p className="muted" style={{ display: "flex", alignItems: "center", gap: ".45rem" }}>
          <Plug className="ico" aria-hidden style={{ width: 14, height: 14 }} />
          No cTrader account is connected.
        </p>
        <a className="btn btn-sm" href="/connect">Connect cTrader</a>
      </div>
    );
  }
  if (read.status === "reauth_required") {
    return (
      <div className="notice notice-warn" role="alert">
        <p style={{ display: "flex", alignItems: "center", gap: ".45rem" }}>
          <TriangleAlert className="ico" aria-hidden style={{ width: 14, height: 14 }} />
          {read.reason ?? "Your cTrader authorisation has expired."}
        </p>
        <a className="btn btn-sm" href="/connect" onClick={onReconnect}>Reconnect cTrader</a>
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
  return <p className="muted" role="status" style={{ padding: ".75rem 0", fontSize: ".85rem" }}>{label}…</p>;
}

/** A placeholder with no content, for a value that has not arrived yet. */
export function Skeleton({ w = "100%", h = "1em" }: { w?: number | string; h?: number | string }) {
  return <span className="skel" style={{ display: "inline-block", width: w, height: h }} aria-hidden />;
}

/**
 * A single headline number.
 *
 * `tone` carries trading meaning only. A stat is never tinted for emphasis,
 * because a green number in this product means long, not "good".
 */
export function Stat({
  label, value, foot, tone, icon: Icon, href, small,
}: {
  label: string;
  value: React.ReactNode;
  foot?: React.ReactNode;
  tone?: "accent" | "long" | "short";
  icon?: React.ComponentType<{ className?: string }>;
  href?: string;
  small?: boolean;
}) {
  const inner = (
    <>
      <div className="stat-top">
        <span className="label-xs">{label}</span>
        {Icon ? <Icon className="ico" aria-hidden /> : null}
      </div>
      <div className={small ? "stat-value stat-value-sm" : "stat-value"}>{value}</div>
      {foot ? <div className="stat-foot">{foot}</div> : null}
    </>
  );
  if (href) {
    return (
      <a className="stat" data-tone={tone} href={href} style={{ color: "inherit" }}>
        {inner}
      </a>
    );
  }
  return <div className="stat" data-tone={tone}>{inner}</div>;
}
