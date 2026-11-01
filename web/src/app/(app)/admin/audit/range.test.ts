import { describe, expect, it } from "vitest";
import { amsterdamIso, auditDetailPaths, auditWindow, DEFAULT_AUDIT_DAYS } from "./range";

describe("audit range", () => {
  it("writes Europe/Amsterdam offsets, including summer time", () => {
    expect(amsterdamIso(Date.parse("2026-01-15T12:00:00Z"))).toBe("2026-01-15T13:00:00+01:00");
    expect(amsterdamIso(Date.parse("2026-07-15T12:00:00Z"))).toBe("2026-07-15T14:00:00+02:00");
  });

  it("defaults the window to fourteen days and always sends both ends", () => {
    const now = Date.parse("2026-11-01T12:00:00Z");
    const window = auditWindow(DEFAULT_AUDIT_DAYS, now);
    expect(Date.parse(window.to) - Date.parse(window.from)).toBe(14 * 86_400_000);
    const paths = auditDetailPaths(424242, DEFAULT_AUDIT_DAYS, now);
    expect(paths.summary).toBe("admin/audit/accounts/424242");
    expect(paths.open).toBe("admin/audit/accounts/424242/open");
    expect(paths.deals.startsWith("admin/audit/accounts/424242/deals?")).toBe(true);
    expect(paths.orders.startsWith("admin/audit/accounts/424242/orders?")).toBe(true);
    const q = new URLSearchParams(paths.deals.split("?")[1]);
    expect(q.get("from")).toBe(window.from);
    expect(q.get("to")).toBe(window.to);
  });
});
