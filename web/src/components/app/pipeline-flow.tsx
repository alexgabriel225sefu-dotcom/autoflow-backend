/**
 * The automation as a pipeline you can watch: account, rule, Risk Guard,
 * journal. Light moves along the links only while the automation is running,
 * so the picture is the state and never a decoration. Every value is one the
 * dashboard already reads; a read that has not answered shows a dash, and
 * nothing here claims a result.
 */
import { BookOpen, Plug, ShieldCheck, Sparkles } from "lucide-react";
import type { ReactNode } from "react";

export type PipelineProps = {
  /** "#12345 · Demo" or null while unknown. */
  account: string | null;
  accountReady: boolean;
  rule: string | null;
  ruleReady: boolean;
  running: boolean;
  /** Decisions in the journal, or null while unknown. */
  decisions: number | null;
};

function Node({ icon, label, value, ok, delay }: {
  icon: ReactNode; label: string; value: string; ok: boolean; delay: number;
}) {
  return (
    <div className="pfl-node" data-ok={ok ? "true" : "false"} style={{ ["--d" as string]: `${delay}ms` }}>
      <span className="pfl-ico" aria-hidden="true">{icon}</span>
      <span className="pfl-label">{label}</span>
      <strong className="pfl-value">{value}</strong>
    </div>
  );
}

function Link({ on }: { on: boolean }) {
  return (
    <span className="pfl-link" data-on={on ? "true" : "false"} aria-hidden="true">
      <i className="pfl-dot" />
    </span>
  );
}

export function PipelineFlow({ account, accountReady, rule, ruleReady, running, decisions }: PipelineProps) {
  return (
    <section className="pfl" aria-label="How your automation flows" data-running={running ? "true" : "false"}>
      <header className="pfl-head">
        <span className="pfl-title"><Sparkles size={14} aria-hidden /> Your automation, live</span>
        <span className="pfl-state">{running ? "Live" : "Idle"}</span>
      </header>
      <div className="pfl-row">
        <Node icon={<Plug size={16} />} label="Account" value={account ?? "—"} ok={accountReady} delay={0} />
        <Link on={running && accountReady} />
        <Node icon={<Sparkles size={16} />} label="Rule" value={rule ?? "—"} ok={ruleReady} delay={90} />
        <Link on={running && ruleReady} />
        <Node icon={<ShieldCheck size={16} />} label="Risk Guard" value="Checked before every order" ok={true} delay={180} />
        <Link on={running} />
        <Node
          icon={<BookOpen size={16} />} label="Journal"
          value={decisions === null ? "—" : `${decisions} recent decision${decisions === 1 ? "" : "s"}`}
          ok={decisions !== null} delay={270}
        />
      </div>
    </section>
  );
}
