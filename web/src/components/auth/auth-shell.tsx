import Link from "next/link";
import type { ReactNode } from "react";
import { BookOpen, PlayCircle, ShieldCheck } from "lucide-react";
import { BrandLockup } from "@/components/brand/logo";
import { BrandStage } from "./brand-stage";
import styles from "./auth-shell.module.css";

/**
 * The frame of every sign-in screen: the form on the left, after "Modern
 * Animated Sign In" by arunachalam (21st.dev), and on wide screens a brand
 * panel on the right with the A4 mark and wordmark, one plain sentence about
 * the product and a real capture of it. The panel makes no claim about
 * results. On a phone only the form shows, with the logo above it.
 */
export function AuthShell({
  title, lead, children, footer,
}: { title: string; lead?: string; children: ReactNode; footer?: ReactNode }) {
  return (
    <main className={`a4t auth-split ${styles.shell}`}>
      {/* Slow-drifting glows behind the form column. Decoration only. */}
      <div className={styles.backdrop} aria-hidden="true">
        <span className={`${styles.glow} ${styles.g1}`} />
        <span className={`${styles.glow} ${styles.g2}`} />
        <span className={`${styles.glow} ${styles.g3}`} />
      </div>
      <section className="auth-main">
        <Link href="/" className="auth-logo" aria-label="Apex4Traders — home">
          <BrandLockup size={24} />
        </Link>
        <div className={`auth-block ${styles.block}`}>
          <h1>{title}</h1>
          {lead ? <p className="auth-lead">{lead}</p> : null}
          {children}
          {footer ? <div className="auth-foot">{footer}</div> : null}
        </div>
        <p className="auth-legal">
          Trading involves risk. No profit is guaranteed. Apex4Traders is not financial advice.
        </p>
      </section>
      <aside className={styles.brand} aria-label="About Apex4Traders">
        <div className={styles.brandGlow} aria-hidden="true" />
        <div className={styles.brandInner}>
          <BrandStage />
          <h2>Trade by rules you can read.</h2>
          <p>
            Write your plan in plain words, test it on a demo account for 14
            days and keep a stop button within reach. You connect your own
            cTrader account.
          </p>
          <ul className={styles.points}>
            <li><ShieldCheck size={18} aria-hidden /> Risk Guard checks your limits before every order</li>
            <li><BookOpen size={18} aria-hidden /> A journal that says why it acted, or why it waited</li>
            <li><PlayCircle size={18} aria-hidden /> Start, pause or stop whenever you like</li>
          </ul>
          <figure className={styles.shot} aria-hidden="true">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/product/dash.webp" alt="" width={1280} height={768} loading="lazy" decoding="async" />
          </figure>
        </div>
      </aside>
    </main>
  );
}
