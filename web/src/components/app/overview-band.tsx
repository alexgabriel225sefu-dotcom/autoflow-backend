/**
 * The dashboard's first glance: four facts, large, read-only.
 *
 * Nothing here is a control and nothing here is a second source of truth.
 * Every value is handed in already derived by the page from the reads it was
 * making anyway, so a tile can never disagree with the panel below it. A read
 * that has not answered renders a dash, never a zero: "0 open" and "we have
 * not asked yet" must not look the same.
 */
export type Tile = {
  label: string;
  /** Null while the read is pending or failed — shown as a dash. */
  value: string | null;
  note?: string | null;
  tone?: "long" | "short" | "neutral";
};

export function OverviewBand({ tiles }: { tiles: Tile[] }) {
  return (
    <section className="ovb" aria-label="Overview">
      {tiles.map((t) => (
        <div className="ovb-tile" key={t.label} data-tone={t.tone ?? "neutral"}>
          <span className="ovb-label">{t.label}</span>
          <span className="ovb-value" data-empty={t.value === null ? "true" : undefined}>
            {t.value ?? "—"}
          </span>
          {t.note ? <span className="ovb-note">{t.note}</span> : <span className="ovb-note">&nbsp;</span>}
        </div>
      ))}
    </section>
  );
}
