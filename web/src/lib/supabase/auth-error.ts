/** Translate provider errors into an action a client can take. */
export function authErrorMessage(message: string, context: "signup" | "signin" | "resend" | "reset" = "signin") {
  const raw = String(message || "").trim();
  const lower = raw.toLowerCase();
  const wait = lower.match(/(?:after|in)\s+(\d+)\s*seconds?/);
  if (wait) {
    return `Please wait ${wait[1]} seconds before trying again.`;
  }
  if (lower.includes("rate limit") || lower.includes("too many requests")) {
    return "Too many requests. Please wait a moment before trying again.";
  }
  if (lower.includes("email not confirmed") || lower.includes("email_not_confirmed")) {
    return "This email is not confirmed yet. Check your inbox or request another confirmation link.";
  }
  if (lower.includes("already registered") || lower.includes("already exists") || lower.includes("user already")) {
    return "An account may already use this email. Try signing in or reset your password.";
  }
  if (context === "signin" && (lower.includes("invalid login") || lower.includes("invalid credentials"))) {
    return "Email or password is incorrect. If you have not confirmed your email, check your inbox first.";
  }
  if (!raw) return "Something went wrong. Please try again.";
  return raw;
}
