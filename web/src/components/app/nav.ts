/**
 * The navigation model, declared once.
 *
 * The sidebar, the mobile bottom bar and the drawer all read this list. They
 * used to be one horizontally scrolling strip, which at 390px showed one
 * destination out of eight with no affordance for the other seven — so the
 * split below is the whole point: `primary` is what fits on a phone, and
 * everything else has to be reachable from the drawer rather than assumed
 * discoverable.
 */
import {
  BarChart3, Bell, BookOpen, Crosshair, LayoutDashboard, ListChecks, Receipt, Settings,
  CircleHelp, ShieldCheck, TrendingUp, Wallet, type LucideIcon,
} from "lucide-react";

export type NavItem = {
  href: string;
  label: string;
  icon: LucideIcon;
  /** Shown in the mobile bottom bar. The rest live in the drawer. */
  primary?: boolean;
  /** Which sidebar group the item sits in. */
  group: "operations" | "account" | "more";
  /** A short caveat shown beside the label for a destination that exists but
   *  cannot be used yet, so nobody has to click to find that out. */
  note?: string;
};

export const NAV: NavItem[] = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard, primary: true, group: "operations" },
  // The front door: pick an instrument and a strategy, set the risk, start.
  { href: "/trade", label: "Trade", icon: Crosshair, primary: true, group: "operations" },
  // Rules is the builder for people who want their own conditions, so it
  // leaves the phone's bottom bar (four slots) for Trade and stays in the drawer.
  { href: "/rules", label: "Rules", icon: ListChecks, group: "operations" },
  { href: "/positions", label: "Positions", icon: TrendingUp, primary: true, group: "operations" },
  { href: "/orders", label: "Orders", icon: Receipt, group: "operations" },
  { href: "/performance", label: "Performance", icon: BarChart3, group: "operations" },
  { href: "/journal", label: "Journal", icon: BookOpen, primary: true, group: "account" },
  { href: "/notifications", label: "Alerts", icon: Bell, group: "account" },
  { href: "/accounts", label: "Accounts", icon: Wallet, group: "account" },
  { href: "/settings", label: "Settings", icon: Settings, group: "account" },
  { href: "/help", label: "Help", icon: CircleHelp, group: "more" },
  // The route stays and its gating is untouched; it just does not sit among the
  // working destinations, because live trading is not available in this release.
  {
    href: "/live", label: "Live access", icon: ShieldCheck, group: "more",
    note: "Not available in this release",
  },
];

export const PRIMARY = NAV.filter((n) => n.primary);
/** Everything the bottom bar has no room for. Nothing may be dropped. */
export const SECONDARY = NAV.filter((n) => !n.primary);

export function isActive(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}

/** The page title for a path, so the top bar always says where you are. */
export function titleFor(pathname: string): string {
  const hit = [...NAV].sort((a, b) => b.href.length - a.href.length)
    .find((n) => isActive(pathname, n.href));
  if (hit) return hit.label;
  if (pathname.startsWith("/connect")) return "Connect cTrader";
  if (pathname.startsWith("/license")) return "Licence";
  return "Apex4Traders";
}
