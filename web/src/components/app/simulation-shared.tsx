"use client";

import { RefreshCw } from "lucide-react";
import { useState } from "react";
import type { ApiResult, CandlesRead, CtraderStatus } from "@/lib/api";
import { useRead } from "@/lib/use-api";
import { ErrorNotice, Spinner } from "@/components/app/state";

export function SimulationHead({ title, detail, reload, loading }: {
  title: string;
  detail: string;
  reload?: () => unknown;
  loading?: boolean;
}) {
  return (
    <div className="page-head">
      <div><h1>{title}</h1><span className="sub">{detail}</span></div>
      {reload ? (
        <button className="btn btn-ghost btn-sm" onClick={() => void reload()} disabled={loading}>
          <RefreshCw className="ico" aria-hidden /> Refresh
        </button>
      ) : null}
    </div>
  );
}

export function SimulationFailure({ result, retry }: {
  result: ApiResult<unknown> | null;
  retry?: () => unknown;
}) {
  return result && !result.ok ? (
    <div><p className="muted">Could not be read.</p><ErrorNotice error={result} onRetry={retry} /></div>
  ) : null;
}

export function CandleReadStatus({ data, empty }: { data: CandlesRead | null; empty: string }) {
  if (!data) return null;
  if (data.status === "unavailable" || data.status === "reauth_required" || data.status === "not_connected") {
    return (
      <div className="notice notice-error" role="alert">
        <strong>Market data could not be read</strong>
        <p className="muted">{data.reason ?? "The broker did not answer."}</p>
      </div>
    );
  }
  if (!data.candles?.length) return <p className="empty">{empty}</p>;
  return null;
}

export function useCandleRead(symbol: string, timeframe: string, days: number) {
  const accounts = useRead<CtraderStatus>("accounts", 60_000);
  const ctid = accounts.result?.ok ? String(accounts.result.data.selected?.ctid ?? "") : "";
  const [openedAt] = useStateOnce();
  const to = openedAt - days * 86400;
  const path = ctid && symbol && timeframe
    ? `accounts/${encodeURIComponent(ctid)}/candles?symbol=${encodeURIComponent(symbol)}&timeframe=${encodeURIComponent(timeframe)}&limit=500&to=${to}`
    : null;
  const candles = useRead<CandlesRead>(path, 0);
  return { accounts, candles, ctid };
}

function useStateOnce() {
  // Kept as a tiny hook so every historical read uses one stable window start.
  const [value] = useState(() => Math.floor(Date.now() / 1000));
  return [value] as const;
}

export function AccountHint({ accounts }: { accounts: ReturnType<typeof useRead<CtraderStatus>> }) {
  const d = accounts.result?.ok ? accounts.result.data : null;
  if (accounts.loading && !accounts.result) return <Spinner label="Checking connected accounts" />;
  if (accounts.result && !accounts.result.ok) return <SimulationFailure result={accounts.result} retry={accounts.reload} />;
  if (!d || !d.connected || !d.accounts?.length) return <p className="empty">No connected account is available for this read.</p>;
  return <p className="muted">Using account {String(d.selected?.ctid ?? d.accounts[0]?.ctid)} · {d.selected?.mode ?? d.accounts[0]?.mode}</p>;
}
