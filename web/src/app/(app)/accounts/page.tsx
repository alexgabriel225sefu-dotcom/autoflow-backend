"use client";
import { useState } from "react";
import { Check, Plug, RefreshCw } from "lucide-react";
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

  const data = status.result?.ok ? status.result.data : null;

  return (
    <main>
      <div className="page-head">
        <div>
          <h1>Accounts</h1>
          <span className="sub">Last synced {whenSynced(status.lastSync)}</span>
        </div>
        <button className="btn btn-ghost btn-sm" onClick={status.reload} disabled={status.loading}>
          <RefreshCw className="ico" aria-hidden /> Refresh
        </button>
      </div>

      {status.loading && !status.result ? <Spinner /> : null}
      {status.result && !status.result.ok
        ? <ErrorNotice error={status.result} onRetry={status.reload} /> : null}
      {err ? <div className="notice notice-error" role="alert">{err}</div> : null}

      {data ? (
        data.connected ? (
          <>
            <section className="card">
              <div className="card-head">
                <h2>Connected accounts</h2>
                <span className="dim" style={{ fontSize: ".75rem" }}>
                  The selected account is the one every read and every order uses.
                </span>
              </div>
              <div className="records">
                {data.accounts.map((a) => {
                  const selected = String(data.selected?.ctid) === String(a.ctid);
                  const blocked = a.mode === "live" && !data.liveAllowed;
                  return (
                    <div
                      className="record" key={String(a.ctid)}
                      style={selected ? { borderColor: "var(--a4t-accent-dim)" } : undefined}
                    >
                      <div className="record-head">
                        <span className="record-title mono">#{a.ctid}</span>
                        <span className="btn-row">
                          <StatusPill mode={a.mode} />
                          {selected ? (
                            <span className="pill pill-accent">
                              <Check style={{ width: 11, height: 11 }} aria-hidden /> Selected
                            </span>
                          ) : null}
                        </span>
                      </div>
                      {a.label ? <p className="muted" style={{ fontSize: ".82rem" }}>{a.label}</p> : null}
                      {blocked ? (
                        /* No button that could start trading on an account
                           this environment refuses. */
                        <p className="dim" style={{ fontSize: ".8rem", marginTop: ".4rem" }}>
                          Live accounts are not available here.
                        </p>
                      ) : selected ? null : (
                        <button className="btn btn-ghost btn-sm" style={{ marginTop: ".5rem" }}
                                disabled={busy === String(a.ctid)}
                                onClick={() => select(a.ctid)}>
                          {busy === String(a.ctid) ? "Selecting…" : "Select this account"}
                        </button>
                      )}
                    </div>
                  );
                })}
              </div>
            </section>

            <section className="card">
              <div className="card-head"><h2>Disconnect</h2></div>
              <p className="muted" style={{ fontSize: ".85rem" }}>
                Removes the tokens from Apex4Traders. It does not revoke access
                inside cTrader — do that there too if you want it withdrawn.
              </p>
              <button className="btn btn-danger" style={{ marginTop: ".7rem" }}
                      onClick={disconnect} disabled={busy === "disconnect"}>
                {busy === "disconnect" ? "Disconnecting…" : "Disconnect cTrader"}
              </button>
            </section>
          </>
        ) : (
          <section className="card">
            <p className="empty">No cTrader account is connected.</p>
            <div style={{ textAlign: "center" }}>
              <a className="btn" href="/connect">
                <Plug className="ico" aria-hidden /> Connect cTrader
              </a>
            </div>
          </section>
        )
      ) : null}
    </main>
  );
}
