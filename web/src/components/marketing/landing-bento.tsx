import {
  Eye,
  GaugeCircle,
  Link2,
  ListChecks,
  NotebookTabs,
  ShieldCheck,
} from "lucide-react";
import styles from "./landing-bento.module.css";

type BentoItem = {
  eyebrow: string;
  title: string;
  body: string;
  icon: typeof Link2;
  className?: string;
};

const items: BentoItem[] = [
  {
    eyebrow: "Account context",
    title: "See the account before the action",
    body: "Broker, mode and selected account stay visible before a rule can be started.",
    icon: Link2,
    className: styles.account,
  },
  {
    eyebrow: "Rule builder",
    title: "Conditions stay readable",
    body: "Build from named conditions, then read back what the rule will evaluate.",
    icon: ListChecks,
    className: styles.rule,
  },
  {
    eyebrow: "Risk guard",
    title: "Limits have a place in the flow",
    body: "Risk context sits beside the decision, with unknown inputs kept visible.",
    icon: ShieldCheck,
    className: styles.risk,
  },
  {
    eyebrow: "Preview",
    title: "Inspect before anything runs",
    body: "A decision can be reviewed as a preview without creating an order.",
    icon: Eye,
    className: styles.preview,
  },
  {
    eyebrow: "Journal",
    title: "Every decision has a trail",
    body: "The journal records what the rule saw, decided and left unchanged.",
    icon: NotebookTabs,
    className: styles.journal,
  },
  {
    eyebrow: "Controls",
    title: "Start, pause, stop",
    body: "Explicit controls keep the automation state in view.",
    icon: GaugeCircle,
    className: styles.controls,
  },
];

function PreviewPanel() {
  return (
    <div className={styles.previewPanel} aria-label="Product preview">
      <div className={styles.previewBar}>
        <span className={styles.previewDot} />
        <span className={styles.previewDot} />
        <span className={styles.previewDot} />
          <span className={styles.previewTitle}>EURUSD · 1h</span>
      </div>
      <div className={styles.previewBody}>
        <div>
          <span className={styles.previewLabel}>Next step</span>
          <strong>Review on demo</strong>
        </div>
        <div className={styles.previewRows}>
          <span>Price vs moving average</span><b>Ready</b>
          <span>Momentum condition</span><b>Ready</b>
          <span>Risk guard</span><b>Review account</b>
        </div>
      </div>
    </div>
  );
}

function BentoCard({ item }: { item: BentoItem }) {
  const Icon = item.icon;
  return (
    <article className={`${styles.card} ${item.className ?? ""}`}>
      <div className={styles.cardTopline}>
        <span>{item.eyebrow}</span>
        <Icon size={17} aria-hidden />
      </div>
      <h3>{item.title}</h3>
      <p>{item.body}</p>
    </article>
  );
}

export function LandingBento() {
  return (
    <section className="mkt-section" aria-labelledby="control-surface-title">
      <div className={styles.heading}>
        <div>
          <span className="mkt-eyebrow">A clearer workspace</span>
          <h2 id="control-surface-title">See the rule before you run it.</h2>
        </div>
        <p>
          Keep the account, rule and risk settings together so the next step
          is easy to understand.
        </p>
      </div>

      <div className={styles.grid}>
        <article className={`${styles.card} ${styles.feature}`}>
          <div className={styles.cardTopline}>
            <span>Product preview</span>
            <span className={styles.liveMark}>Demo preview</span>
          </div>
          <h3>From market context to a clear next step.</h3>
          <p>
            Review the market context, the conditions and the account settings
            in one calm workspace before you decide what to do next.
          </p>
          <PreviewPanel />
        </article>
        {items.map((item) => <BentoCard item={item} key={item.title} />)}
      </div>
    </section>
  );
}
