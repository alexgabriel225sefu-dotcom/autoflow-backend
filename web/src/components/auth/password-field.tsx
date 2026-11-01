"use client";
import { useId, useRef, useState } from "react";
import styles from "./auth-shell.module.css";

/**
 * Password input with a show/hide toggle. Pattern after "Modern Animated Sign
 * In" (21st.dev, arunachalam), written natively for this codebase.
 *
 * The toggle sits inside the label for layout, so the input is named by the
 * label text alone (aria-labelledby) and not "Password Show password". The
 * button never takes focus from the field on a mouse or touch press.
 */
export function PasswordField({
  label, value, onChange, autoComplete, minLength,
}: {
  label: string; value: string; onChange: (v: string) => void;
  autoComplete: "current-password" | "new-password"; minLength?: number;
}) {
  const [shown, setShown] = useState(false);
  const ref = useRef<HTMLInputElement>(null);
  const labelId = useId();
  return (
    <label className={`field ${styles.field}`}>
      <span id={labelId}>{label}</span>
      <div className={styles.row}>
        <input ref={ref} type={shown ? "text" : "password"} required minLength={minLength}
               value={value} autoComplete={autoComplete} aria-labelledby={labelId}
               onChange={(e) => onChange(e.target.value)} />
        <button type="button" className={styles.toggle} aria-pressed={shown}
                aria-label={shown ? "Hide password" : "Show password"}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => setShown((s) => !s)}>
          <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor"
               strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Z" />
            <circle cx="12" cy="12" r="3" />
            {shown ? <path d="M4 20 20 4" /> : null}
          </svg>
        </button>
      </div>
    </label>
  );
}
