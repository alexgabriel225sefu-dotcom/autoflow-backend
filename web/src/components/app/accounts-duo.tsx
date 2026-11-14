"use client";
/**
 * Demo and live, side by side.
 *
 * It exists so a visitor can see that the platform is built for real-money
 * accounts too, without the page ever claiming more than the server does. The
 * live card shows the SERVER's verdict about live access, in the server's own
 * words; the demo card shows what is actually selected and running. Nothing
 * here is a control that moves money: both cards only link to the screens that
 * are.
 */
import Link from "next/link";
import { FlaskConical, Radio } from "lucide-react";
import type { AutomationState, CtAccount, Execution } from "@/lib/api";
import { liveCleared, liveNotice } from "@/components/app/live-access";
import { BorderBeam } from "@/components/ui/border-beam";

export type AccountFigure = {
  ctid: number | string;
  mode: "demo" | "live" | "unknown";
  balance: number | null;
  equity: number | null;
  account: { status: string; reason?: string | null; errorCode?: string | null; correlationId?: string | null };
  positions: { status: string; count: number | null; reason?: string | null; errorCode?: string | null; correlationId?: string | null };
  orders: { status: string; count: number | null; reason?: string | null; errorCode?: string | null; correlationId?: string | null };
};

type Props = {
  accounts: CtAccount[] | null;
  selected: { ctid: number | string; mode: "demo" | "live" } | null;
  execution: Execution | null;
  running: AutomationState | null;
  figures?: AccountFigure[] | null;
  /** The balance read is still on its way. Not the same as an unknown balance. */
  figuresLoading?: boolean;
};

function money(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "unknown";
  return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function count(status: string | undefined, value: number | null | undefined): string {
  if (status !== "ok" || value == null) return "unknown";
  return String(value);
}

function ReadLines({ figure, loading }: { figure: AccountFigure | null; loading: boolean }) {
  // The broker read takes a few seconds. Until it answers the figures are not
  // "unknown": saying so told a client with a healthy account that its balance
  // could not be read.
  if (!figure) return <p>{loading ? "Reading balance and equity…" : "Balance unknown · Equity unknown"}</p>;
  const failed = figure.account.status !== "ok" ? figure.account
    : figure.positions.status !== "ok" ? figure.positions
    : figure.orders.status !== "ok" ? figure.orders : null;
  return (
    <>
      <p>
        Balance {money(figure.balance)} · Equity {money(figure.equity)}
        {" · "}Positions {count(figure.positions.status, figure.positions.count)}
        {" · "}Orders {count(figure.orders.status, figure.orders.count)}
      </p>
      {failed ? (
        <p role="alert">
          {failed.reason || "This read failed."}
          {failed.errorCode ? ` · ${failed.errorCode}` : ""}
          {failed.correlationId ? ` · ref ${failed.correlationId}` : ""}
          {failed.status === "reauth_required" || failed.errorCode === "AUTH_FAILED"
            ? " Reconnect cTrader, then refresh." : " Refresh to try this read again."}
        </p>
      ) : null}
    </>
  );
}

export function AccountsDuo({ accounts, selected, execution, running, figures = null, figuresLoading = false }: Props) {
  const demo = accounts?.find((a) => a.mode === "demo") ?? null;
  const live = accounts?.find((a) => a.mode === "live") ?? null;
  const figureFor = (account: CtAccount | null) =>
    account && figures ? figures.find((f) => String(f.ctid) === String(account.ctid)) ?? null : null;
  const automating = running?.state === "running" || running?.state === "paused";
  const demoActive = automating && selected?.mode === "demo";
  const liveActive = automating && selected?.mode === "live";
  const cleared = liveCleared(execution);
  const notice = liveNotice(execution);

  return (
    <section className="duo" aria-label="Demo and live accounts">
      <article className="duo-card" data-active={demoActive ? "true" : undefined} data-kind="demo">
        {demoActive ? <BorderBeam size={160} duration={9} colorFrom="#3ddc97" colorTo="#ff9484" /> : null}
        <header><FlaskConical size={16} aria-hidden /> <span>Demo account</span>
          <em data-tone={demoActive ? "on" : "idle"}>{demoActive ? "Automating" : demo ? "Ready" : "Not chosen"}</em>
        </header>
        <strong>{demo ? `#${demo.ctid}` : "No demo account yet"}</strong>
        {demo ? <ReadLines figure={figureFor(demo)} loading={figuresLoading} /> : <p>Free for 14 days. Test a rule with no real money.</p>}
        <Link href={demo ? "/trade" : "/accounts"}>{demoActive ? "Manage automation" : demo ? "Start on demo" : "Choose a demo account"}</Link>
      </article>

      <article className="duo-card" data-active={liveActive ? "true" : undefined} data-kind="live">
        {liveActive ? <BorderBeam size={160} duration={9} colorFrom="#ff9484" colorTo="#ffd2a8" /> : null}
        <header><Radio size={16} aria-hidden /> <span>Live account</span>
          <em data-tone={liveActive ? "on" : cleared ? "ready" : "idle"}>
            {liveActive ? "Automating" : cleared ? "Cleared" : "Not enabled yet"}
          </em>
        </header>
        <strong>{live ? `#${live.ctid}` : "Real money, same rules"}</strong>
        {live ? <ReadLines figure={figureFor(live)} loading={figuresLoading} /> : null}
        <p>{cleared ? notice.lead : "Live trading is not enabled. This account is shown so you can read it. No order is sent."}</p>
        <Link href="/live">{cleared ? "Open live" : "Not enabled — see why"}</Link>
      </article>
    </section>
  );
}
