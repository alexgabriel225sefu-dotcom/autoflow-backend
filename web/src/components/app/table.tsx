"use client";
/**
 * One table definition, rendered two ways.
 *
 * A trading table on a phone was a horizontally scrolling grid, which means
 * the symbol scrolls out of view before you reach the price. The same columns
 * are declared once here and rendered as a table on a wide screen and as
 * stacked records on a narrow one, so the two can never drift apart the way
 * a hand-written mobile variant does.
 */
import type { ReactNode } from "react";

export type Column<T> = {
  key: string;
  header: string;
  /** Numbers are right-aligned and tabular; text is not. */
  num?: boolean;
  cell: (row: T) => ReactNode;
  /** Left out of the stacked card — used for the card's own title/badge. */
  hideOnCard?: boolean;
};

export function DataTable<T>({
  columns, rows, rowKey, empty, cardTitle, cardBadge,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  empty: string;
  /** The heading of each stacked record. Defaults to the first column. */
  cardTitle?: (row: T) => ReactNode;
  cardBadge?: (row: T) => ReactNode;
}) {
  if (!rows.length) return <p className="empty">{empty}</p>;
  const cardCols = columns.filter((c) => !c.hideOnCard);

  return (
    <>
      <div className="only-desktop scroll-x">
        <table className="tbl">
          <thead>
            <tr>
              {columns.map((c) => (
                <th key={c.key} className={c.num ? "num" : undefined}>{c.header}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={rowKey(r)}>
                {columns.map((c) => (
                  <td key={c.key} className={c.num ? "num mono" : undefined}>{c.cell(r)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="only-mobile records">
        {rows.map((r) => (
          <div className="record" key={rowKey(r)}>
            <div className="record-head">
              <span className="record-title">
                {cardTitle ? cardTitle(r) : columns[0].cell(r)}
              </span>
              {cardBadge ? cardBadge(r) : null}
            </div>
            <div className="record-grid">
              {cardCols.map((c) => (
                <div key={c.key}>
                  <span className="k">{c.header}</span>
                  <span className={c.num ? "v mono" : "v"}>{c.cell(r)}</span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </>
  );
}

/** BUY/SELL with the trading semantics of the palette, never as plain text. */
export function Side({ side }: { side: string }) {
  const s = String(side).toUpperCase();
  return <span className={s === "BUY" ? "side-long" : s === "SELL" ? "side-short" : undefined}>{s}</span>;
}

/**
 * A number, or an em dash.
 *
 * `null` means the broker did not give a value. It is shown as "—" and never
 * as 0, because 0 is a price and "we were not told" is not.
 */
export function Num({ value, digits }: { value: number | string | null | undefined; digits?: number }) {
  if (value === null || value === undefined || value === "") return <span className="dim">—</span>;
  const n = typeof value === "number" ? value : Number(value);
  if (Number.isNaN(n)) return <>{String(value)}</>;
  return <>{digits === undefined ? n.toLocaleString(undefined, { maximumFractionDigits: 6 }) : n.toFixed(digits)}</>;
}

/** A timestamp in seconds, shown in full. A chart without a time is a picture. */
export function When({ ts }: { ts: number }) {
  const d = new Date(ts * 1000);
  return (
    <time dateTime={d.toISOString()} title={d.toISOString()}>
      {d.toLocaleString(undefined, {
        year: "2-digit", month: "2-digit", day: "2-digit",
        hour: "2-digit", minute: "2-digit",
      })}
    </time>
  );
}
