/**
 * Where a client can reach a person.
 *
 * ONE CONSTANT, ONE FILE. The owner confirmed this mailbox: the domain
 * registrar forwards it to a mailbox the owner reads. If it is ever set back to
 * null, every screen that says "contact support" points at the Help page.
 */
export const SUPPORT_EMAIL: string | null = "support@apex4traders.com";

/** The Help page, which is where support is reachable from today. */
export const HELP_PATH = "/help";

/** A mailto link when an address has been set, otherwise null. */
export function supportMailto(subject?: string): string | null {
  if (!SUPPORT_EMAIL) return null;
  return `mailto:${SUPPORT_EMAIL}${subject ? `?subject=${encodeURIComponent(subject)}` : ""}`;
}
