"use client";

import { useRef } from "react";
import { motion, useReducedMotion, useScroll, useTransform, type MotionValue } from "framer-motion";
import { ArrowRight } from "lucide-react";
import { BrandMark } from "@/components/brand/logo";
import styles from "./perspective-tunnel-hero.module.css";

type TunnelCardData = {
  name: string;
  logo: string;
  alt: string;
  status: string;
  statusTone: "available" | "soon";
  start: number;
  finalX: string;
};

const cards: TunnelCardData[] = [
  {
    name: "cTrader",
    logo: "/ctrader-logo-light.svg",
    alt: "cTrader",
    status: "Primary integration",
    statusTone: "available",
    start: 0.08,
    finalX: "-108%",
  },
  {
    name: "MetaTrader 4",
    logo: "/metatrader-4-light.png",
    alt: "MetaTrader 4",
    status: "On the roadmap",
    statusTone: "soon",
    start: 0.28,
    finalX: "0%",
  },
  {
    name: "MetaTrader 5",
    logo: "/metatrader-5-light.png",
    alt: "MetaTrader 5",
    status: "On the roadmap",
    statusTone: "soon",
    start: 0.48,
    finalX: "108%",
  },
];

function TunnelCard({
  card,
  progress,
  reduced,
}: {
  card: TunnelCardData;
  progress: MotionValue<number>;
  reduced: boolean;
}) {
  const end = Math.min(card.start + 0.28, 0.92);
  const opacity = useTransform(
    progress,
    [Math.max(0, card.start - 0.07), card.start, end],
    [0, 0.95, 1],
  );
  const scale = useTransform(progress, [card.start - 0.04, end], [0.32, 1]);
  const z = useTransform(progress, [card.start - 0.04, end], [-1500, 12]);
  const x = useTransform(progress, [card.start - 0.04, end], ["0%", card.finalX]);
  const y = useTransform(progress, [card.start - 0.04, end], ["2rem", "0rem"]);
  const rotateY = useTransform(progress, [card.start - 0.04, end], [-16, 0]);

  return (
    <motion.article
      className={`${styles.card} ${styles[card.statusTone]}`}
      style={reduced ? undefined : { opacity, scale, z, x, y, rotateY }}
      aria-label={`${card.name}: ${card.status}`}
    >
      <div className={styles.cardTopline}>
        <span className={styles.cardIndex}>0{cards.indexOf(card) + 1}</span>
        <span className={styles.cardStatus}>{card.status}</span>
      </div>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img className={styles.logo} src={card.logo} alt={card.alt} />
      <span className={styles.cardName}>{card.name}</span>
    </motion.article>
  );
}

export function PerspectiveTunnelHero() {
  const sectionRef = useRef<HTMLElement | null>(null);
  const reducedMotion = useReducedMotion() ?? false;
  const { scrollYProgress } = useScroll({
    target: sectionRef,
    offset: ["start start", "end end"],
  });
  const markOpacity = useTransform(scrollYProgress, [0, 0.32, 0.72, 1], [1, 1, 0.4, 0.18]);
  const markScale = useTransform(scrollYProgress, [0, 0.72], [1, 0.8]);

  return (
    <section ref={sectionRef} className={styles.section} id="product">
      <div className={styles.sticky}>
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
          <motion.div
            className={styles.mark}
            style={reducedMotion ? undefined : { opacity: markOpacity, scale: markScale }}
          >
            <BrandMark size={74} title="Apex4Traders" />
            <span>Apex4Traders</span>
            <small>One control panel for your trading rules</small>
          </motion.div>
          <div className={styles.tunnel}>
            {cards.map((card) => (
              <TunnelCard
                key={card.name}
                card={card}
                progress={scrollYProgress}
                reduced={reducedMotion}
              />
            ))}
          </div>
          <p className={styles.scrollHint}>Scroll to explore platform connections</p>
        </div>
      </div>
    </section>
  );
}
