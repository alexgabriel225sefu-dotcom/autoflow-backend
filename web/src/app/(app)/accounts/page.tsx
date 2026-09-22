"use client";
import { useState } from "react";
import { api, type CtraderStatus } from "@/lib/api";
import { useRead, whenSynced } from "@/lib/use-api";
import { ErrorNotice, Spinner, StatusPill } from "@/components/app/state";

export default function AccountsPage() {
  const status = useRead<CtraderStatus>("ctrader/status", 60_000);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function select(ctid: number | string) {
    setBusy(String(ctid)); setErr(null);
    const r = await api("ctrader/select", { method: "POST", body: { ctid } });
    setBusy(null);
    if (!r.ok) return setErr(`${r.code}: ${r.message}`);
    void status.reload();
  }

  async function disconnect() {
    setBusy("disconnect"); setErr(null);
    const r = await api("ctrader/disconnect", { method: "POST" });
    setBusy(null);
    if (!r.ok) return setErr(`${r.code}: ${r.message}`);
    void status.reload();
  }

  return (
    <main>
      <div className="card-head">
        <h1>Accounts</h1>
        <span className="muted">Last synced {whenSynced(status.lastSync)}</span>
      </div>
      {status.loading && !status.result ? <Spinner /> : null}
      {status.result && !status.result.ok
        ? <ErrorNotice error={status.result} onRetry={status.reload} /> : null}
      {err ? <div className="notice notice-error" role="alert">{err}</div> : null}

      {status.result?.ok ? (
        status.result.data.connected ? (
          <>
            <section className="card">
              <div className="scroll-x">
                <table className="tbl">
                  <thead><tr><th>Account</th><th>Mode</th><th>Selected</th><th /></tr></thead>
                  <tbody>
                    {status.result.data.accounts.map((a) => {
                      const selected = String(status.result!.ok &&
                        status.result!.data.selected?.ctid) === String(a.ctid);
                      const blocked = a.mode === "live" && !status.result!.ok
                        ? true
                        : a.mode === "live" && status.result!.ok
                          && !status.result!.data.liveAllowed;
                      return (
                        <tr key={String(a.ctid)}>
                          <td className="mono">#{a.ctid}</td>
                          <td><StatusPill mode={a.mode} /></td>
                          <td>{selected ? "Yes" : ""}</td>
                          <td>
                            {blocked ? (
                              /* No button that could start trading on an
                                 account this environment refuses. */
                              <span className="muted">Live accounts are not available here</span>
                            ) : selected ? null : (
                              <button className="btn btn-ghost" disabled={busy === String(a.ctid)}
                                      onClick={() => select(a.ctid)}>
                                {busy === String(a.ctid) ? "Selecting…" : "Select"}
                              </button>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </section>
            <section className="card">
              <h2>Disconnect</h2>
              <p className="muted">
                Removes the tokens from Apex4Traders. It does not revoke access
                inside cTrader — do that there too if you want it withdrawn.
              </p>
              <button className="btn btn-danger" onClick={disconnect} disabled={busy === "disconnect"}>
                {busy === "disconnect" ? "Disconnecting…" : "Disconnect cTrader"}
              </button>
            </section>
          </>
        ) : (
          <section className="card">
            <p className="muted">No cTrader account is connected.</p>
            <a className="btn" href="/connect">Connect cTrader</a>
          </section>
        )
      ) : null}
    </main>
  );
}
