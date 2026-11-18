"use client";

import { useCallback, useEffect, useLayoutEffect, useState } from "react";
import { BrandLockup } from "@/components/brand/logo";
import styles from "./intro-film.module.css";

/**
 * The first seven seconds of the public page.
 *
 * One idea, and it is the product's: a rule you can read, then a limit that
 * holds. A rule types itself in monospace, a stop line is drawn, and the price
 * path comes down onto it and stops. No money, no candles flying, no result.
 * The rule is labelled as an example and the whole thing is silent.
 *
 * It must never trap a visitor:
 *  - it is pure CSS timing, so with scripting off it still ends by itself and
 *    hides (`animation-fill-mode: forwards`, `visibility: hidden`);
 *  - it plays once per browser session (`sessionStorage`), and `?intro=0`
 *    skips it for a screenshot or a shared link;
 *  - `prefers-reduced-motion` removes it entirely;
 *  - Skip is a real button, and so is Escape.
 */

const KEY = "a4t-intro-seen";
// Matches the CSS timeline plus the closing fade. After this the overlay is
// removed from the tree so it cannot sit above anything.
const TOTAL_MS = 7600;

type Phase = "pending" | "playing" | "gone";

function shouldSkip(): boolean {
  try {
    if (typeof window === "undefined") return true;
    if (new URLSearchParams(window.location.search).get("intro") === "0") return true;
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return true;
    return window.sessionStorage.getItem(KEY) === "1";
  } catch {
    // Storage blocked: play it, once per page load. Better than hiding it
    // from a visitor whose browser refuses storage.
    return false;
  }
}

function remember() {
  try {
    window.sessionStorage.setItem(KEY, "1");
  } catch {
    /* a blocked store only means it may play again on the next visit */
  }
}

// useLayoutEffect warns during server rendering; the overlay is rendered by the
// server on purpose (so there is no flash of the page under it) and decided here.
const useIsoLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;

export function IntroFilm() {
  const [phase, setPhase] = useState<Phase>("pending");

  useIsoLayoutEffect(() => {
    setPhase(shouldSkip() ? "gone" : "playing");
  }, []);

  const finish = useCallback(() => {
    remember();
    setPhase("gone");
  }, []);

  useEffect(() => {
    if (phase !== "playing") return;
    const root = document.documentElement;
    root.classList.add("a4t-intro-lock");
    const timer = window.setTimeout(finish, TOTAL_MS);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") finish();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      root.classList.remove("a4t-intro-lock");
      window.clearTimeout(timer);
      window.removeEventListener("keydown", onKey);
    };
  }, [phase, finish]);

  if (phase === "gone") return null;

  return (
    <div className={styles.film} data-phase={phase} data-testid="intro-film">
      <button type="button" className={styles.skip} onClick={finish}>
        Skip intro
      </button>

      <div className={styles.stage} aria-hidden="true">
        <p className={styles.eyebrow}>Example rule · demo only</p>

        <div className={styles.code}>
          <span className={`${styles.line} ${styles.l1}`}>when EURUSD closes above its range</span>
          <span className={`${styles.line} ${styles.l2}`}>risk 0.5% per trade</span>
          <span className={`${styles.line} ${styles.l3}`}>stop 20 pips</span>
        </div>

        <svg className={styles.chart} viewBox="0 0 600 200" fill="none" preserveAspectRatio="none">
          <line className={styles.stopLine} x1="40" y1="160" x2="600" y2="160" />
          <polyline
            className={styles.path}
            points="0,118 70,104 140,124 200,96 250,92 330,66 390,84 450,128 520,160"
          />
          <circle className={styles.entry} cx="250" cy="92" r="4" />
          <circle className={styles.hit} cx="520" cy="160" r="5" />
          <text className={styles.stopLabel} x="44" y="150">stop</text>
        </svg>

        <div className={styles.brand}>
          <BrandLockup size={34} />
          <p className={styles.tagline}>Rules you can read.</p>
        </div>
      </div>

      <p className="sr-only">Apex4Traders, rules you can read. Skip the introduction with the Skip button or the Escape key.</p>
    </div>
  );
}
