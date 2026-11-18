"use client";

import dynamic from "next/dynamic";
import styles from "./scroll-backdrop.module.css";

// Loaded after the page and never on the server: the first paint is the copy.
const Scene = dynamic(() => import("./scroll-backdrop-scene").then((m) => m.ScrollBackdropScene), {
  ssr: false,
  loading: () => null,
});

export function ScrollBackdrop() {
  return (
    <div className={styles.layer} aria-hidden="true" data-testid="scroll-backdrop">
      <Scene model="/models/a4-mark.glb" />
    </div>
  );
}
