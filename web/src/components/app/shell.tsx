"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { LogOut, MoreHorizontal, X } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import type { AutomationState, CtraderStatus, Me, NotificationPage } from "@/lib/api";
import { useRead } from "@/lib/use-api";
import { isActive, NAV, PRIMARY, SECONDARY, titleFor } from "./nav";
import { StatusBar } from "./status-bar";

/**
 * The application shell.
 *
 * Desktop gets a sidebar; a phone gets a bottom bar for the four most-used
 * destinations and a drawer for the rest. The previous shell was a single
 * horizontally scrolling strip that, measured at 390px, showed 135px of a
 * 599px list — one destination out of eight, with nothing on screen to
 * suggest the other seven existed.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const [unread, setUnread] = useState(0);
  const [drawer, setDrawer] = useState(false);

  // One fetch of each, shared with the status strip, rather than every page
  // asking again for the same three facts.
  const me = useRead<Me>("me", 120_000);
  const ct = useRead<CtraderStatus>("accounts", 60_000);
  const auto = useRead<AutomationState>("automation", 30_000);
  const notes = useRead<NotificationPage>("notifications?limit=1", 60_000);

  useEffect(() => {
    if (notes.result?.ok) setUnread(notes.result.data.unread);
  }, [notes.result]);

  // A route change must close the drawer, or the new page arrives underneath it.
  useEffect(() => { setDrawer(false); }, [path]);

  useEffect(() => {
    if (!drawer) return;
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setDrawer(false); };
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [drawer]);

  async function signOut() {
    await createClient().auth.signOut();
    router.push("/login");
    router.refresh();
  }

  const badge = (href: string) =>
    href === "/notifications" && unread > 0 ? (
      <span className="pill pill-accent" style={{ padding: "0 .3rem", fontSize: ".62rem" }}>
        {unread > 99 ? "99+" : unread}
      </span>
    ) : null;

  return (
    <div className="a4t app">
      <aside className="side">
        <Link className="side-brand" href="/dashboard">
          <span className="side-mark" aria-hidden />
          Apex4Traders
        </Link>

        <p className="label-xs side-group" style={{ marginTop: 0 }}>Operations</p>
        {NAV.slice(0, 5).map(({ href, label, icon: Icon }) => (
          <Link key={href} className="side-link" href={href} data-active={isActive(path, href)}>
            <Icon className="ico" aria-hidden />
            <span style={{ flex: 1 }}>{label}</span>
            {badge(href)}
          </Link>
        ))}

        <p className="label-xs side-group">Account</p>
        {NAV.slice(5).map(({ href, label, icon: Icon }) => (
          <Link key={href} className="side-link" href={href} data-active={isActive(path, href)}>
            <Icon className="ico" aria-hidden />
            <span style={{ flex: 1 }}>{label}</span>
            {badge(href)}
          </Link>
        ))}

        <div className="side-foot">
          <button className="side-link" onClick={signOut} style={{ width: "100%" }}>
            <LogOut className="ico" aria-hidden />
            <span>Sign out</span>
          </button>
        </div>
      </aside>

      <div className="main-col">
        <header className="topbar">
          <Link className="topbar-brand" href="/dashboard">
            <span className="side-mark" aria-hidden />
          </Link>
          <span className="topbar-title">{titleFor(path)}</span>
          <span className="topbar-spacer" />
          {/* Sign out lives in the sidebar on desktop and in the drawer on a
              phone, so the top bar does not carry a second copy of it. */}
        </header>

        <StatusBar me={me.result} ct={ct.result} auto={auto.result} />

        <div className="shell">{children}</div>
      </div>

      <nav className="bottomnav" aria-label="Primary">
        {PRIMARY.map(({ href, label, icon: Icon }) => (
          <Link key={href} href={href} data-active={isActive(path, href)}>
            <Icon className="ico" aria-hidden />
            {label}
          </Link>
        ))}
        <button
          onClick={() => setDrawer(true)}
          data-active={SECONDARY.some((n) => isActive(path, n.href))}
          aria-expanded={drawer}
          aria-label="More destinations"
        >
          <span style={{ position: "relative", display: "inline-flex" }}>
            <MoreHorizontal className="ico" aria-hidden />
            {unread > 0 ? (
              <span
                aria-hidden
                style={{
                  position: "absolute", top: -2, right: -3, width: 6, height: 6,
                  borderRadius: 999, background: "var(--a4t-accent)",
                }}
              />
            ) : null}
          </span>
          More
        </button>
      </nav>

      {drawer ? (
        <>
          <button className="drawer-scrim" aria-label="Close menu" onClick={() => setDrawer(false)} />
          <div className="drawer" role="dialog" aria-modal="true" aria-label="More destinations">
            <div className="drawer-grip" />
            <div className="card-head" style={{ marginBottom: ".6rem" }}>
              <span className="label-xs">All destinations</span>
              <button className="btn btn-ghost btn-sm" onClick={() => setDrawer(false)}>
                <X className="ico" aria-hidden /> Close
              </button>
            </div>
            {/* Every destination, not only the overflow: someone who opened
                this menu is looking for a page, and making them remember
                which bar holds which one is the problem being fixed. */}
            <div className="drawer-links">
              {NAV.map(({ href, label, icon: Icon }) => (
                <Link key={href} href={href} data-active={isActive(path, href)}>
                  <Icon className="ico" aria-hidden />
                  <span style={{ flex: 1 }}>{label}</span>
                  {badge(href)}
                </Link>
              ))}
            </div>
            <button
              className="btn btn-ghost"
              style={{ width: "100%", marginTop: ".6rem", minHeight: 46 }}
              onClick={signOut}
            >
              <LogOut className="ico" aria-hidden /> Sign out
            </button>
          </div>
        </>
      ) : null}
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
        {disabledReason ? <span className="muted" style={{ fontSize: ".8rem" }}>{disabledReason}</span> : null}
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
          <span className="muted" style={{ fontSize: ".82rem" }}>{question}</span>
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
      {outcome ? <span className="muted" role="status" style={{ fontSize: ".82rem" }}>{outcome}</span> : null}
    </span>
  );
}
