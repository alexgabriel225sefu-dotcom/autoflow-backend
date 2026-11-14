import { ProductWindow } from "./product-window";
import styles from "./product.module.css";

/** Real UI labels that float over the capture. They are copied from the product. */
const badges = [
  { text: "Automation running", cls: "b1" },
  { text: "Risk Guard active", cls: "b2" },
  { text: "Demo account", cls: "b3" },
] as const;

export function HeroProduct() {
  return (
    <div
      className={styles.stage}
      role="img"
      aria-label="Apex4Traders on a laptop and on a phone: automation running on a demo account, with the journal of what it did"
    >
      <div className={styles.float}>
        <ProductWindow src="/product/journal.webp" alt="" ratio="16 / 10" priority />
      </div>
      <div className={styles.phone} aria-hidden="true">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/product/m-dash.webp" alt="" width={560} height={1213} loading="eager" decoding="async" />
      </div>
      {badges.map((b) => (
        <span key={b.text} className={`${styles.badge} ${styles[b.cls]}`} aria-hidden="true">
          <i className={styles.pulse} />{b.text}
        </span>
      ))}
    </div>
  );
}
