"use client";
import { digestOf } from "@/components/app/route-states";

/**
 * The last resort: the root layout itself failed, so no stylesheet, font or
 * theme is available. Self-contained, with the product's dark palette inline.
 * Plain anchors, not next/link, because the router may be what broke.
 */
export default function GlobalError({ error, retry }: { error: unknown; retry: () => void }) {
  const ref = digestOf(error);
  const button = {
    font: "inherit", cursor: "pointer", padding: ".55rem 1rem", borderRadius: 8,
    border: "1px solid #3a3a42", background: "#17171B", color: "#EDEDF0",
    textDecoration: "none", display: "inline-block",
  } as const;
  return (
    <html lang="en">
      <body style={{
        margin: 0, minHeight: "100vh", display: "grid", placeItems: "center",
        background: "#08080A", color: "#EDEDF0",
        fontFamily: "system-ui, -apple-system, Segoe UI, sans-serif",
      }}>
        <main role="alert" style={{ maxWidth: 440, padding: "1.5rem" }}>
          <h1 style={{ fontSize: "1.3rem" }}>Something went wrong</h1>
          <p style={{ color: "#A0A0AA" }}>
            Apex4Traders could not be shown. Nothing was changed on your account
            or at your broker by this error.
          </p>
          {ref ? <p style={{ color: "#80808A", fontSize: ".8rem" }}>Reference: {ref}</p> : null}
          <p style={{ display: "flex", gap: ".6rem", flexWrap: "wrap" }}>
            <button style={button} onClick={() => retry()}>Try again</button>
            <a style={button} href="/dashboard">Back to the dashboard</a>
          </p>
        </main>
      </body>
    </html>
  );
}
