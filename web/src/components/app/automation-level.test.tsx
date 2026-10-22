/**
 * Choosing who acts on a setup.
 *
 * A control that says "Signals Only" and saves nothing would place orders for
 * a client who asked to be told and nothing more. So these tests follow the
 * choice all the way: the control, the document it writes, the document it
 * reads back, and the sentence the rule summary says about it.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { BLANK, RuleForm, fromDoc, toDoc, type Draft } from "./rule-form";
import { AUTOMATION_LEVELS, plainLevel } from "./plain";

const mount = (draft: Draft, set = () => {}) =>
  render(<RuleForm draft={draft} set={set} specs={{}} step="basics" />);

describe("the level control", () => {
  it("offers exactly the three levels the server services", () => {
    const py = readFileSync(
      join(process.cwd(), "..", "apex-forex-bot", "apex", "platform", "ruledoc.py"),
      "utf8",
    );
    const m = py.match(/AUTOMATION_LEVELS = \(([^)]*)\)/);
    expect(m, "ruledoc.AUTOMATION_LEVELS not found").not.toBeNull();
    const server = [...m![1].matchAll(/"([a-z]+)"/g)].map((x) => x[1]).sort();
    expect(AUTOMATION_LEVELS.map((l) => l.id).sort()).toEqual(server);
  });

  it("shows all three and marks the chosen one", () => {
    mount({ ...BLANK, automationLevel: "approval" });
    expect(screen.getByRole("button", { name: "Signals Only" }).getAttribute("aria-pressed")).toBe("false");
    expect(screen.getByRole("button", { name: "Approval Required" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: "Full Automation" }).getAttribute("aria-pressed")).toBe("false");
  });

  it("says what the chosen level does and does not do", () => {
    mount({ ...BLANK, automationLevel: "signals" });
    expect(screen.queryByText(/Places nothing\./)).not.toBeNull();
  });

  it("reports the click as that level's engine id", () => {
    const calls: [string, unknown][] = [];
    mount(BLANK, ((k: string, v: unknown) => { calls.push([k, v]); }) as never);
    fireEvent.click(screen.getByRole("button", { name: "Signals Only" }));
    expect(calls).toContainEqual(["automationLevel", "signals"]);
  });
});

describe("the choice is what is saved and what is read back", () => {
  it.each(["signals", "approval", "full"])("%s survives toDoc → fromDoc", (id) => {
    const doc = toDoc({ ...BLANK, automationLevel: id });
    expect(doc.automationLevel).toBe(id);
    const back = fromDoc(doc as never);
    expect(back.ok && back.draft.automationLevel).toBe(id);
  });

  it("a rule stored before the field existed reads as full", () => {
    const doc = { ...toDoc(BLANK) } as Record<string, unknown>;
    delete doc.automationLevel;
    const back = fromDoc(doc as never);
    expect(back.ok && back.draft.automationLevel).toBe("full");
  });

  it("an unknown level is shown as itself, never as a friendly guess", () => {
    expect(plainLevel("aproval")).toBe("aproval");
    expect(plainLevel("approval")).toBe("Approval Required");
  });
});
