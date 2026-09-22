"use client";
import type { ConditionParam, ConditionSpec } from "@/lib/api";

/**
 * One condition's form, generated from the backend's own spec.
 *
 * Nothing here has a hard-coded list of conditions or parameters. The choices
 * in every dropdown come from /api/v1/conditions, which is generated from the
 * evaluator's registry — so the builder cannot offer a condition the
 * evaluator does not implement, and cannot offer a parameter value the
 * evaluator would refuse. A duplicated list here would drift the first time
 * somebody added a condition, and the drift would show up as a rule that
 * saves and then refuses to run.
 */
export type ConditionValue = { id: string; params: Record<string, unknown> };

export function defaultsFor(spec: ConditionSpec): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [name, p] of Object.entries(spec.params)) {
    if (p.default !== null && p.default !== undefined) out[name] = p.default;
  }
  return out;
}

function Field({
  name, param, value, onChange,
}: {
  name: string; param: ConditionParam; value: unknown;
  onChange: (v: unknown) => void;
}) {
  if (param.choices?.length) {
    return (
      <label className="field">
        <span>{name}</span>
        <select value={String(value ?? "")} onChange={(e) => onChange(e.target.value)}>
          {param.choices.map((c) => <option key={String(c)} value={String(c)}>{String(c)}</option>)}
        </select>
      </label>
    );
  }
  if (param.type === "int" || param.type === "float") {
    return (
      <label className="field">
        <span>
          {name}
          {param.min !== null || param.max !== null ? (
            <> <span className="muted">({param.min ?? "−∞"}–{param.max ?? "∞"})</span></>
          ) : null}
        </span>
        <input
          type="number"
          step={param.type === "int" ? 1 : "any"}
          min={param.min ?? undefined}
          max={param.max ?? undefined}
          value={value === undefined || value === null ? "" : String(value)}
          onChange={(e) => {
            const raw = e.target.value;
            if (raw === "") return onChange(undefined);
            // Parsed to the type the backend declared. Sending "14" where an
            // int is expected is refused there, and refusing it here means
            // the client sees it while they are still looking at the field.
            const n = param.type === "int" ? parseInt(raw, 10) : parseFloat(raw);
            onChange(Number.isNaN(n) ? undefined : n);
          }}
        />
      </label>
    );
  }
  if (param.type === "list") {
    return (
      <label className="field">
        <span>{name} <span className="muted">(comma separated)</span></span>
        <input
          value={Array.isArray(value) ? value.join(",") : ""}
          onChange={(e) => onChange(
            e.target.value.split(",").map((s) => s.trim()).filter(Boolean)
              .map((s) => (/^\d+$/.test(s) ? Number(s) : s)),
          )}
        />
      </label>
    );
  }
  return (
    <label className="field">
      <span>{name}</span>
      <input value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} />
    </label>
  );
}

export function ConditionEditor({
  specs, value, onChange, onRemove,
}: {
  specs: Record<string, ConditionSpec>;
  value: ConditionValue;
  onChange: (v: ConditionValue) => void;
  onRemove: () => void;
}) {
  const spec = specs[value.id];
  return (
    <div className="notice">
      <div className="card-head">
        <label className="field" style={{ margin: 0, flex: 1 }}>
          <span>Condition</span>
          <select
            value={value.id}
            onChange={(e) => {
              const next = specs[e.target.value];
              // Parameters are reset to the NEW condition's defaults. Keeping
              // the old ones would send names the new condition does not
              // accept, and the backend refuses unknown parameter names
              // rather than ignoring them.
              onChange({ id: e.target.value, params: next ? defaultsFor(next) : {} });
            }}
          >
            {Object.keys(specs).sort().map((id) => (
              <option key={id} value={id}>{id}</option>
            ))}
          </select>
        </label>
        <button className="btn btn-ghost" onClick={onRemove} aria-label="Remove condition">
          Remove
        </button>
      </div>
      {spec ? <p className="muted">{spec.doc}</p> : (
        <p className="notice notice-error">
          This condition is not one the engine implements.
        </p>
      )}
      {spec ? (
        <div className="grid grid-2">
          {Object.entries(spec.params).map(([name, p]) => (
            <Field
              key={name} name={name} param={p} value={value.params[name]}
              onChange={(v) => {
                const params = { ...value.params };
                if (v === undefined) delete params[name];
                else params[name] = v;
                onChange({ ...value, params });
              }}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}
