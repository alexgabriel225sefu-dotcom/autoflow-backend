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

type Props = {
  accounts: CtAccount[] | null;
  selected: { ctid: number | string; mode: "demo" | "live" } | null;
  execution: Execution | null;
  running: AutomationState | null;
};

export function AccountsDuo({ accounts, selected, execution, running }: Props) {
  const demo = accounts?.find((a) => a.mode === "demo") ?? null;
  const live = accounts?.find((a) => a.mode === "live") ?? null;
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
        <p>Free for 14 days. Test a rule with no real money.</p>
        <Link href={demo ? "/trade" : "/accounts"}>{demo ? "Automate on demo" : "Choose a demo account"}</Link>
      </article>

      <article className="duo-card" data-active={liveActive ? "true" : undefined} data-kind="live">
        {liveActive ? <BorderBeam size={160} duration={9} colorFrom="#ff9484" colorTo="#ffd2a8" /> : null}
        <header><Radio size={16} aria-hidden /> <span>Live account</span>
          <em data-tone={liveActive ? "on" : cleared ? "ready" : "idle"}>
            {liveActive ? "Automating" : cleared ? "Cleared" : "Not enabled yet"}
          </em>
        </header>
        <strong>{live ? `#${live.ctid}` : "Real money, same rules"}</strong>
        <p>{cleared ? notice.lead : "Real-money accounts are a paid plan. Open the live page to see what is needed."}</p>
        <Link href="/live">{cleared ? "Open live" : "See what live needs"}</Link>
      </article>
    </section>
  );
}
