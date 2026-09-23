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
  Bell, BookOpen, LayoutDashboard, ListChecks, Receipt, Settings,
  TrendingUp, Wallet, type LucideIcon,
} from "lucide-react";

export type NavItem = {
  href: string;
  label: string;
  icon: LucideIcon;
  /** Shown in the mobile bottom bar. The rest live in the drawer. */
  primary?: boolean;
};

export const NAV: NavItem[] = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard, primary: true },
  { href: "/rules", label: "Rules", icon: ListChecks, primary: true },
  { href: "/positions", label: "Positions", icon: TrendingUp, primary: true },
  { href: "/orders", label: "Orders", icon: Receipt },
  { href: "/journal", label: "Journal", icon: BookOpen, primary: true },
  { href: "/notifications", label: "Alerts", icon: Bell },
  { href: "/accounts", label: "Accounts", icon: Wallet },
  { href: "/settings", label: "Settings", icon: Settings },
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
