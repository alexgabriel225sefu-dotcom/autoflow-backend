"use client";
import { useState } from "react";
import { CheckCheck } from "lucide-react";
import { api, type NotificationPage } from "@/lib/api";
import { useRead } from "@/lib/use-api";
import { ErrorNotice, Spinner } from "@/components/app/state";
import { When } from "@/components/app/table";
import { humanise } from "@/components/app/rule-summary";

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
      <div className="page-head">
        <div>
          <h1>Alerts</h1>
          <span className="sub">What the platform needed to tell you.</span>
        </div>
        <span className="btn-row">
          <div className="seg" role="group" aria-label="Filter by type">
            {TYPES.map((t) => (
              <button key={t} type="button" aria-pressed={type === t} onClick={() => setType(t)}>
                {t ? humanise(t) : "All"}
              </button>
            ))}
          </div>
          {r.result?.ok && r.result.data.unread > 0 ? (
            <button className="btn btn-ghost btn-sm" onClick={markAll} disabled={busy}>
              <CheckCheck className="ico" aria-hidden /> Mark all read ({r.result.data.unread})
            </button>
          ) : null}
        </span>
      </div>

      {r.loading && !r.result ? <Spinner /> : null}
      {r.result && !r.result.ok ? <ErrorNotice error={r.result} onRetry={r.reload} /> : null}
      {r.result?.ok ? (
        r.result.data.notifications.length ? (
          <div className="records">
            {r.result.data.notifications.map((n) => (
              <article className="record" key={n.id} style={{ opacity: n.readAt ? 0.6 : 1 }}>
                <div className="record-head">
                  <span className="record-title">
                    {!n.readAt ? (
                      <span aria-label="unread" style={{
                        display: "inline-block", width: 6, height: 6, borderRadius: 999,
                        background: "var(--a4t-accent)", marginRight: 7, verticalAlign: "middle",
                      }} />
                    ) : null}
                    {n.title}
                  </span>
                  <span className="btn-row">
                    <span className={n.level === "critical" ? "pill pill-warn"
                      : n.level === "warning" ? "pill pill-warn" : "pill pill-muted"}>
                      {n.type}
                    </span>
                    <span className="dim" style={{ fontSize: ".74rem" }}><When ts={n.ts} /></span>
                  </span>
                </div>
                {n.body ? (
                  <p className="muted" style={{ fontSize: ".83rem" }}>{n.body}</p>
                ) : null}
                {!n.readAt ? (
                  <button className="btn btn-ghost btn-sm" disabled={busy}
                          style={{ marginTop: ".5rem" }}
                          onClick={() => markOne(n.id)}>Mark read</button>
                ) : null}
              </article>
            ))}
          </div>
        ) : (
          <section className="card"><p className="empty">No alerts.</p></section>
        )
      ) : null}
    </main>
  );
}
