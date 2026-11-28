"use client";
import { useEffect, useState } from "react";
import { Gauge } from "lucide-react";

/**
 * A read the platform refused for a moment, and will ask again by itself.
 *
 * Shown by `ErrorNotice` when a RATE_LIMITED answer carries `retryAt`, which
 * `useRead` sets only when it has actually scheduled the retry. So the
 * countdown is a statement about something that will happen, not a guess: a
 * refusal with no retry behind it keeps the ordinary notice and its button.
 *
 * Plain words on purpose. The reader did nothing wrong and has nothing to do;
 * an error code and "too many requests" would say the opposite.
 */
export function BusyNotice({ retryAt }: { retryAt: number }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [retryAt]);
  const secs = Math.ceil((retryAt - now) / 1000);
  return (
    <div className="notice notice-info" role="status" aria-live="polite">
      <div className="notice-head">
        <Gauge className="ico" aria-hidden
               style={{ width: 12, height: 12, verticalAlign: "-2px", marginRight: 4 }} />
        <strong>Busy</strong>
      </div>
      <p>{secs > 0 ? `Retrying in ${secs} s.` : "Retrying now."}</p>
    </div>
  );
}
