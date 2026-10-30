"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { deleteAccount, exportAccount } from "@/lib/api";
import { createClient } from "@/lib/supabase/client";
import { plainError } from "./plain";

/** What has to be typed before the delete button works. */
export const DELETE_WORD = "DELETE";

/** Save JSON as a file through a temporary link. Browser-only. */
function download(filename: string, json: unknown) {
  const blob = new Blob([JSON.stringify(json, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/**
 * Export and delete. Both go through the API and show its answer; the delete
 * button stays disabled until DELETE is typed exactly, and the page only
 * signs out and leaves after the server said it was done.
 */
export function YourData() {
  const router = useRouter();
  const [exporting, setExporting] = useState(false);
  const [exportNote, setExportNote] = useState<{ ok: boolean; text: string } | null>(null);
  const [typed, setTyped] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  async function runExport() {
    setExporting(true);
    setExportNote(null);
    const r = await exportAccount();
    setExporting(false);
    if (!r.ok) { setExportNote({ ok: false, text: plainError(r) }); return; }
    const day = (r.data.exportedAt ?? "").slice(0, 10) || "export";
    download(`apex4traders-data-${day}.json`, r.data);
    setExportNote({ ok: true, text: "Your data was downloaded as a JSON file." });
  }

  async function runDelete() {
    if (typed !== DELETE_WORD) return;
    setDeleting(true);
    setDeleteError(null);
    const r = await deleteAccount(typed);
    if (!r.ok) {
      setDeleting(false);
      setDeleteError(plainError(r));
      return;
    }
    // The account is gone server-side. A sign-out failing now (the login may
    // no longer exist) must not strand the person on a dead session.
    try { await createClient().auth.signOut(); } catch { /* already gone */ }
    router.push("/");
    router.refresh();
  }

  return (
    <section className="card">
      <div className="card-head"><h2>Your data</h2></div>

      <p className="muted" style={{ fontSize: ".85rem" }}>
        Download a copy of what Apex4Traders holds about you: your rules,
        journal and settings, as a JSON file.
      </p>
      <button className="btn btn-ghost" type="button" onClick={() => void runExport()} disabled={exporting}>
        {exporting ? "Preparing…" : "Export my data"}
      </button>
      {exportNote ? (
        <p role={exportNote.ok ? "status" : "alert"} className="muted" style={{ fontSize: ".82rem" }}>
          {exportNote.text}
        </p>
      ) : null}

      <hr style={{ margin: "1rem 0", opacity: 0.2 }} />

      <h3 style={{ fontSize: ".95rem" }}>Delete account</h3>
      <p className="muted" style={{ fontSize: ".85rem" }}>
        Permanently deletes your account and the data held for it. This cannot
        be undone. Anything already open at your broker is not touched; close
        it in cTrader first if you want it closed. Type {DELETE_WORD} to
        confirm.
      </p>
      <label className="field">
        <span>Type {DELETE_WORD} to confirm</span>
        <input value={typed} autoComplete="off" onChange={(e) => setTyped(e.target.value)} />
      </label>
      {deleteError ? <div className="notice notice-error" role="alert">{deleteError}</div> : null}
      <button className="btn btn-danger" type="button" onClick={() => void runDelete()}
              disabled={typed !== DELETE_WORD || deleting}>
        {deleting ? "Deleting…" : "Delete my account"}
      </button>
    </section>
  );
}
