"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { LogOut, MoreHorizontal, User, X } from "lucide-react";
import { BrandLockup, BrandMark } from "@/components/brand/logo";
import { createClient } from "@/lib/supabase/client";
import type { AutomationState, CtraderStatus, Me, NotificationPage } from "@/lib/api";
import { useRead } from "@/lib/use-api";
import { isActive, NAV, PRIMARY, SECONDARY, titleFor } from "./nav";
import { StatusBar } from "./status-bar";
import { AppearanceControls } from "./appearance-controls";
import type { NavItem } from "./nav";

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
  const [drawer, setDrawer] = useState(false);
  const [menu, setMenu] = useState(false);
  const [signOutError, setSignOutError] = useState<string | null>(null);

  // One fetch of each, shared with the status strip, rather than every page
  // asking again for the same three facts.
  const me = useRead<Me>("me", 120_000);
  const ct = useRead<CtraderStatus>("accounts", 60_000);
  const auto = useRead<AutomationState>("automation", 30_000);
  const notes = useRead<NotificationPage>("notifications?limit=1", 60_000);

  // Derived from the read, not copied into state by an effect: a second
  // copy can only ever be the same value or a stale one.
  const unread = notes.result?.ok ? notes.result.data.unread : 0;

  // Closed where the click happens rather than in an effect on `path`: the
  // effect version fires a synchronous setState during render commit, and a
  // navigation that lands on the same route would not fire it at all.
  const close = () => { setDrawer(false); setMenu(false); };

  useEffect(() => {
    if (!drawer && !menu) return;
    const esc = (e: KeyboardEvent) => {
      if (e.key === "Escape") { setDrawer(false); setMenu(false); }
    };
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [drawer, menu]);

  async function signOut() {
    setSignOutError(null);
    try {
      const result = await createClient().auth.signOut();
      if (result?.error) {
        setSignOutError(result.error.message || "Sign out failed.");
        return;
      }
    } catch (e) {
      setSignOutError(e instanceof Error ? e.message : "Sign out failed.");
      return;
    }
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
        <Link className="side-brand" href="/dashboard" aria-label="Apex4Traders — dashboard">
          <BrandLockup size={22} />
        </Link>

        <SideGroup label="Operations" items={NAV.slice(0, 6)} path={path} badge={badge} first />
        <SideGroup label="Account" items={NAV.slice(6)} path={path} badge={badge} />

        <div className="side-foot">
          <AppearanceMenu />
          <button className="side-out" onClick={signOut}>
            <LogOut className="ico" aria-hidden />
            <span>Sign out</span>
          </button>
        </div>
      </aside>

      <div className="main-col">
        <header className="topbar">
          <Link className="topbar-brand" href="/dashboard" aria-label="Apex4Traders — dashboard">
            <BrandLockup size={18} />
          </Link>
          <span className="topbar-title">{titleFor(path)}</span>
          <span className="topbar-spacer" />

          {/* The user menu. Present on every screen, so signing out and
              reaching settings never depend on which page you are on. */}
          <div style={{ position: "relative" }}>
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => setMenu((v) => !v)}
              aria-expanded={menu}
              aria-haspopup="menu"
            >
              <User className="ico" aria-hidden />
              <span className="only-desktop" style={{ maxWidth: 150, overflow: "hidden", textOverflow: "ellipsis" }}>
                {me.result?.ok ? me.result.data.user.email ?? "Account" : "Account"}
              </span>
            </button>
            {menu ? (
              <div role="menu" className="usermenu">
                <Link role="menuitem" href="/settings" onClick={close}>Settings</Link>
                <Link role="menuitem" href="/license" onClick={close}>Licence</Link>
                <Link role="menuitem" href="/accounts" onClick={close}>cTrader accounts</Link>
                <button role="menuitem" onClick={signOut}>
                  <LogOut className="ico" aria-hidden /> Sign out
                </button>
              </div>
            ) : null}
          </div>
          {/* Sign out lives in the sidebar on desktop and in the drawer on a
              phone, so the top bar does not carry a second copy of it. */}
        </header>

        <StatusBar me={me.result} ct={ct.result} auto={auto.result} />

        {me.result?.ok && me.result.data.user.emailVerified === false ? (
          <div className="notice notice-warn" role="status">
            Connecting cTrader and activating a rule are refused until the address is confirmed.{" "}
            <Link href="/settings">Review it in settings</Link>
          </div>
        ) : null}
        {signOutError ? <div className="notice notice-error" role="alert">{signOutError}</div> : null}

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
                <Link key={href} href={href} data-active={isActive(path, href)} onClick={close}>
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
 * One group of sidebar destinations, drawn as a timeline.
 *
 * A rail runs down the left with a node per destination. The node of the page
 * you are on is filled, and the rail fills from the top down to whichever node
 * you are pointing at (or the current one, when you are not pointing at
 * anything), so moving the pointer reads as travelling along the line. A single
 * highlight slides between rows instead of each row flashing on its own.
 *
 * Rows are one fixed height, which is what lets the highlight and the fill be
 * positioned from an index in CSS with no measuring. Keyboard focus drives the
 * same state as the pointer, so the animation is not mouse-only. With
 * `prefers-reduced-motion` the CSS drops every transition and the states
 * simply change.
 */
function SideGroup({
  label, items, path, badge, first,
}: {
  label: string;
  items: NavItem[];
  path: string;
  badge: (href: string) => React.ReactNode;
  first?: boolean;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const active = items.findIndex((n) => isActive(path, n.href));
  const lit = hover ?? active;
  return (
    <div className="side-section">
      <p className="label-xs side-group" style={first ? { marginTop: 0 } : undefined}>{label}</p>
      <div
        className="side-list"
        style={{ "--hi": hover ?? 0, "--ri": lit } as React.CSSProperties}
        data-hover={hover !== null}
        onPointerLeave={() => setHover(null)}
        onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget)) setHover(null); }}
      >
        <span className="side-rail" aria-hidden><i /></span>
        <span className="side-hl" aria-hidden />
        <ul>
        {items.map(({ href, label: text, icon: Icon }, i) => (
          <li key={href} data-lit={lit >= 0 && i <= lit}>
            <Link
              className="side-link"
              href={href}
              data-active={i === active}
              aria-current={i === active ? "page" : undefined}
              onPointerEnter={() => setHover(i)}
              onFocus={() => setHover(i)}
            >
              <span className="side-node" aria-hidden />
              <Icon className="ico" aria-hidden />
              <span style={{ flex: 1 }}>{text}</span>
              {badge(href)}
            </Link>
          </li>
        ))}
        </ul>
      </div>
    </div>
  );
}

/**
 * The logo as a button: opens the appearance popover (theme and accent).
 * The mark in the button is drawn in the current accent, so it previews the
 * choice it offers.
 */
function AppearanceMenu() {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("pointerdown", away);
    window.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("pointerdown", away);
      window.removeEventListener("keydown", esc);
    };
  }, [open]);

  return (
    <div className="appearance-menu" ref={box}>
      <button
        type="button"
        className="side-out side-appearance"
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => setOpen((v) => !v)}
      >
        <BrandMark size={20} />
        <span>Appearance</span>
      </button>
      {open ? (
        <div className="appearance-pop" role="dialog" aria-label="Appearance">
          <AppearanceControls />
        </div>
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
