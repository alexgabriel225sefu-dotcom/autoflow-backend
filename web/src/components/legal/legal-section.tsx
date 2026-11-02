"use client";

import {
  Children,
  createContext,
  isValidElement,
  useContext,
  useEffect,
  useId,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactElement,
  type ReactNode,
} from "react";
import styles from "./legal-section.module.css";

/**
 * Collapsible legal sections, after the "Privacy Policy Collapsible Card"
 * pattern on 21st.dev by cnippet-dev. Written natively for this codebase.
 *
 * The full text is always in the server-rendered HTML. Before hydration every
 * section is open, so the page reads with JavaScript off. Once hydrated, all
 * but the first collapse. A collapsed body stays in the DOM, marked
 * hidden="until-found" so Ctrl+F can find it and open it where supported.
 */

const SETTLE_MS = 230;

type Ctx = {
  ready: boolean;
  animate: boolean;
  open: boolean[];
  setOpen: (index: number, value: boolean) => void;
};

const SectionsContext = createContext<Ctx | null>(null);
const IndexContext = createContext(0);

const subscribeNever = () => () => {};

function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/** Wraps the LegalSection children, owns the open state and the controls. */
export function LegalSections({ children }: { children: ReactNode }) {
  const items = Children.toArray(children);
  // False while rendering on the server and during hydration, true after.
  const ready = useSyncExternalStore(subscribeNever, () => true, () => false);
  const [animate, setAnimate] = useState(false);
  const [open, setOpenState] = useState<boolean[]>(() => items.map((_, i) => i === 0));

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => setAnimate(true));
    return () => window.cancelAnimationFrame(frame);
  }, []);

  const setOpen = (index: number, value: boolean) =>
    setOpenState((prev) => prev.map((v, i) => (i === index ? value : v)));
  const setAll = (value: boolean) => setOpenState(items.map(() => value));

  const allOpen = items.every((_, i) => open[i]);
  const allClosed = items.every((_, i) => !open[i]);

  return (
    <SectionsContext.Provider value={{ ready, animate, open, setOpen }}>
      {ready ? (
        <div className={styles.controls}>
          <button type="button" className={styles.controlBtn} disabled={allOpen} onClick={() => setAll(true)}>
            Expand all
          </button>
          <button type="button" className={styles.controlBtn} disabled={allClosed} onClick={() => setAll(false)}>
            Collapse all
          </button>
        </div>
      ) : null}
      {items.map((child, i) => (
        <IndexContext.Provider key={isValidElement(child) && child.key != null ? child.key : i} value={i}>
          {child}
        </IndexContext.Provider>
      ))}
    </SectionsContext.Provider>
  );
}

/**
 * One section. Its first child must be the section's <h2>; the rest is the
 * body. The h2 text is unchanged: it becomes the label of the heading button.
 */
export function LegalSection({ children }: { children: ReactNode }) {
  const ctx = useContext(SectionsContext);
  const index = useContext(IndexContext);
  const reactId = useId();
  const parts = Children.toArray(children);
  const headingEl = parts.find(
    (p): p is ReactElement<{ children?: ReactNode }> => isValidElement(p) && p.type === "h2",
  );
  const body = parts.filter((p) => p !== headingEl);
  const headingChildren = headingEl?.props.children;
  const text = typeof headingChildren === "string" ? headingChildren : "";
  const number = /^(\d+)\./.exec(text)?.[1];
  const id = number ? `section-${number}` : `section-${reactId.replace(/:/g, "")}`;
  const panelId = `${id}-panel`;

  const isOpen = !ctx || !ctx.ready || Boolean(ctx.open[index]);
  const innerRef = useRef<HTMLDivElement>(null);
  const setOpen = ctx?.setOpen;
  const animate = ctx?.animate ?? false;

  // Keep the body unhidden while it opens and while it animates closed, then
  // mark it hidden once the height has reached zero. The attribute is set on
  // the node because React's types only know hidden as a boolean, and
  // "until-found" is what lets find-in-page reach the collapsed text.
  useEffect(() => {
    const el = innerRef.current;
    if (!el) return;
    if (isOpen) {
      el.removeAttribute("hidden");
      return;
    }
    const wait = animate && !prefersReducedMotion() ? SETTLE_MS : 0;
    const timer = window.setTimeout(() => el.setAttribute("hidden", "until-found"), wait);
    return () => window.clearTimeout(timer);
  }, [isOpen, animate]);

  // Ctrl+F landing in a collapsed body opens its section.
  useEffect(() => {
    const el = innerRef.current;
    if (!el || !setOpen) return;
    const onMatch = () => setOpen(index, true);
    el.addEventListener("beforematch", onMatch);
    return () => el.removeEventListener("beforematch", onMatch);
  }, [setOpen, index]);

  // A link to #section-N opens that section.
  useEffect(() => {
    if (!setOpen || !ctx?.ready) return;
    const check = () => {
      if (window.location.hash === `#${id}`) {
        setOpen(index, true);
        document.getElementById(id)?.scrollIntoView();
      }
    };
    check();
    window.addEventListener("hashchange", check);
    return () => window.removeEventListener("hashchange", check);
  }, [ctx?.ready, setOpen, index, id]);

  const cls = [
    styles.card,
    isOpen ? styles.open : styles.closed,
    animate ? styles.animate : "",
  ].join(" ");

  return (
    <section id={id} className={cls} aria-labelledby={`${id}-heading`}>
      <h2 id={`${id}-heading`} className={styles.heading}>
        {ctx && ctx.ready ? (
          <button
            type="button"
            className={styles.trigger}
            aria-expanded={isOpen}
            aria-controls={panelId}
            onClick={() => ctx.setOpen(index, !isOpen)}
          >
            <span>{headingChildren}</span>
            <span className={styles.chevron} aria-hidden="true" />
          </button>
        ) : (
          <span className={styles.trigger}>{headingChildren}</span>
        )}
      </h2>
      <div className={styles.panel}>
        <div
          ref={innerRef}
          id={panelId}
          role="region"
          aria-labelledby={`${id}-heading`}
          className={styles.inner}
        >
          <div className={styles.body}>{body}</div>
        </div>
      </div>
    </section>
  );
}
