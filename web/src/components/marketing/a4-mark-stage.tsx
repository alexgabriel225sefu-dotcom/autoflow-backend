"use client";

import dynamic from "next/dynamic";
import { BrandMark } from "@/components/brand/logo";
import styles from "./a4-mark-stage.module.css";

// Three.js and the model are only needed here, and only in a browser: loaded
// after the page, never in the server render, so the first paint is the copy.
const A4Mark3D = dynamic(() => import("./a4-mark-3d").then((m) => m.A4Mark3D), {
  ssr: false,
  loading: () => null,
});

export function A4MarkStage() {
  return (
    <div className={styles.stage} role="img" aria-label="The Apex4Traders A4 monogram in polished chrome, turning slowly">
      <div className={styles.floor} aria-hidden="true" />
      <A4Mark3D
        fallback={
          <div className={styles.fallback} aria-hidden="true">
            <BrandMark size={160} />
          </div>
        }
      />
    </div>
  );
}
