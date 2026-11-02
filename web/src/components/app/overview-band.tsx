"use client";
import type { ReactNode } from "react";
import { onSpot } from "./spotlight";

/**
 * The dashboard's first glance: four facts, large, read-only.
 *
 * Nothing here is a control and nothing here is a second source of truth.
 * Every value is handed in already derived by the page from the reads it was
 * making anyway, so a tile can never disagree with the panel below it. A read
 * that has not answered renders a dash, never a zero: "0 open" and "we have
 * not asked yet" must not look the same.
 *
 * The tile is a spotlight card: a glow in the accent colour follows the
 * pointer and lights the border. It does not change the number.
 */
export type Tile = {
  label: string;
  /** Null while the read is pending or failed — shown as a dash. */
  value: ReactNode;
  note?: ReactNode;
  tone?: "long" | "short" | "neutral";
};

export function OverviewBand({ tiles }: { tiles: Tile[] }) {
  return (
    <section className="ovb" aria-label="Overview">
      {tiles.map((t) => (
        <div
          className="ovb-tile spot"
          key={t.label}
          data-tone={t.tone ?? "neutral"}
          onPointerMove={onSpot}
          onPointerDown={onSpot}
        >
          <span className="ovb-label">{t.label}</span>
          <span className="ovb-value" data-empty={t.value == null || t.value === "" ? "true" : undefined}>
            {t.value ?? "—"}
          </span>
          {t.note ? <span className="ovb-note">{t.note}</span> : <span className="ovb-note">&nbsp;</span>}
        </div>
      ))}
    </section>
  );
}
