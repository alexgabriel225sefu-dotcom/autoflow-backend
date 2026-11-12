import { AnnotatedShot, type Hotspot } from "./annotated-shot";
import styles from "./guide.module.css";

type Step = {
  id: string; n: string; title: string; body: string; points: string[];
  src: string; alt: string; ratio: string; spots: Hotspot[];
};

// Positions are measured on the captures in /public/product.
const steps: Step[] = [
  {
    id: "choose", n: "1", title: "Choose how you want to trade",
    body: "Pick an instrument and one of fifteen ready-made strategies. Each card tells you in plain words what it does and, just as important, what it will not trade.",
    points: ["No code and no indicators to learn first", "Every strategy lists what it will not do"],
    src: "/product/wizard.webp", alt: "The strategy step: ready-made strategies, each with a 'will not trade' line.", ratio: "16 / 10",
    spots: [
      { x: 21.7, y: 50.7, w: 75.5, h: 39, label: "Ready-made strategies", side: "top" },
      { x: 47.1, y: 50.7, w: 24.1, h: 39, label: "Trend Following selected" },
    ],
  },
  {
    id: "start", n: "2", title: "Start on a demo account",
    body: "Your first 14 days are on a demo account with no real money. Start, pause or stop with one tap, and the stop button is always in reach.",
    points: ["Demo only in this release", "Pause or stop whenever you like"],
    src: "/product/dash.webp", alt: "The dashboard with automation running and the Pause and Stop buttons.", ratio: "16 / 10",
    spots: [
      { x: 19.8, y: 7.5, w: 78.6, h: 5, label: "Account and Risk Guard, always visible", side: "bottom" },
      { x: 39.8, y: 26.4, w: 19.8, h: 17.4, label: "State: Running", side: "bottom" },
      { x: 21.5, y: 88.6, w: 12.7, h: 6, label: "Pause or stop", side: "top" },
    ],
  },
  {
    id: "review", n: "3", title: "See what happened, and when",
    body: "The journal records when automation starts, pauses and stops, and any signal found at the Signals Only level. Orders and closed trades are listed in Positions and Closed trades.",
    points: ["Every start and stop is recorded", "Export it any time"],
    src: "/product/journal.webp", alt: "The journal with a buy decision and its reason.", ratio: "16 / 10",
    spots: [
      { x: 20, y: 40.9, w: 78, h: 22, label: "A decision, with its reason", side: "bottom" },
      { x: 82, y: 19.2, w: 15.8, h: 5.4, label: "Export", side: "bottom" },
    ],
  },
];

export function ProductGuide() {
  return (
    <div className={styles.guide}>
      {steps.map((s, i) => (
        <article key={s.id} className={`${styles.row} ${i % 2 ? styles.flip : ""}`}>
          <div className={styles.text}>
            <span className={styles.num}>{s.n}</span>
            <h3>{s.title}</h3>
            <p>{s.body}</p>
            <ul>{s.points.map((p) => <li key={p}>{p}</li>)}</ul>
          </div>
          <AnnotatedShot src={s.src} alt={s.alt} ratio={s.ratio} spots={s.spots} />
        </article>
      ))}
    </div>
  );
}
