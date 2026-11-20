/** A link to the inbox for the common providers, so nobody has to hunt for it. */
export function inboxLink(email: string): { name: string; href: string } | null {
  const domain = email.split("@")[1]?.trim().toLowerCase() ?? "";
  if (domain === "gmail.com" || domain === "googlemail.com")
    return { name: "Gmail", href: "https://mail.google.com/" };
  if (["outlook.com", "hotmail.com", "live.com", "msn.com"].includes(domain))
    return { name: "Outlook", href: "https://outlook.live.com/mail/" };
  if (domain === "yahoo.com") return { name: "Yahoo Mail", href: "https://mail.yahoo.com/" };
  if (domain === "icloud.com" || domain === "me.com")
    return { name: "iCloud Mail", href: "https://www.icloud.com/mail" };
  return null;
}
