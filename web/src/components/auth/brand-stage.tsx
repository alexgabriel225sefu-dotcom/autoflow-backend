"use client";
/**
 * The A4 mark in depth, and the sign-in screen's motion.
 *
 * Three things move, all of them tied to what the person is doing:
 *   - the mark is stacked in layers, so it reads as a solid object, and it
 *     turns a little toward the pointer;
 *   - every letter typed in a field pops up above the caret, and the mark
 *     gives a small kick as if it felt the keystroke;
 *   - while the form is signing in, the mark turns on its axis.
 * Everything is decoration and is switched off for anyone who asked their
 * system for less motion. It reads no credentials: for a password field it
 * shows a dot, never the character.
 */
import { useEffect, useRef } from "react";
import styles from "./auth-shell.module.css";

const LAYERS = 9;
// The approved lockup is one sprite: the mark is its first 178px, the
// wordmark starts at 355px. Cropped with background-position, never redrawn.
const S = 0.36;

function reduced() {
  return !!window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
}

/** Web Animations where the browser has them; nothing where it does not (jsdom, old browsers). */
function play(el: Element | null | undefined, frames: Keyframe[], opts: KeyframeAnimationOptions) {
  if (!el || typeof (el as HTMLElement).animate !== "function") return null;
  return el.animate(frames, opts);
}

export function BrandStage() {
  const root = useRef<HTMLDivElement>(null);
  const tilt = useRef<HTMLDivElement>(null);
  const kick = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const stage = root.current;
    const main = stage?.closest("main");
    if (!stage || !main || reduced()) return;
    const measure = document.createElement("canvas").getContext("2d");

    // 1. Turn toward the pointer.
    function onMove(e: PointerEvent) {
      const r = stage!.getBoundingClientRect();
      const dx = (e.clientX - (r.left + r.width / 2)) / window.innerWidth;
      const dy = (e.clientY - (r.top + r.height / 2)) / window.innerHeight;
      tilt.current?.style.setProperty("--ry", `${(dx * 38).toFixed(2)}deg`);
      tilt.current?.style.setProperty("--rx", `${(-dy * 26).toFixed(2)}deg`);
    }

    // 2. A letter pops above the caret, and the mark kicks.
    function onInput(e: Event) {
      const input = e.target as HTMLInputElement | null;
      if (!input || input.tagName !== "INPUT") return;
      const ie = e as InputEvent;
      const typed = ie.data;
      play(kick.current,
        [
          { transform: "scale(1) rotateZ(0deg)" },
          { transform: `scale(1.14) rotateZ(${(Math.random() * 8 - 4).toFixed(1)}deg)`, offset: 0.35 },
          { transform: "scale(1) rotateZ(0deg)" },
        ],
        { duration: 240, easing: "cubic-bezier(.2,.8,.2,1)" },
      );
      const field = input.closest("label.field") as HTMLElement | null;
      if (!field) return;
      play(input,
        [{ boxShadow: "0 0 0 0 rgba(255,148,132,.0)" }, { boxShadow: "0 0 26px 0 rgba(255,148,132,.35)", offset: 0.3 }, { boxShadow: "0 0 0 0 rgba(255,148,132,0)" }],
        { duration: 420, easing: "ease-out" },
      );
      if (!typed) return;
      const shown = input.type === "password" ? "•" : typed;
      const cs = getComputedStyle(input);
      if (measure) measure.font = `${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
      const textW = measure && input.type !== "password" ? measure.measureText(input.value).width : input.value.length * 7;
      const box = input.getBoundingClientRect();
      const host = field.getBoundingClientRect();
      const x = Math.min(box.width - 24, parseFloat(cs.paddingLeft) + textW) + (box.left - host.left);
      const pop = document.createElement("span");
      pop.textContent = shown;
      pop.setAttribute("aria-hidden", "true");
      Object.assign(pop.style, {
        position: "absolute", left: `${x}px`, top: `${box.top - host.top - 4}px`, zIndex: "3",
        pointerEvents: "none", font: "700 1.1rem/1 var(--font-geist-mono, ui-monospace, monospace)",
        color: "#ff9484", textShadow: "0 0 14px rgba(255,148,132,.7)",
      });
      field.appendChild(pop);
      const anim = play(pop,
        [{ transform: "translate3d(0,0,0) scale(.6)", opacity: 0 }, { transform: "translate3d(0,-14px,0) scale(1.25)", opacity: 1, offset: 0.25 }, { transform: `translate3d(${(Math.random() * 16 - 8).toFixed(0)}px,-46px,0) scale(.9)`, opacity: 0 }],
        { duration: 780, easing: "cubic-bezier(.2,.7,.2,1)" },
      );
      if (anim) anim.onfinish = () => pop.remove(); else pop.remove();
    }

    // 3. Turn on the spot while the form is signing in.
    const watch = new MutationObserver(() => {
      const busy = !!main.querySelector('button[aria-busy="true"]');
      stage.dataset.busy = busy ? "true" : "false";
    });
    watch.observe(main, { subtree: true, attributes: true, attributeFilter: ["aria-busy"] });

    main.addEventListener("pointermove", onMove);
    main.addEventListener("input", onInput);
    return () => {
      main.removeEventListener("pointermove", onMove);
      main.removeEventListener("input", onInput);
      watch.disconnect();
    };
  }, []);

  const sprite = (x: number, w: number): React.CSSProperties => ({
    width: w * S, height: 152 * S, backgroundImage: "url(/apex4traders-logo-light.png)",
    backgroundSize: `${1116 * S}px ${152 * S}px`, backgroundPosition: `${-x * S}px 0`, backgroundRepeat: "no-repeat",
  });

  return (
    <div ref={root} className={styles.stage} data-busy="false" role="img" aria-label="Apex4Traders">
      <div ref={tilt} className={styles.tilt}>
        <div ref={kick} className={styles.kick}>
          <div className={styles.solid} aria-hidden="true">
            {Array.from({ length: LAYERS }, (_, i) => (
              <i key={i} className={i === 0 ? styles.front : styles.depth}
                 style={{ ...sprite(0, 178), transform: `translateZ(${-i * 2.4}px)`, opacity: i === 0 ? 1 : 0.9 - i * 0.07 }} />
            ))}
          </div>
        </div>
      </div>
      <i className={styles.word} aria-hidden="true" style={sprite(355, 761)} />
    </div>
  );
}
