"use client";
/**
 * The client's live-access flow.
 *
 * Accepting terms and requesting a connection are the only writes. Neither
 * one selects a broker account or starts automation. The verdict on the page
 * is the server's.
 */
import { useState } from "react";
import Link from "next/link";
import { api, type LiveGateVerdict } from "@/lib/api";
import { invalidate, useRead } from "@/lib/use-api";
import { ErrorNotice, Spinner } from "@/components/app/state";
import { LiveAccessPanel } from "@/components/app/live-access";
import type { ApiError } from "@/lib/api";

export default function LiveAccessPage() {
  const status = useRead<LiveGateVerdict>("live/status");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const gate = status.result?.ok ? status.result.data : null;

  async function post(path: "live/accept" | "live/request") {
    setBusy(path);
    setError(null);
    setNote(null);
    const result = await api<LiveGateVerdict>(path, { method: "POST", body: {} });
    setBusy(null);
    if (!result.ok) {
      setError(result);
      return;
    }
    setNote(path === "live/accept"
      ? "The current published versions are recorded as accepted."
      : "The request is on file. It does not connect a broker account.");
    invalidate("live/status", "me");
  }

  return (
    <main>
      <div className="page-head">
        <div>
          <h1>Live access</h1>
          <span className="sub">What still has to be true before a live account can be used.</span>
        </div>
      </div>
      {status.loading && !status.result ? <Spinner /> : null}
      {status.result && !status.result.ok ? (
        <ErrorNotice error={status.result} onRetry={status.reload} />
      ) : null}
      {error ? <ErrorNotice error={error} /> : null}
      {note ? <p className="muted">{note}</p> : null}
      <LiveAccessPanel gate={gate} />
      <div className="btn-row" style={{ marginTop: "var(--sp-3)" }}>
        <button type="button" disabled={busy !== null} onClick={() => void post("live/accept")}>
          {busy === "live/accept" ? "Saving…" : "Accept current terms"}
        </button>
        <button type="button" disabled={busy !== null} onClick={() => void post("live/request")}>
          {busy === "live/request" ? "Sending…" : "Request a live account connection"}
        </button>
      </div>
      <p className="muted" style={{ marginTop: "var(--sp-3)" }}>
        <Link href="/license">Licence</Link>
        {" · "}
        <Link href="/live/review">Operator review</Link>
      </p>
    </main>
  );
}
