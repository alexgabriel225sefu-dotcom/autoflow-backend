"use client";
import { RouteError } from "@/components/app/route-states";

/** Public pages (landing, login, legal). The signed-in area has its own. */
export default function Error({ error, retry }: { error: unknown; retry: () => void }) {
  return (
    <div className="a4t" style={{ padding: "var(--sp-4, 1.5rem)" }}>
      <RouteError error={error} retry={retry} />
    </div>
  );
}
