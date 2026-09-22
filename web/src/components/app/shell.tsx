"use client";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { api, type NotificationPage } from "@/lib/api";

const LINKS = [
  ["/dashboard", "Dashboard"],
  ["/rules", "Rules"],
  ["/positions", "Positions"],
  ["/orders", "Orders"],
  ["/journal", "Journal"],
  ["/notifications", "Alerts"],
  ["/accounts", "Accounts"],
  ["/settings", "Settings"],
] as const;

export function AppShell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const [unread, setUnread] = useState(0);

  useEffect(() => {
    let alive = true;
    const poll = async () => {
      const r = await api<NotificationPage>("notifications?limit=1");
      if (alive && r.ok) setUnread(r.data.unread);
    };
    void poll();
    const id = window.setInterval(() => { if (!document.hidden) void poll(); }, 60_000);
    return () => { alive = false; window.clearInterval(id); };
  }, [path]);

  async function signOut() {
    await createClient().auth.signOut();
    router.push("/login");
    router.refresh();
  }

  return (
    <div className="a4t">
      <nav className="nav">
        <div className="nav-inner">
          <a className="brand" href="/dashboard">Apex4Traders</a>
          <div className="nav-links">
            {LINKS.map(([href, label]) => (
              <a key={href} href={href} data-active={path === href || path.startsWith(`${href}/`)}>
                {label}
                {href === "/notifications" && unread > 0 ? (
                  <> <span className="badge" aria-label={`${unread} unread`}>{unread}</span></>
                ) : null}
              </a>
            ))}
          </div>
          <button className="btn btn-ghost" onClick={signOut}>Sign out</button>
        </div>
      </nav>
      <div className="shell">{children}</div>
    </div>
  );
}

/**
 * A confirmation step for anything that changes whether money can move.
 *
 * Start, pause, resume and stop all pass through here. The result shown
 * afterwards is the API's own answer, never an optimistic "Done" written
 * before the request came back.
 */
export function ConfirmAction({
  label, question, onConfirm, disabled, danger, disabledReason,
}: {
  label: string;
  question: string;
  onConfirm: () => Promise<string>;
  disabled?: boolean;
  danger?: boolean;
  disabledReason?: string;
}) {
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<string | null>(null);

  if (disabled) {
    return (
      <span className="btn-row">
        <button className="btn btn-ghost" disabled>{label}</button>
        {disabledReason ? <span className="muted">{disabledReason}</span> : null}
      </span>
    );
  }
  return (
    <span className="btn-row">
      {!asking ? (
        <button className={danger ? "btn btn-danger" : "btn"} onClick={() => { setOutcome(null); setAsking(true); }}>
          {label}
        </button>
      ) : (
        <>
          <span className="muted">{question}</span>
          <button className="btn" disabled={busy} onClick={async () => {
            setBusy(true);
            const msg = await onConfirm();
            setBusy(false);
            setAsking(false);
            setOutcome(msg);
          }}>{busy ? "Working…" : "Yes"}</button>
          <button className="btn btn-ghost" disabled={busy} onClick={() => setAsking(false)}>Cancel</button>
        </>
      )}
      {outcome ? <span className="muted" role="status">{outcome}</span> : null}
    </span>
  );
}
