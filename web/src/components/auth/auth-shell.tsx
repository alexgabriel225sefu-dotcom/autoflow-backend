import Link from "next/link";
import type { ReactNode } from "react";
import { BrandLockup } from "@/components/brand/logo";
import styles from "./auth-shell.module.css";

/**
 * The frame of every sign-in screen: one centred column with the logo above
 * it, after "Modern Animated Sign In" by arunachalam (21st.dev). There is no
 * side panel and no brand banner; the form is the whole page.
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
    </main>
  );
}
