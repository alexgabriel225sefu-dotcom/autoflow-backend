"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import { invalidate, useRead } from "@/lib/use-api";
import { ConfirmAction } from "@/components/app/shell";
import { ErrorNotice, Spinner } from "@/components/app/state";

/**
 * Every version of a rule that is stored, what changed between two of them, and
 * a way back to an earlier one.
 *
 * Only versions the server has are listed; a version that was never activated
 * has no stored copy and is not invented. Going back never edits the old
 * version or the running one: the server opens a new draft carrying the old
 * terms, and the reader activates it when they choose.
 */
type Version = { version: number; state: string | null; activatedAt: number | null; frozen: boolean };
type Change = { path: string; kind: "added" | "removed" | "changed"; before: unknown; after: unknown };

const show = (v: unknown) =>
  v === null || v === undefined ? "—" : typeof v === "object" ? JSON.stringify(v) : String(v);
const when = (t: number | null) =>
  t == null ? "not activated" : new Date(t * 1000).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

export function RuleHistory({ id, onChanged }: { id: string; onChanged?: () => void }) {
  const list = useRead<{ versions: Version[] }>(`rules/${id}/versions`);
  const [pair, setPair] = useState<{ from: number; to: number } | null>(null);
  const diff = useRead<{ changes: Change[] }>(
    pair ? `rules/${id}/diff?from=${pair.from}&to=${pair.to}` : null);

  const versions = list.result?.ok ? list.result.data.versions : null;

  async function revert(version: number) {
    const r = await api(`rules/${id}/revert`, { method: "POST", body: { version } });
    if (!r.ok) return r.code;
    invalidate("rules");
    void list.reload();
    onChanged?.();
    return `Draft opened with the terms of v${version}`;
  }

  return (
    <section className="card" style={{ marginTop: ".85rem" }} aria-label="Version history">
      <div className="card-head">
        <h2>Version history</h2>
        <span className="dim" style={{ fontSize: ".75rem" }}>
          Each activated version keeps its terms for good
        </span>
      </div>
      {list.loading && !list.result ? <Spinner /> : null}
      {list.result && !list.result.ok ? <ErrorNotice error={list.result} onRetry={list.reload} /> : null}
      {versions && versions.length === 0 ? <p className="empty">No versions are stored yet.</p> : null}
      {versions && versions.length > 0 ? (
        <ul className="plain-list">
          {versions.map((v, i) => {
            const next = versions[i + 1];
            return (
              <li key={v.version} style={{ display: "flex", gap: ".6rem", alignItems: "center", flexWrap: "wrap" }}>
                <strong>v{v.version}</strong>
                <span className="muted">{v.state ?? "—"} · {when(v.activatedAt)}</span>
                {next ? (
                  <button type="button" className="btn btn-ghost btn-sm"
                          onClick={() => setPair({ from: next.version, to: v.version })}>
                    What changed since v{next.version}
                  </button>
                ) : null}
                {v.frozen ? (
                  <ConfirmAction
                    label={`Go back to v${v.version}`}
                    question={`Open a new draft with the terms of v${v.version}? Nothing that is running changes until you activate it.`}
                    onConfirm={() => revert(v.version)}
                  />
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : null}

      {pair ? (
        <div role="region" aria-label={`Changes from v${pair.from} to v${pair.to}`} style={{ marginTop: ".8rem" }}>
          <h3 style={{ fontSize: ".9rem" }}>v{pair.from} → v{pair.to}</h3>
          {diff.loading && !diff.result ? <Spinner /> : null}
          {diff.result && !diff.result.ok ? <ErrorNotice error={diff.result} onRetry={diff.reload} /> : null}
          {diff.result?.ok && diff.result.data.changes.length === 0 ? (
            <p className="muted">The terms of these two versions are identical.</p>
          ) : null}
          {diff.result?.ok && diff.result.data.changes.length > 0 ? (
            <ul className="plain-list">
              {diff.result.data.changes.map((c) => (
                <li key={c.path} data-kind={c.kind}>
                  <code>{c.path}</code>{" "}
                  <span className="muted">
                    {c.kind === "added" ? `added: ${show(c.after)}`
                      : c.kind === "removed" ? `removed (was ${show(c.before)})`
                      : `${show(c.before)} → ${show(c.after)}`}
                  </span>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
