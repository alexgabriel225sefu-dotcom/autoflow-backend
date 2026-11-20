"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import { useRead } from "@/lib/use-api";

/**
 * Your own tags and comment on one journal entry. They are kept beside the
 * entry and never change it. Nothing is requested until the panel is opened,
 * so a page of entries makes no extra requests.
 */
type Note = { tags: string[]; comment: string; updatedAt: number | null } | null;

export function JournalNote({ entryId }: { entryId: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ marginTop: ".45rem" }}>
      <button type="button" className="btn btn-ghost btn-sm" aria-expanded={open}
              onClick={() => setOpen(!open)}>
        {open ? "Hide notes" : "Tags and notes"}
      </button>
      {open ? <Editor entryId={entryId} /> : null}
    </div>
  );
}

function Editor({ entryId }: { entryId: string }) {
  const path = `journal/${entryId}/note`;
  const r = useRead<{ note: Note }>(path);
  const [tags, setTags] = useState<string | null>(null);
  const [comment, setComment] = useState<string | null>(null);
  const [state, setState] = useState<"idle" | "saving" | "saved" | string>("idle");

  if (r.loading && !r.result) return <p className="muted">Loading…</p>;
  if (r.result && !r.result.ok) {
    return <p role="alert" className="notice notice-error">Your notes could not be read just now.</p>;
  }
  const note = r.result?.ok ? r.result.data.note : null;
  const tagText = tags ?? (note?.tags ?? []).join(", ");
  const commentText = comment ?? (note?.comment ?? "");

  async function save() {
    setState("saving");
    const res = await api<{ note: Note }>(path, {
      method: "PUT",
      body: { tags: tagText.split(",").map((t) => t.trim()).filter(Boolean), comment: commentText },
    });
    if (!res.ok) { setState(res.message || res.code); return; }
    setState("saved");
    void r.reload();
  }

  return (
    <div style={{ marginTop: ".45rem" }}>
      <label className="field">
        <span>Tags (comma separated)</span>
        <input value={tagText} maxLength={300} onChange={(e) => { setTags(e.target.value); setState("idle"); }} />
      </label>
      <label className="field">
        <span>Comment</span>
        <textarea rows={3} maxLength={2000} value={commentText}
                  onChange={(e) => { setComment(e.target.value); setState("idle"); }} />
      </label>
      <div className="btn-row">
        <button type="button" className="btn btn-sm" onClick={save} disabled={state === "saving"}>Save</button>
        {state === "saved" ? <span className="muted" role="status">Saved</span> : null}
        {state !== "idle" && state !== "saving" && state !== "saved"
          ? <span role="alert" className="notice notice-error">{state}</span> : null}
      </div>
    </div>
  );
}
