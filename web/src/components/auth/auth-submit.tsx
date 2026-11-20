import styles from "./auth-shell.module.css";

/** Submit button with a visible busy state (spinner + aria-busy); the label text is unchanged. */
export function AuthSubmit({ busy, idle, busyLabel }: { busy: boolean; idle: string; busyLabel: string }) {
  return (
    <button className={`btn btn-lg ${styles.submit}`} type="submit" disabled={busy}
            aria-busy={busy} style={{ width: "100%" }}>
      {busy ? <i className={styles.spinner} aria-hidden="true" /> : null}
      {busy ? busyLabel : idle}
    </button>
  );
}
