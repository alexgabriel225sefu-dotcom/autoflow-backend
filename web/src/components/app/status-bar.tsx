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

function Emoji({ children }: { children: string }) {
  return <span className="status-emoji" aria-hidden="true">{children}</span>;
}

function Chip({
  tone, live, label, value, href, title, emoji,
}: {
  tone?: Tone; live?: boolean; label: string; value: React.ReactNode;
  href?: string; title?: string; emoji?: string;
}) {
  const body = (
    <>
      <span className="dot" data-tone={tone ?? "neutral"} data-live={live ? "true" : undefined} />
      {emoji ? <Emoji>{emoji}</Emoji> : null}
      <span>{label}</span>
      <strong>{value}</strong>
    </>
  );
  return href
    ? <a className="stat-chip" data-tone={tone ?? "neutral"} href={href} title={title}>{body}</a>
    : <span className="stat-chip" data-tone={tone ?? "neutral"} title={title}>{body}</span>;
}

/* A read that failed is not a read still in flight.
 *
 * Both used to arrive here as a null payload and both rendered the loading
 * shimmer, so a 503 from the API read on screen as "still loading", for ever.
 * That is the same mistake as rendering it as "not connected", just quieter:
 * the strip claims a state it does not have. An unknown state now says so. */
function Unknown({ label, title }: { label: string; title: string }) {
  return <Chip label={label} value="Unknown" title={title} emoji="❔" />;
}

