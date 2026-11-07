import { ProductWindow } from "./product-window";
import styles from "./guide.module.css";

export type Hotspot = {
  /** Position and size as percentages of the screenshot. */
  x: number; y: number; w: number; h: number;
  label: string;
  /** Where the label sits relative to the highlighted area. */
  side?: "top" | "bottom";
};

/**
 * A real screenshot with parts of it lit up one after another, each with a
 * plain label. The highlights are drawn over the capture; the capture itself is
 * not edited.
 */
export function AnnotatedShot({
  src, alt, ratio, spots,
}: { src: string; alt: string; ratio: string; spots: Hotspot[] }) {
  return (
    <div className={styles.shot} style={{ ["--n" as string]: spots.length } as React.CSSProperties}>
      <ProductWindow src={src} alt={alt} ratio={ratio} />
      <div className={styles.layer} style={{ ["--ratio" as string]: ratio } as React.CSSProperties} aria-hidden="true">
        {spots.map((s, i) => (
          <div
            key={s.label}
            className={styles.spot}
            style={{ left: `${s.x}%`, top: `${s.y}%`, width: `${s.w}%`, height: `${s.h}%`, ["--i" as string]: i } as React.CSSProperties}
          >
            <span className={`${styles.tag} ${s.side === "top" ? styles.top : ""}`}>
              <b>{i + 1}</b>{s.label}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
