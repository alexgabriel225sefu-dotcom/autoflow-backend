import { ProductWindow } from "./product-window";
import styles from "./product.module.css";

/**
 * The product under the hero: the live journal on a laptop-sized window and the
 * dashboard on a phone, both real captures from a demo account.
 */
export function HeroProduct() {
  return (
    <div className={styles.stage} role="img" aria-label="Apex4Traders on a laptop and on a phone: automation running on a demo account, with the journal of every decision">
      <ProductWindow
        src="/product/journal.webp"
        alt=""
        ratio="16 / 8.6"
        priority
      />
      <div className={styles.phone} aria-hidden="true">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/product/m-dash.webp" alt="" width={560} height={1213} loading="eager" decoding="async" />
      </div>
      <div className={styles.fade} aria-hidden="true" />
    </div>
  );
}
