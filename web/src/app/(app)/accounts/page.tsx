"use client";
import { useState } from "react";
import { Check, Plug, RefreshCw } from "lucide-react";
import { plainError } from "@/components/app/plain";
import { AccountKinds } from "@/components/app/account-kinds";
import { api, type ApiError, type CtraderStatus } from "@/lib/api";
import { invalidateBrokerViews, useRead, whenSynced } from "@/lib/use-api";
import {
  AccountLimitNotice, ErrorNotice, MoreAccountsSection, Spinner, StatusPill,
} from "@/components/app/state";

export default function AccountsPage() {
  const status = useRead<CtraderStatus>("ctrader/status", 60_000);
  const [err, setErr] = useState<string | null>(null);
  // Kept separately from `err`: the account-limit refusal is the one case with
  // something to DO about it, and it needs a link and a disclosure rather than
  // a line of red text. Cleared on every attempt so a stale offer cannot sit
  // under a later, unrelated error.
  const [limit, setLimit] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function select(ctid: number | string) {
    setBusy(String(ctid)); setErr(null); setLimit(null);
    const r = await api("ctrader/select", { method: "POST", body: { ctid } });
    setBusy(null);
    if (!r.ok) {
      if (r.code === "ACCOUNT_LIMIT") return setLimit(r);
      return setErr(plainError(r));
    }
    invalidateBrokerViews();
  }

  async function disconnect() {
    setBusy("disconnect"); setErr(null); setLimit(null);
    const r = await api("ctrader/disconnect", { method: "POST" });
    setBusy(null);
    if (!r.ok) return setErr(plainError(r));
    invalidateBrokerViews();
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

      {limit ? <AccountLimitNotice error={limit} /> : null}

      {data?.connected && data.needsReconnect ? (
        <div className="notice notice-warn" role="alert">
          <p style={{ fontWeight: 600 }}>Reconnect cTrader</p>
          <p className="muted">The broker rejected the saved authorisation. Reconnect before reading account data.</p>
          <a className="btn btn-sm" href="/connect">Reconnect cTrader</a>
        </div>
      ) : null}

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
              {data.accounts.length === 0 ? (
                <p>Connected, but cTrader returned no accounts.</p>
              ) : null}
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

            <AccountKinds />

            <MoreAccountsSection plan={data.accountPlan} />

            {/* The list above is whatever cTrader's own authorisation covers.
                An account that was not ticked on cTrader's screen is not in
                it, and nothing here can add it: only a new authorisation can.
                So the way to bring a missing demo or live account in is
                offered here, in the place where its absence is noticed. */}
            <section className="card" aria-labelledby="refresh-accounts">
              <div className="card-head"><h2 id="refresh-accounts">Switch or add accounts</h2></div>
              <p className="muted" style={{ fontSize: ".85rem" }}>
                {data.accounts.filter((a) => a.mode === "demo").length} demo
                {" · "}
                {data.accounts.filter((a) => a.mode === "live").length} live.
                {" "}These come from your cTrader authorisation. If a demo or
                live account is missing, sign in to cTrader again and tick
                every account you want here.
              </p>
              <a className="btn" style={{ marginTop: ".7rem" }} href="/connect">
                <Plug className="ico" aria-hidden /> Refresh accounts with cTrader
              </a>
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
