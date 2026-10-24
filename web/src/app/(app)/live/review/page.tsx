"use client";
/**
 * Operator review of live-account requests.
 *
 * The server decides who is an operator. This page only sends the decision
 * the person typed; it cannot grant the decision by being open.
 */
import { useState } from "react";
import { api } from "@/lib/api";
import { ErrorNotice } from "@/components/app/state";
import { LiveAccessPanel } from "@/components/app/live-access";
import type { ApiError, LiveGateVerdict } from "@/lib/api";

type QueueRow = { userId: string; status: string; requestedAt?: number };
type Review = { verdict: LiveGateVerdict; status: string; reason?: string };

export default function LiveReviewPage() {
  const [rows, setRows] = useState<QueueRow[] | null>(null);
  const [userId, setUserId] = useState("");
  const [review, setReview] = useState<Review | null>(null);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  async function loadQueue() {
    setBusy(true);
    setError(null);
    const result = await api<{ requests: QueueRow[] }>("live/queue");
    setBusy(false);
    if (!result.ok) {
      setError(result);
      setRows(null);
      return;
    }
    setRows(result.data.requests ?? []);
  }

  async function loadOne(id = userId) {
    const target = id.trim();
    if (!target) return;
    setBusy(true);
    setError(null);
    setUserId(target);
    const result = await api<Review>(`live/requests/${encodeURIComponent(target)}`);
    setBusy(false);
    if (!result.ok) {
      setError(result);
      setReview(null);
      return;
    }
    setReview(result.data);
  }

  async function decide(decision: "approved" | "rejected") {
    const target = userId.trim();
    if (!target) return;
    setBusy(true);
    setError(null);
    const result = await api<Review>(`live/requests/${encodeURIComponent(target)}/decide`, {
      method: "POST",
      body: { decision, reason },
    });
    setBusy(false);
    if (!result.ok) {
      setError(result);
      return;
    }
    setReview(result.data);
    void loadQueue();
  }

  const operatorOnly = !!error && error.status === 403 && error.code === "NOT_OPERATOR";

  return (
    <main>
      <div className="page-head">
        <div>
          <h1>Live access</h1>
          <span className="sub">Review a request. Approval is recorded on the server.</span>
        </div>
      </div>
      {operatorOnly ? (
        <section className="notice" role="status">
          <p style={{ fontWeight: 600 }}>Operators only</p>
          <p className="muted" style={{ fontSize: ".82rem" }}>{error.message}</p>
        </section>
      ) : (
      <>
      {error ? <ErrorNotice error={error} /> : null}
      <section className="card">
        <div className="btn-row">
          <button type="button" disabled={busy} onClick={() => void loadQueue()}>
            Load queue
          </button>
        </div>
        {rows ? (
          rows.length ? (
            <ul>
              {rows.map((row) => (
                <li key={row.userId}>
                  <button type="button" onClick={() => void loadOne(row.userId)}>
                    {row.userId}
                  </button>
                  {" "}
                  {row.status}
                </li>
              ))}
            </ul>
          ) : <p className="empty">No requests on file.</p>
        ) : null}
      </section>
      <section className="card">
        <label>
          User id
          <input value={userId} onChange={(event) => setUserId(event.target.value)} />
        </label>
        <div className="btn-row">
          <button type="button" disabled={busy} onClick={() => void loadOne()}>
            Load
          </button>
          <button type="button" disabled={busy} onClick={() => void decide("approved")}>
            Approve
          </button>
          <button type="button" disabled={busy} onClick={() => void decide("rejected")}>
            Reject
          </button>
        </div>
        <label>
          Reason
          <input value={reason} onChange={(event) => setReason(event.target.value)} />
        </label>
        {review ? (
          <>
            <p>Request: {review.status}</p>
            <LiveAccessPanel gate={review.verdict} />
          </>
        ) : null}
      </section>
      </>
      )}
    </main>
  );
}
