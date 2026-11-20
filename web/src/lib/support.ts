/**
 * Where a client can reach a person.
 *
 * ONE CONSTANT, ONE FILE. The owner has not supplied a support address yet, and
 * a made-up one would send real clients' mail into nothing. Until it is set,
 * every screen that says "contact support" points at the Help page instead.
 *
 * TODO(owner): set SUPPORT_EMAIL below to a mailbox the owner confirms they
 * read. Nothing else needs to change.
 */
export const SUPPORT_EMAIL: string | null = null;

/** The Help page, which is where support is reachable from today. */
export const HELP_PATH = "/help";

/** A mailto link when an address has been set, otherwise null. */
export function supportMailto(subject?: string): string | null {
  if (!SUPPORT_EMAIL) return null;
  return `mailto:${SUPPORT_EMAIL}${subject ? `?subject=${encodeURIComponent(subject)}` : ""}`;
}
