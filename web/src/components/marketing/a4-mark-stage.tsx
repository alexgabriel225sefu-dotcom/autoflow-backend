"use client";

import dynamic from "next/dynamic";
import { BrandMark } from "@/components/brand/logo";
import { SceneGuard } from "./scene-guard";
import styles from "./a4-mark-stage.module.css";

// Three.js and the model are only needed here, and only in a browser: loaded
// after the page, never in the server render, so the first paint is the copy.
const ChromeScene = dynamic(() => import("./chrome-scene").then((m) => m.ChromeScene), {
  ssr: false,
  loading: () => null,
});

const FALLBACK = (
  <div className={styles.fallback} aria-hidden="true">
    <BrandMark size={160} />
  </div>
);

export function A4MarkStage() {
  return (
    <div className={styles.stage} role="img" aria-label="The Apex4Traders A4 monogram in polished chrome, turning slowly">
      <div className={styles.floor} aria-hidden="true" />
      <SceneGuard fallback={FALLBACK}>
        <ChromeScene model="/models/a4-mark.glb" fallback={FALLBACK} />
      </SceneGuard>
    </div>
  );
}
