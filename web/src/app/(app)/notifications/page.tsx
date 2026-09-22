"use client";
import { useState } from "react";
import { api, type NotificationPage } from "@/lib/api";
import { useRead } from "@/lib/use-api";
import { ErrorNotice, Spinner } from "@/components/app/state";

const TYPES = ["", "order", "rule", "account", "risk", "system"];

export default function NotificationsPage() {
  const [type, setType] = useState("");
  const qs = new URLSearchParams({ limit: "50" });
  if (type) qs.set("type", type);
  const r = useRead<NotificationPage>(`notifications?${qs.toString()}`, 60_000);
  const [busy, setBusy] = useState(false);

  async function markOne(id: string) {
    setBusy(true);
    await api(`notifications/${id}/read`, { method: "POST" });
    setBusy(false);
    void r.reload();
  }
  async function markAll() {
    setBusy(true);
    await api("notifications/read-all", { method: "POST" });
    setBusy(false);
    void r.reload();
  }

  return (
    <main>
      <div className="card-head">
        <h1>Alerts</h1>
        {r.result?.ok && r.result.data.unread > 0 ? (
          <button className="btn btn-ghost" onClick={markAll} disabled={busy}>
            Mark all read ({r.result.data.unread})
          </button>
        ) : null}
      </div>
      <section className="card">
        <label className="field">
          <span>Type</span>
          <select value={type} onChange={(e) => setType(e.target.value)}>
            {TYPES.map((t) => <option key={t} value={t}>{t || "All"}</option>)}
          </select>
        </label>
      </section>
      {r.loading && !r.result ? <Spinner /> : null}
      {r.result && !r.result.ok ? <ErrorNotice error={r.result} onRetry={r.reload} /> : null}
      {r.result?.ok ? (
        <section className="card">
          {r.result.data.notifications.length ? (
            <ul style={{ listStyle: "none", padding: 0 }}>
              {r.result.data.notifications.map((n) => (
                <li key={n.id} className="notice" style={{ opacity: n.readAt ? 0.6 : 1 }}>
                  <div className="card-head">
                    <strong>{n.title}</strong>
                    <span className="muted">{new Date(n.ts * 1000).toLocaleString()}</span>
                  </div>
                  {n.body ? <p className="muted">{n.body}</p> : null}
                  {!n.readAt ? (
                    <button className="btn btn-ghost" disabled={busy}
                            onClick={() => markOne(n.id)}>Mark read</button>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : <p className="empty">No alerts.</p>}
        </section>
      ) : null}
    </main>
  );
}
