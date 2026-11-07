import { api, type ApiResult, type AutomationState } from "@/lib/api";
import { invalidate } from "@/lib/use-api";
import { outcomeOf } from "./plain";

/**
 * Start, Pause, Resume and Stop — one implementation, shared by the dashboard
 * and the rule page.
 *
 * WHAT IT GUARANTEES, AND WHY EACH THING IS HERE
 *
 * 1. THE AUTOMATION READ IS RELOADED STRAIGHT AFTER THE POST and its answer is
 *    checked against what the action should have produced. Leaving it to the
 *    20-second poll meant a Stop that worked could sit under a RUNNING chip for
 *    most of half a minute — and a Stop that did not take effect looked exactly
 *    the same.
 * 2. THE SERVER'S SENTENCE IS RETURNED VERBATIM (`outcomeOf` formats the
 *    server's own fields and invents nothing). For Stop that sentence is the
 *    one saying open positions are NOT closed.
 * 3. AN ERROR IS ITS CODE AND ITS MESSAGE, as the API sent them.
 * 4. A MISMATCH IS AN ERROR. If the POST succeeded and the next read still
 *    shows the old state — or cannot be made — the result says so. It never
 *    lets a stale RUNNING read as though the action had worked.
 *
 * `reload` is the caller's own read of `automation`; it must resolve to that
 * read's answer (see `useRead`). Other readers of the endpoint (the shell's
 * status strip) are reloaded through `invalidate`.
 */
export type ControlAction = "start" | "pause" | "resume" | "stop";
export type ControlResult = { action: ControlAction; ok: boolean; text: string };

const EXPECTED: Record<ControlAction, AutomationState["state"]> = {
  start: "running", resume: "running", pause: "paused", stop: "stopped",
};

export async function runAutomationControl(
  action: ControlAction,
  opts: {
    ruleDocId?: string;
    reload: () => Promise<ApiResult<AutomationState> | undefined>;
  },
): Promise<ControlResult> {
  const body = action === "start" && opts.ruleDocId
    ? { ruleDocId: opts.ruleDocId } : undefined;
  const r = await api<AutomationState>(`automation/${action}`, { method: "POST", body });

  // Every mounted reader of these endpoints, not only the caller's copy. The
  // call reaches the caller's own read too; the `reload` below supersedes it
  // and is the one that returns an answer.
  invalidate("automation", "automation/why", "journal?limit=8", "me", "positions");
  const fresh = await opts.reload();

  if (!r.ok) return { action, ok: false, text: `${r.code}: ${r.message}` };

  const got = fresh?.ok ? fresh.data.state : null;
  if (got !== EXPECTED[action]) {
    return {
      action, ok: false,
      text: `The server accepted “${action}”, but the status read afterwards `
        + (got ? `still says ${got.toUpperCase()}` : "could not be confirmed")
        + `. Press Refresh before doing anything else. ${outcomeOf(r.data)}`,
    };
  }
  return { action, ok: true, text: outcomeOf(r.data) };
}
