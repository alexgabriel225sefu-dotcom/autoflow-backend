"use client";

import { useEffect, useRef, useState } from "react";
import { delayAfter, frameAt, totalSteps } from "./terminal-sequence";
import styles from "./terminal.module.css";

/**
 * A rule shown as a terminal window that types the rule in and then prints
 * the reply line by line, once, when it scrolls into view.
 *
 * Pattern: "Terminal" by dillionverma (21st.dev / Magic UI), written natively
 * here against the landing tokens.
 *
 * The full text is ALWAYS in the DOM as visually-hidden text, so server
 * render, screen readers and tests read the finished block. The animated copy
 * is aria-hidden and starts out finished: without JS, without
 * IntersectionObserver or under prefers-reduced-motion nothing is ever reset.
 */
export function RuleTerminal({ rule, reply }: { rule: string; reply: readonly string[] }) {
  const rootRef = useRef<HTMLDivElement>(null);
  const total = totalSteps(rule, reply);
  const [step, setStep] = useState(total);

  useEffect(() => {
    const el = rootRef.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;

    let timer: ReturnType<typeof setTimeout> | undefined;
    let cancelled = false;

    const run = (s: number) => {
      if (cancelled) return;
      setStep(s);
      if (s >= total) return;
      timer = setTimeout(() => run(s + 1), delayAfter(s, rule));
    };

    const io = new IntersectionObserver((entries) => {
      if (!entries.some((e) => e.isIntersecting)) return;
      io.disconnect();
      run(0);
    }, { threshold: 0.4 });

    // Armed only once the observer exists: from here the block starts empty
    // and fills in when it is seen.
    queueMicrotask(() => { if (!cancelled) setStep(0); });
    io.observe(el);
    return () => { cancelled = true; io.disconnect(); if (timer) clearTimeout(timer); };
  }, [rule, total]);

  const frame = frameAt(step, rule, reply);

  return (
    <div className={styles.window} ref={rootRef}>
      <div className={styles.bar} aria-hidden>
        <i /><i /><i />
        <span>rule: read back</span>
      </div>

      <div className={styles.sr}>
        <p>{rule}</p>
        {reply.map((l) => <p key={l}>{l}</p>)}
      </div>

      <div className={styles.screen} aria-hidden>
        <p className={styles.cmd}>
          <span className={styles.prompt}>&gt;</span>
          <span>{frame.typed}</span>
          {!frame.done && frame.lines.length === 0 ? <span className={styles.caret} /> : null}
        </p>
        {frame.lines.map((l) => (
          <p key={l} className={styles.out}>{l}</p>
        ))}
      </div>
    </div>
  );
}
