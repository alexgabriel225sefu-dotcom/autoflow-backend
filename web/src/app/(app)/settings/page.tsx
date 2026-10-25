"use client";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { useRead } from "@/lib/use-api";
import { ErrorNotice, LicencePill, Spinner } from "@/components/app/state";
import { BrandMark } from "@/components/brand/logo";
import { Check, Moon, Sun } from "lucide-react";
import type { CtraderStatus, Me } from "@/lib/api";

type ThemeChoice = "dark" | "light";
type AccentChoice = "cyan" | "blue" | "violet";

export default function SettingsPage() {
  const me = useRead<Me>("me");
  const ct = useRead<CtraderStatus>("ctrader/status");
  const router = useRouter();
  const [theme, setTheme] = useState<ThemeChoice>("light");
  const [accent, setAccent] = useState<AccentChoice>("blue");

  useEffect(() => {
    const storedTheme = window.localStorage.getItem("a4t-theme");
    const storedAccent = window.localStorage.getItem("a4t-accent");
    if (storedTheme === "dark" || storedTheme === "light") setTheme(storedTheme);
    if (storedAccent === "cyan" || storedAccent === "blue" || storedAccent === "violet") setAccent(storedAccent);
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.dataset.accent = accent;
    window.localStorage.setItem("a4t-theme", theme);
    window.localStorage.setItem("a4t-accent", accent);
  }, [accent, theme]);

  return (
    <main>
      <div className="page-head">
        <div>
          <h1>Settings</h1>
          <span className="sub">Your account, your broker link and your session.</span>
        </div>
      </div>
      {me.loading && !me.result ? <Spinner /> : null}
      {me.result && !me.result.ok ? <ErrorNotice error={me.result} onRetry={me.reload} /> : null}
      {me.result?.ok ? (
        <section className="card">
          <div className="card-head"><h2>Account</h2></div>
          <table className="tbl tbl-kv">
            <tbody>
              <tr><th>Email</th><td>{me.result.data.user.email}</td></tr>
              <tr><th>Confirmed</th><td>{me.result.data.user.emailVerified ? "Yes" : "No"}</td></tr>
              <tr><th>Licence</th><td><LicencePill state={me.result.data.licence.state} /></td></tr>
              {/* The Supabase user id is shown because it is the id every
                  record here is filed under, and support questions are
                  unanswerable without it. It is not a secret. */}
              <tr><th>User ID</th><td className="mono">{me.result.data.user.userId}</td></tr>
            </tbody>
          </table>
        </section>
      ) : null}

      <section className="card appearance-card">
        <div className="card-head"><h2>Appearance</h2><BrandMark size={28} title="Apex4Traders" /></div>
        <p className="muted appearance-copy">Set the workspace tone. Your accent applies to the logo, navigation and active controls; trading gains and losses keep their own meaning.</p>
        <div className="appearance-group">
          <span className="label-xs">Theme</span>
          <div className="appearance-toggle" role="group" aria-label="Theme">
            {(["dark", "light"] as const).map((value) => (
              <button key={value} type="button" aria-pressed={theme === value} onClick={() => setTheme(value)}>
                {value === "dark" ? <Moon size={16} aria-hidden /> : <Sun size={16} aria-hidden />}
                {value === "dark" ? "Black" : "Light"}
              </button>
            ))}
          </div>
        </div>
        <div className="appearance-group">
          <span className="label-xs">Accent</span>
          <div className="accent-swatches" role="group" aria-label="Accent colour">
            {(["cyan", "blue", "violet"] as const).map((value) => (
              <button key={value} className={`accent-swatch accent-${value}`} type="button" aria-label={`${value} accent`} aria-pressed={accent === value} onClick={() => setAccent(value)}>
                {accent === value ? <Check size={18} aria-hidden /> : null}
              </button>
            ))}
          </div>
        </div>
      </section>

      <section className="card">
        <div className="card-head"><h2>Broker</h2></div>
        {ct.result?.ok ? (
          ct.result.data.connected
            ? <p style={{ fontSize: ".88rem" }}>Connected · <a href="/accounts">manage accounts</a></p>
            : <p className="muted" style={{ fontSize: ".88rem" }}>Not connected · <a href="/connect">connect cTrader</a></p>
        ) : <Spinner />}
      </section>

      <section className="card">
        <div className="card-head"><h2>Password</h2></div>
        <a className="btn btn-ghost" href="/auth/reset">Send a reset link</a>
      </section>

      <section className="card">
        <div className="card-head"><h2>Session</h2></div>
        <button className="btn btn-danger" onClick={async () => {
          await createClient().auth.signOut();
          router.push("/login");
          router.refresh();
        }}>Sign out</button>
      </section>
    </main>
  );
}
