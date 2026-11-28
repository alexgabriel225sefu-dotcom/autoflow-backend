import styles from "./product.module.css";

/**
 * A real screenshot of the product in a browser frame. Nothing here is drawn:
 * the images are captures of the live app on a demo account. The size of the
 * crop is the only thing this component decides.
 */
export function ProductWindow({
  src, alt, ratio, priority = false,
}: {
  src: string; alt: string; ratio?: string; priority?: boolean;
}) {
  return (
    <div className={styles.win}>
      <div className={styles.bar} aria-hidden="true">
        <span className={styles.dot} /><span className={styles.dot} /><span className={styles.dot} />
        <span className={styles.url}>apex4traders.com</span>
      </div>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        className={styles.crop}
        style={ratio ? ({ ["--ratio" as string]: ratio } as React.CSSProperties) : undefined}
        src={src}
        alt={alt}
        width={1800}
        height={1125}
        loading={priority ? "eager" : "lazy"}
        decoding="async"
      />
    </div>
  );
}
