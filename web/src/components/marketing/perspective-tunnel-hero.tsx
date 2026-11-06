import { ArrowRight } from "lucide-react";
import { StackedBrandLockup } from "@/components/brand/logo";
import styles from "./perspective-tunnel-hero.module.css";

type PlatformCard = {
  name: string;
  logo: string;
  alt: string;
  status: string;
  statusTone: "available" | "soon";
};

const cards: PlatformCard[] = [
  { name: "cTrader", logo: "/ctrader-logo-light.svg", alt: "cTrader", status: "Available now", statusTone: "available" },
  { name: "MetaTrader 4", logo: "/metatrader-4-light.png", alt: "MetaTrader 4", status: "Coming soon", statusTone: "soon" },
  { name: "MetaTrader 5", logo: "/metatrader-5-light.png", alt: "MetaTrader 5", status: "Coming soon", statusTone: "soon" },
];

function PlatformCard({ card, index }: { card: PlatformCard; index: number }) {
  return (
    <article className={`${styles.card} ${styles[card.statusTone]}`} aria-label={`${card.name}: ${card.status}`}>
      <div className={styles.cardTopline}>
        <span className={styles.cardIndex}>0{index + 1}</span>
        <span className={styles.cardStatus}>{card.status}</span>
      </div>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img className={styles.logo} src={card.logo} alt={card.alt} />
      <span className={styles.cardName}>{card.name}</span>
    </article>
  );
}

export function PerspectiveTunnelHero() {
  return (
    <section className={styles.section} id="product">
      <div className={styles.layout}>
        <div className={styles.copy}>
          <p className="mkt-kicker">YOUR RULES, YOUR BROKER</p>
          <h1>Trade like you planned&nbsp;to.</h1>
          <p className="mkt-lede">
            Connect your cTrader account, then set your market, method and risk.
            Automation follows your rules and stops when you say.
          </p>
          <div className="mkt-hero-cta">
            <a className="mkt-btn mkt-btn-lg" href="/signup">
              Get started <ArrowRight className="mkt-ico" aria-hidden />
            </a>
            <a className="mkt-btn mkt-btn-outline mkt-btn-lg" href="#features">
              See how it works
            </a>
          </div>
        </div>

        <div className={styles.stage} aria-label="Supported trading platforms">
          <div className={styles.grid} aria-hidden="true" />
          <div className={styles.mark}>
            <StackedBrandLockup className={styles.markLogo} width={300} />
            <small>One control panel for your trading rules</small>
          </div>
          <div className={styles.platforms}>
            {cards.map((card, index) => (
              <PlatformCard key={card.name} card={card} index={index} />
            ))}
          </div>
          <p className={styles.scrollHint}>Platform connections</p>
        </div>
      </div>
    </section>
  );
}
