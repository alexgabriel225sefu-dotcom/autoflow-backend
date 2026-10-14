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
import type { ApiError, Execution, ReadState } from "@/lib/api";
// ONE definition of what a broker read state says. It was written out
// longhand here as well, and the two drifted: this copy claimed "No
// cTrader account is connected" for a status that also means "linked
// but nothing selected".
import { plainRead } from "./plain";

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
    /* "No cTrader account is connected." was false half the time.
       This status means there is nothing to read from, which is true both
       when no account is linked and when one is linked but none has been
       SELECTED — the server says so in `reason`: "no cTrader account is
       connected, or none has been selected". The hardcoded sentence picked
       one of those and the button sent the reader to /connect, so somebody
       who had just linked was told on this screen that he had not, with the
       status strip above it reading "cTrader Linked".
       The server's words now carry which case it is, and /accounts is the
       destination because it is correct for both. */
    const p = plainRead(read.status, read.reason);
    return (
      <div className="notice">
        <p style={{ display: "flex", alignItems: "center", gap: ".45rem", fontWeight: 600 }}>
          <Plug className="ico" aria-hidden style={{ width: 14, height: 14 }} />
          {p?.label}
        </p>
        {p?.detail ? (
          <p className="muted" style={{ fontSize: ".82rem" }}>{p.detail}</p>
        ) : null}
        <a className="btn btn-sm" href="/accounts">Choose an account</a>
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

/**
 * The account-limit refusal, and the only place a referral link is rendered.
 *
 * ONE implementation, used by every screen that can hit the refusal. Written
 * that way deliberately: the link must never appear without the disclosure
 * beside it, and two copies of this markup would be two chances for a later
 * edit to drop it from one of them.
 *
 * It renders only for ACCOUNT_LIMIT — the moment a client has just tried to
 * add another real-money account, which makes them the one client asking.
 * Every other screen and every other client never sees it, which is the
 * difference between answering a question and nudging somebody to open
 * accounts they do not need.
 *
 * The url and the disclosure arrive together from the server, which has no
 * accessor returning the url alone; if the disclosure is somehow missing,
 * this falls back to support rather than showing a bare link.
 */
export function AccountLimitNotice({ error }: { error: ApiError }) {
  if (error.code !== "ACCOUNT_LIMIT") return null;
  // BOTH halves, or neither. The api layer already drops a payload carrying a
  // url without a disclosure, and this is the last line before a client sees
  // one: checking only that the object exists rendered the anchor beside an
  // empty paragraph, which is precisely the bare referral link this component
  // must never produce. Found by its own test.
  const s = error.brokerSignup;
  const signup = s && s.url && s.disclosure.trim() ? s : undefined;
  return (
    <div className="notice" role="status" style={{ display: "grid", gap: ".6rem" }}>
      <strong>{error.message}</strong>
      {signup ? (
        <>
          <p className="muted" style={{ margin: 0, fontSize: ".8rem" }}>
            {signup.disclosure}
          </p>
          <a
            className="btn btn-sm"
            href={signup.url}
            target="_blank"
            rel="noopener noreferrer nofollow sponsored"
            style={{ justifySelf: "start" }}
          >
            Open an account with the referral broker
          </a>
        </>
      ) : (
        <p className="muted" style={{ margin: 0, fontSize: ".8rem" }}>
          Contact support to have an additional real-money account added.
        </p>
      )}
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

/**
 * The server's verdict on what this client may do, rendered as it was given.
 *
 * The badge text and the sentence under it both come from `me.execution`.
 * Nothing here re-derives them from a licence state and an account mode: that
 * combination is a decision, it is made in apex/platform/entitlement.py, and
 * a second implementation of it in the browser is one that can disagree with
 * the server that actually refuses.
 */
export function ExecutionBadge({ execution }: { execution?: Execution | null }) {
  if (!execution) return <span className="pill pill-muted">Checking access</span>;
  const tone =
    execution.badge === "DEMO" ? "pill pill-demo"
      : execution.badge === "LIVE BLOCKED" ? "pill pill-live"
        : "pill pill-muted";
  return (
    <span className={tone} title={execution.message}>
      {execution.badge}
    </span>
  );
}

/**
 * What this release charges for, in one sentence that comes from the server.
 *
 * Holding the wording in the backend is the point: a promise about pricing
 * written in a component is a promise nobody reviewed, and this product has
 * no active checkout to promise.
 */
export function PlanNotice({ execution }: { execution?: Execution | null }) {
  if (!execution?.planNotice) return null;
  return (
    <p className="muted" style={{ fontSize: ".8rem" }}>
      {execution.planNotice}
    </p>
  );
}
