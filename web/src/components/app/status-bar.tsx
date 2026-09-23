"use client";
/**
 * The persistent status strip.
 *
 * On every screen it answers the three questions an operator actually has:
 * which account is selected, whether it is demo or live, and whether anything
 * is running. Those used to live only on the dashboard, which meant that from
 * the journal or the rule page you could not tell whether automation was on.
 *
 * Every chip here is either a fact the API confirmed or an explicit "not
 * connected". Nothing is optimistic, and nothing is filled in while a request
 * is still out — an unknown state renders as unknown.
 */
import { Activity, Plug, ShieldCheck } from "lucide-react";
import type { AutomationState, CtraderStatus, Me } from "@/lib/api";
import type { ApiResult } from "@/lib/api";

type Tone = "long" | "short" | "accent" | "neutral";

function Chip({
  tone, live, label, value, href,
}: {
  tone?: Tone; live?: boolean; label: string; value: React.ReactNode; href?: string;
}) {
  const body = (
    <>
      <span className="dot" data-tone={tone ?? "neutral"} data-live={live ? "true" : undefined} />
      <span>{label}</span>
      <strong>{value}</strong>
    </>
  );
  return href
    ? <a className="stat-chip" href={href}>{body}</a>
    : <span className="stat-chip">{body}</span>;
}

export function StatusBar({
  me, ct, auto,
}: {
  me: ApiResult<Me> | null;
  ct: ApiResult<CtraderStatus> | null;
  auto: ApiResult<AutomationState> | null;
}) {
  const account = ct?.ok ? ct.data : null;
  const selected = account?.selected ?? null;
  const running = auto?.ok ? auto.data : null;
  const licence = me?.ok ? me.data.licence.state : null;

  return (
    <div className="statusbar" role="status" aria-label="Platform status">
      {/* Account. "Not connected" is a fact from the API, never a placeholder
          shown while we wait. */}
      {account === null ? (
        <Chip label="Account" value={<span className="skel" style={{ width: 52, display: "inline-block" }} />} />
      ) : !account.connected ? (
        <a className="stat-chip" href="/connect">
          <Plug className="ico" style={{ width: 12, height: 12 }} aria-hidden />
          <span>Account</span><strong>Not connected</strong>
        </a>
      ) : selected ? (
        <Chip
          href="/accounts"
          tone={selected.mode === "live" ? "short" : "long"}
          live={selected.mode === "live"}
          label={selected.mode === "live" ? "LIVE" : "DEMO"}
          value={<span className="mono">#{selected.ctid}</span>}
        />
      ) : (
        <Chip href="/accounts" label="Account" value="No account selected" />
      )}

      {/* Automation. The single most consequential thing on the screen. */}
      {running === null ? (
        <Chip label="Automation" value={<span className="skel" style={{ width: 44, display: "inline-block" }} />} />
      ) : (
        <Chip
          href={running.ruleDocId ? `/rules/${running.ruleDocId}` : "/rules"}
          tone={running.state === "running" ? "accent" : "neutral"}
          live={running.state === "running"}
          label="Automation"
          value={running.state.toUpperCase()}
        />
      )}

      {licence && licence !== "active" ? (
        <a className="stat-chip" href="/license" style={{ color: "var(--a4t-short)" }}>
          <ShieldCheck className="ico" style={{ width: 12, height: 12 }} aria-hidden />
          <span>Licence</span><strong style={{ color: "inherit" }}>{licence}</strong>
        </a>
      ) : null}

      {/* The broker link itself, separate from which account is selected:
          "connected but nothing selected" and "not connected" need
          different actions from the reader. */}
      {account?.connected ? (
        <a className="stat-chip" href="/accounts">
          <span className="dot" data-tone="long" />
          <span>cTrader</span><strong>Linked</strong>
        </a>
      ) : null}

      <span style={{ flex: 1 }} />

      {/* Stated on every screen, not only in a footer: this release does not
          trade live, and that is a property of the product, not a setting. */}
      <span className="stat-chip" title="Live trading is not enabled in this release">
        <Activity className="ico" style={{ width: 12, height: 12 }} aria-hidden />
        <span>Demo&nbsp;only</span>
      </span>
    </div>
  );
}
