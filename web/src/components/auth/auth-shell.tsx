import Link from "next/link";
import type { ReactNode } from "react";
import { BrandLockup } from "@/components/brand/logo";

/**
 * The frame of every sign-in screen: the form on the calm surface, the product
 * on a dark one beside it. The right-hand panel is decoration and says nothing
 * a screen reader needs, so it is hidden from them; everything a person has to
 * read or do is in the left column.
 *
 * The card in the panel is an illustration of the rule check, labelled as one.
 * It carries no balance, no result and no return.
 */
export function AuthShell({
  title, lead, children, footer,
}: { title: string; lead?: string; children: ReactNode; footer?: ReactNode }) {
  return (
    <main className="a4t auth-split">
      <section className="auth-main">
        <Link href="/" className="auth-logo" aria-label="Apex4Traders — home">
          <BrandLockup size={24} />
        </Link>
        <div className="auth-block">
          <h1>{title}</h1>
          {lead ? <p className="auth-lead">{lead}</p> : null}
          {children}
          {footer ? <div className="auth-foot">{footer}</div> : null}
        </div>
        <p className="auth-legal">
          Trading involves risk. No profit is guaranteed. Apex4Traders is not financial advice.
        </p>
      </section>

      <aside className="auth-aside" aria-hidden="true">
        <div className="aside-glow" />
        <div className="aside-copy">
          <p className="aside-kicker">YOUR RULES · YOUR BROKER</p>
          <p className="aside-head">Trade like you planned&nbsp;to.</p>
          <p className="aside-sub">
            Connect your cTrader account. Choose your market, your method and
            your risk. Then let automation follow your rules.
          </p>
        </div>

        <div className="aside-card">
          <div className="ac-bar"><i /><i /><i /><span>Illustrative preview</span></div>
          <div className="ac-title">Rule check</div>
          <div className="ac-row"><b>EMA (21)</b><em>crosses above</em><b>EMA (55)</b><u /></div>
          <div className="ac-row"><b>RSI (14)</b><em>greater than</em><b>50</b><u /></div>
          <div className="ac-row"><b>Stop-loss</b><em>set</em><b>1.0% risk</b><u /></div>
          <div className="ac-foot">
            <span className="ac-ok"><i />Conditions met</span>
            <span className="ac-stop">■ Emergency stop</span>
          </div>
        </div>

        <div className="aside-works">
          <span>WORKS WITH</span>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/ctrader-logo-light.svg" alt="" width={104} height={25} />
        </div>
      </aside>
    </main>
  );
}
