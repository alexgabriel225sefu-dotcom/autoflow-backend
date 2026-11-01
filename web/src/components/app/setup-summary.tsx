import type { TradeChoice } from "@/app/(app)/trade/trade-model";
import styles from "./setup-summary.module.css";

/**
 * Shine Border Stats Card by shadcnspace (21st.dev), written natively: a grid
 * of tiles inside a conic shining border. It only presents facts the Trade
 * page already holds; it decides nothing and gates nothing. The Start control
 * is passed in as children and keeps all of its own logic.
 */

export type SummaryTile = { key: string; label: string; value: string };

const DASH = "—";
const pct = (v: string) => (v.trim() === "" ? DASH : `${v.trim()}%`);

export function summaryTiles(
  c: TradeChoice, opts: { accountId?: string | number | null },
): SummaryTile[] {
  const strategy = c.strategy?.label
    ?? (c.custom ? `${c.custom.name} (my method)` : DASH);
  return [
    { key: "instrument", label: "Instrument", value: c.symbol || DASH },
    { key: "timeframe", label: "Timeframe", value: c.timeframe || DASH },
    { key: "strategy", label: "Strategy", value: strategy },
    { key: "risk", label: "Risk per trade", value: pct(c.riskPercent) },
    { key: "dayStop", label: "Stop the day at", value: pct(c.dailyLossPercent) },
    { key: "account", label: "Account",
      value: opts.accountId != null && opts.accountId !== "" ? `#${opts.accountId}` : DASH },
    { key: "mode", label: "Mode",
      value: c.account === "live" ? "Live" : c.account === "demo" ? "Demo" : DASH },
  ];
}

export function SetupSummary({ choice, accountId, children }: {
  choice: TradeChoice;
  accountId?: string | number | null;
  children?: React.ReactNode;
}) {
  const tiles = summaryTiles(choice, { accountId });
  return (
    <section className={styles.card} aria-label="Automation summary">
      <span className={styles.shine} aria-hidden="true" />
      <dl className={styles.grid}>
        {tiles.map((t) => (
          <div key={t.key} className={styles.tile}>
            <dt>{t.label}</dt>
            <dd>{t.value}</dd>
          </div>
        ))}
      </dl>
      {children ? <div className={styles.action}>{children}</div> : null}
    </section>
  );
}