export function StatusBar({
  me, ct, auto,
}: {
  me: ApiResult<Me> | null;
  ct: ApiResult<CtraderStatus> | null;
  auto: ApiResult<AutomationState> | null;
}) {
  const account = ct?.ok ? ct.data : null;
  // A result that arrived and said no is a third state, distinct from both
  // "we have an answer" and "we are still asking".
  const ctFailed = ct != null && !ct.ok;
  const autoFailed = auto != null && !auto.ok;
  const selected = account?.selected ?? null;
  const running = auto?.ok ? auto.data : null;
  // A guard with no report, while the loop is idling through the weekend close
  // window. Said as such; any other silence keeps the plain "No report yet".
  const idleForWeekend = running?.riskGuard?.state === "unknown"
    && running.marketClosed === true;
  // The loop is up, and the weekend window says it is idle. PR 66 already
  // refuses to call a dead loop "running". Calling an idle weekend loop
  // RUNNING contradicts the Risk Guard chip on the same strip.
  const marketIdle = running?.state === "running" && running.marketClosed === true;
  const licence = me?.ok ? me.data.licence.state : null;

  return (
    <div className="statusbar" role="status" aria-label="Platform status">
      {/* Account. "Not connected" is a fact from the API, never a placeholder
          shown while we wait. */}
      {account === null ? (
        ctFailed ? (
          <Unknown label="Account"
                   title="The platform could not read your broker link just now — this is not a statement that nothing is connected" />
        ) : (
          <Chip emoji="⏳" label="Account" value={<span className="skel" style={{ width: 52, display: "inline-block" }} />} />
        )
      ) : !account.connected ? (
        <a className="stat-chip" href="/connect">
          <Emoji>🔌</Emoji>
          <Plug className="ico" style={{ width: 12, height: 12 }} aria-hidden />
          <span>Account</span><strong>Not connected</strong>
        </a>
      ) : selected ? (
        <Chip
          href="/accounts"
          tone={selected.mode === "live" ? "short" : "long"}
          live={selected.mode === "live"}
          emoji={selected.mode === "live" ? "🔴" : "🧪"}
          label={selected.mode === "live" ? "LIVE" : "DEMO"}
          value={<span className="mono">#{selected.ctid}</span>}
        />
      ) : (
        <Chip href="/accounts" emoji="🔘" label="Account" value="No account selected" />
      )}

      {/* Automation. The single most consequential thing on the screen. */}
      {running === null ? (
        autoFailed ? (
          <Unknown label="Automation"
                   title="The platform could not read whether automation is running — do not read this as stopped" />
        ) : (
          <Chip emoji="⏳" label="Automation" value={<span className="skel" style={{ width: 44, display: "inline-block" }} />} />
        )
      ) : (
        <Chip
          href={running.ruleDocId ? `/rules/${running.ruleDocId}` : "/rules"}
          tone={marketIdle ? "neutral" : running.state === "running" ? "accent" : "neutral"}
          live={running.state === "running" && !marketIdle}
          emoji={marketIdle ? "🌙"
            : running.state === "running" ? "🟢⚙️"
            : running.state === "blocked" ? "⛔"
            : running.state === "paused" ? "⏯️"
            : "⏸️"}
          label="Automation"
          value={marketIdle ? "MARKET CLOSED"
            : running.state === "blocked" ? "BLOCKED"
            : running.state.toUpperCase()}
          title={marketIdle
            ? (running.marketMessage ?? "The market is closed, so the loop is idle.")
            : running.blockReason ?? running.levelBlurb ?? undefined}
        />
      )}
      {running?.marketMessage ? (
        <span className="stat-chip" title={running.marketMessage}>
          <Emoji>🌙</Emoji>
          <span>{running.marketMessage}</span>
        </span>
      ) : null}

      {/* WHAT "RUNNING" MEANS. The three engine levels differ by whether a
          setup becomes an order, and this strip showed the same RUNNING for
          all of them — so a client at Signals Only, whose loop places nothing
          by design, read the most consequential chip on the screen as "it is
          trading for me".

          Only shown for a level that does NOT execute, because that is the
          case where the state alone misleads. `levelExecutes` is the server's
          answer, not a list of level names kept here: which levels place
          orders is decided by the engine and must be read from it. */}
      {running?.state === "running" && running.levelExecutes === false ? (
        <Chip label="Level" value={running.levelLabel ?? running.level ?? "Unknown"}
              title={running.levelBlurb
                ?? "This level does not place orders — it reports setups and leaves the trade to you."} />
      ) : null}

      {/* THE RISK GUARD, as the loop last reported it. Shown only while a loop
          exists to have reported: a stopped account has no report, and a chip
          saying "no report" there would be noise rather than information.
          "unknown" is its own wording and is never drawn as "active" — a guard
          that has not spoken has not said yes. */}
      {running && running.state !== "stopped" && running.riskGuard ? (
        <Chip
          label="Risk Guard"
          tone={running.riskGuard.state === "holding" ? "short"
            : running.riskGuard.state === "ok" ? "long" : "neutral"}
          emoji={running.riskGuard.state === "holding" ? "🛑"
            : running.riskGuard.state === "ok" ? "🛡️"
            : idleForWeekend ? "🌙" : "⏳"}
          value={running.riskGuard.state === "holding" ? "HOLDING"
            : running.riskGuard.state === "ok" ? "Active"
              : idleForWeekend ? "Market closed" : "No report yet"}
          title={running.riskGuard.state === "holding"
            ? (running.riskGuard.reasons.join("; ") || "A risk limit was hit.")
            : running.riskGuard.state === "unknown"
              ? (idleForWeekend
                ? "The market is closed for the weekend, so the loop is idle and has not reported. It reports again after the market reopens. This is not a statement that the guard is fine."
                : "The guard has not reported yet. This is not a statement that it is fine.")
              : undefined}
        />
      ) : null}

      {licence && licence !== "active" ? (
        <a className="stat-chip" href="/license" style={{ color: "var(--a4t-short)" }}>
          <Emoji>⚠️</Emoji>
          <ShieldCheck className="ico" style={{ width: 12, height: 12 }} aria-hidden />
          <span>Licence</span><strong style={{ color: "inherit" }}>{licence}</strong>
        </a>
      ) : null}

      {/* The broker link itself, separate from which account is selected:
          "connected but nothing selected" and "not connected" need
          different actions from the reader. */}
      {account?.connected ? (
        <a className="stat-chip" data-tone="long" href="/accounts">
          <span className="dot" data-tone="long" data-live="true" />
          <Emoji>🔗</Emoji>
          <span>cTrader</span><strong>Linked</strong>
        </a>
      ) : null}

      <span style={{ flex: 1 }} />

      {/* Stated on every screen, not only in a footer: this release does not
          trade live, and that is a property of the product, not a setting. */}
      <span className="stat-chip" title="Live trading is not enabled in this release">
        <Emoji>🧪</Emoji>
        <Activity className="ico" style={{ width: 12, height: 12 }} aria-hidden />
        <span>Demo&nbsp;only</span>
      </span>
    </div>
  );
}
