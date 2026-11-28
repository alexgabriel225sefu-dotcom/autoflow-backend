"use client";

import { useEffect, useState } from "react";
import styles from "./article-view.module.css";

export interface TocItem {
  readonly id: string;
  readonly label: string;
}

/**
 * "On this page" list. Plain anchor links work without JavaScript; once
 * hydrated, an IntersectionObserver marks the section being read.
 */
export function ArticleToc({ items }: { items: readonly TocItem[] }) {
  const [active, setActive] = useState<string>(items[0]?.id ?? "");

  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") return;
    const visible = new Set<string>();
    const observer = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) visible.add(e.target.id);
          else visible.delete(e.target.id);
        }
        const first = items.find((i) => visible.has(i.id));
        if (first) setActive(first.id);
      },
      { rootMargin: "-12% 0px -72% 0px", threshold: 0 },
    );
    for (const item of items) {
      const el = document.getElementById(item.id);
      if (el) observer.observe(el);
    }
    return () => observer.disconnect();
  }, [items]);

  return (
    <ol className={styles.tocList}>
      {items.map((item, i) => (
        <li key={item.id}>
          <a
            href={`#${item.id}`}
            className={styles.tocLink}
            data-active={active === item.id ? "true" : undefined}
            aria-current={active === item.id ? "location" : undefined}
          >
            <span className={styles.tocNum} aria-hidden="true">{String(i + 1).padStart(2, "0")}</span>
            <span>{item.label}</span>
          </a>
        </li>
      ))}
    </ol>
  );
}
