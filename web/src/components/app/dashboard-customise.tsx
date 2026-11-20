"use client";
import { useState } from "react";
import { SlidersHorizontal } from "lucide-react";
import { WIDGETS, toggle, writeHidden, type WidgetId } from "@/lib/dashboard-layout";

/**
 * Choose which optional cards the dashboard shows. The approval and the
 * automation card (with its stop controls) are not offered here: they carry a
 * deadline or a safety control, so they are always there.
 */
export function DashboardCustomise({
  hidden,
}: { hidden: ReadonlySet<WidgetId> }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button type="button" className="btn btn-ghost btn-sm" aria-expanded={open}
              onClick={() => setOpen(!open)}>
        <SlidersHorizontal className="ico" aria-hidden /> Customise
      </button>
      {open ? (
        <fieldset className="card" style={{ marginTop: ".5rem" }}>
          <legend className="muted" style={{ fontSize: ".8rem" }}>Cards on this dashboard</legend>
          {WIDGETS.map((w) => (
            <label key={w.id} style={{ display: "flex", gap: ".5rem", alignItems: "center", padding: ".2rem 0" }}>
              <input type="checkbox" checked={!hidden.has(w.id)}
                     onChange={() => writeHidden(toggle(hidden, w.id))} />
              {w.label}
            </label>
          ))}
          <p className="muted" style={{ fontSize: ".78rem", margin: ".4rem 0" }}>
            The approval and the automation card with its stop controls always stay.
          </p>
          <button type="button" className="btn btn-ghost btn-sm"
                  disabled={hidden.size === 0}
                  onClick={() => writeHidden(new Set())}>
            Show everything again
          </button>
        </fieldset>
      ) : null}
    </div>
  );
}
