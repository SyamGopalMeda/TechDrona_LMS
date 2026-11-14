/**
 * Forms (components.js form / formDialog): field primitives with the portal look, plus a spec-driven form and
 * form dialog with the old behaviour, so forms.js / college-form.js port field-for-field.
 *
 * Field spec: {name, label, type: text|number|date|tel|email|password|url|textarea|select|multiselect|checkbox,
 *              required?, options?, value?, help?, placeholder?, min?, max?, step?, rows?, full?, disabled?, maxLength?}
 * Values: empty → null; numbers → Number; select → the option's value (any type); multiselect → value[]; checkbox → bool.
 * A thrown PortalApiError's `fields` show under the matching inputs; anything else shows above the form.
 *
 * Form dialog (the old imperative formDialog() is a component now):
 *   <FormDialog open={open} title="Set target" fields={FIELDS} values={row}
 *     onSubmit={(v, { idempotencyKey }) => portalApi.put("targets", v, { idempotencyKey })}
 *     onDone={(result) => { setOpen(false); if (result) toast("Saved", "good"); }} />
 */
import { useId, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import { isPortalApiError, newIdempotencyKey } from "../lib/api";
import { Button } from "./Button";
import { cx } from "./context";
import { Modal } from "./Overlay";
import { toast } from "./Overlay";

export type FieldType = "text" | "number" | "date" | "tel" | "email" | "password" | "url" | "textarea" | "select" | "multiselect" | "checkbox";
export type OptionValue = string | number | boolean | null;
export type OptionInput = { value?: OptionValue; id?: OptionValue; label?: string; name?: string } | [OptionValue, string?] | string | number;
export interface Option {
  value: OptionValue;
  label: string;
}

/** Normalise options: {value,label} | {id,name} | [value,label] | plain values. */
export function normOptions(options: readonly OptionInput[] = []): Option[] {
  return options.map((o) => {
    if (Array.isArray(o)) return { value: o[0] ?? null, label: String(o[1] ?? o[0]) };
    if (o !== null && typeof o === "object") {
      const v = o.value ?? o.id ?? null;
      return { value: v, label: o.label ?? o.name ?? String(v) };
    }
    return { value: o, label: String(o) };
  });
}

export interface FieldSpec {
  name: string;
  label?: string;
  type?: FieldType;
  required?: boolean;
  options?: readonly OptionInput[];
  value?: unknown;
  help?: ReactNode;
  placeholder?: string;
  min?: number | string;
  max?: number | string;
  step?: number | string;
  rows?: number;
  full?: boolean;
  disabled?: boolean;
  maxLength?: number;
  autoComplete?: string;
}

/* ------------------------------------------------------------------ primitives */

/** Label + control + help + error, with the ids wired for screen readers. `children(id, describedBy)`. */
export function Field({
  label,
  required,
  help,
  error,
  full,
  check,
  name,
  children,
}: {
  label: ReactNode;
  /** field name (data-field, used to focus the first bad field) */
  name?: string;
  required?: boolean;
  help?: ReactNode;
  error?: string | null;
  full?: boolean;
  check?: boolean;
  children: (id: string, describedBy: string) => ReactNode;
}) {
  const id = useId();
  const describedBy = [help ? `${id}-help` : null, `${id}-err`].filter(Boolean).join(" ");
  const lbl = (
    <label htmlFor={id} className="td-field__label">
      {label}
      {required ? (
        <span className="td-field__req" aria-hidden="true">
          {" "}
          *
        </span>
      ) : null}
    </label>
  );
  return (
    <div className={cx("td-field", full && "td-field--full", check && "td-field--check", error && "has-error")} data-field={name}>
      {check ? (
        <div className="td-field__checkrow">
          {children(id, describedBy)}
          {lbl}
        </div>
      ) : (
        <>
          {lbl}
          {children(id, describedBy)}
        </>
      )}
      {help ? (
        <div id={`${id}-help`} className="td-field__help">
          {help}
        </div>
      ) : null}
      <div id={`${id}-err`} className="td-field__error" aria-live="polite">
        {error ?? ""}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ spec-driven form */

type Values = Record<string, unknown>;

function initialRaw(f: FieldSpec, opts: Option[]): unknown {
  const v = f.value;
  switch (f.type) {
    case "checkbox":
      return !!v;
    case "multiselect":
      return Array.isArray(v) ? v.map(String) : [];
    case "select": {
      const i = opts.findIndex((o) => v !== undefined && v !== null && String(o.value) === String(v));
      return i < 0 ? "" : String(i);
    }
    case "date":
      return v === undefined || v === null ? "" : String(v).slice(0, 10);
    default:
      return v === undefined || v === null ? "" : String(v);
  }
}

function readValue(f: FieldSpec, raw: unknown, opts: Option[]): unknown {
  switch (f.type) {
    case "checkbox":
      return !!raw;
    case "multiselect":
      return opts.filter((o) => (raw as string[]).includes(String(o.value))).map((o) => o.value);
    case "select":
      return raw === "" ? null : (opts[Number(raw)]?.value ?? null);
    case "textarea":
      return String(raw).trim() === "" ? null : String(raw);
    default: {
      const s = String(raw).trim();
      if (s === "") return null;
      if (f.type === "number") {
        const n = Number(s);
        return Number.isNaN(n) ? s : n;
      }
      return s;
    }
  }
}

export interface PortalFormProps {
  fields: (FieldSpec | null | false | undefined)[];
  submitLabel?: string;
  cancelLabel?: string;
  onCancel?: () => void;
  /** throw (e.g. a PortalApiError) to keep the form open with errors */
  onSubmit: (values: Values) => Promise<unknown> | unknown;
  /** live values (debounce yourself if it is expensive) */
  onChange?: (values: Values) => void;
  danger?: boolean;
}

export function PortalForm({ fields: rawFields, submitLabel = "Save", cancelLabel = "Cancel", onCancel, onSubmit, onChange, danger }: PortalFormProps) {
  const fields = useMemo(() => rawFields.filter((f): f is FieldSpec => !!f), [rawFields]);
  const opts = useMemo(() => Object.fromEntries(fields.map((f) => [f.name, normOptions(f.options ?? [])])), [fields]);
  const [raw, setRaw] = useState<Record<string, unknown>>(() => Object.fromEntries(fields.map((f) => [f.name, initialRaw(f, opts[f.name] ?? [])])));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const formRef = useRef<HTMLFormElement>(null);
  const [filter, setFilter] = useState<Record<string, string>>({});

  const values = (r = raw): Values => Object.fromEntries(fields.map((f) => [f.name, readValue(f, r[f.name], opts[f.name] ?? [])]));
  const set = (name: string, v: unknown) => {
    const next = { ...raw, [name]: v };
    setRaw(next);
    onChange?.(values(next));
  };
  const focusField = (name: string) => {
    const el = formRef.current?.querySelector<HTMLElement>(`[data-field="${CSS.escape(name)}"] input, [data-field="${CSS.escape(name)}"] select, [data-field="${CSS.escape(name)}"] textarea`);
    el?.focus();
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setErrors({});
    setFormError(null);
    const v = values();
    const errs: Record<string, string> = {};
    for (const f of fields) {
      const x = v[f.name];
      const missing = x === null || x === undefined || x === "" || (Array.isArray(x) && !x.length);
      if (f.required && missing && f.type !== "checkbox") errs[f.name] = `${f.label ?? f.name} is required`;
      else if (f.type === "number" && x !== null && typeof x !== "number") errs[f.name] = "Enter a number";
      else if (f.type === "email" && x && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(String(x))) errs[f.name] = "Enter a valid email address";
    }
    const firstBad = fields.find((f) => errs[f.name]);
    if (firstBad) {
      setErrors(errs);
      focusField(firstBad.name);
      return;
    }
    setBusy(true);
    try {
      await onSubmit(v);
    } catch (err) {
      const fe = isPortalApiError(err) ? err.fields : {};
      const known = Object.fromEntries(Object.entries(fe).filter(([k]) => fields.some((f) => f.name === k)));
      const unknown = Object.entries(fe).filter(([k]) => !(k in known)).map(([k, m]) => `${k}: ${m}`);
      const msg = err instanceof Error ? err.message : "Could not save";
      setErrors(known);
      if (!Object.keys(known).length || unknown.length) setFormError([msg, ...unknown].join(" — "));
      const first = fields.find((f) => known[f.name]);
      if (first) focusField(first.name);
      if (!isPortalApiError(err) || err.status !== 400) toast(msg, "bad");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="td-form" noValidate onSubmit={submit} ref={formRef} aria-busy={busy || undefined}>
      {formError ? (
        <div className="td-form__error" role="alert">
          {formError}
        </div>
      ) : null}
      <div className="td-form__grid">
        {fields.map((f) => {
          const type = f.type ?? "text";
          const o = opts[f.name] ?? [];
          const full = type === "textarea" || type === "multiselect" || f.full;
          return (
              <Field key={f.name} name={f.name} label={f.label ?? f.name} required={f.required} help={f.help} error={errors[f.name]} full={full} check={type === "checkbox"}>
                {(id, describedBy) => {
                  const common = { id, name: f.name, "aria-describedby": describedBy, "aria-invalid": errors[f.name] ? true : undefined, "aria-required": f.required || undefined, disabled: f.disabled };
                  if (type === "textarea")
                    return <textarea {...common} className="td-input" rows={f.rows ?? 3} placeholder={f.placeholder} value={String(raw[f.name] ?? "")} onChange={(e) => set(f.name, e.target.value)} />;
                  if (type === "select")
                    return (
                      <select {...common} className="td-input td-select" value={String(raw[f.name] ?? "")} onChange={(e) => set(f.name, e.target.value)}>
                        <option value="">{f.placeholder ?? (f.required ? "Choose…" : "— None —")}</option>
                        {o.map((op, i) => (
                          <option key={i} value={String(i)}>
                            {op.label}
                          </option>
                        ))}
                      </select>
                    );
                  if (type === "checkbox") return <input {...common} type="checkbox" className="td-check" checked={!!raw[f.name]} onChange={(e) => set(f.name, e.target.checked)} />;
                  if (type === "multiselect") {
                    const sel = (raw[f.name] as string[]) ?? [];
                    const q = (filter[f.name] ?? "").toLowerCase();
                    return (
                      <div className="td-multi" id={id} role="group" aria-describedby={describedBy}>
                        <div className="td-multi__top">
                          {o.length > 6 ? (
                            <input
                              type="search"
                              className="td-input td-input--sm"
                              placeholder="Search…"
                              aria-label={`Search ${f.label ?? f.name}`}
                              value={filter[f.name] ?? ""}
                              onChange={(e) => setFilter({ ...filter, [f.name]: e.target.value })}
                              onKeyDown={(e) => e.key === "Enter" && e.preventDefault()}
                            />
                          ) : null}
                          <span className="td-multi__count td-num">{sel.length ? `${sel.length} selected` : "None selected"}</span>
                        </div>
                        <div className="td-multi__list">
                          {o.length ? (
                            o.map((op) => (
                              <label key={String(op.value)} className="td-multi__opt" hidden={!!q && !op.label.toLowerCase().includes(q)}>
                                <input
                                  type="checkbox"
                                  disabled={f.disabled}
                                  checked={sel.includes(String(op.value))}
                                  onChange={(e) => set(f.name, e.target.checked ? [...sel, String(op.value)] : sel.filter((x) => x !== String(op.value)))}
                                />
                                <span>{op.label}</span>
                              </label>
                            ))
                          ) : (
                            <div className="td-muted td-multi__none">No options available</div>
                          )}
                        </div>
                      </div>
                    );
                  }
                  return (
                    <input
                      {...common}
                      type={type}
                      className={cx("td-input", (type === "number" || type === "date" || type === "tel") && "td-num")}
                      placeholder={f.placeholder}
                      inputMode={type === "number" ? "decimal" : undefined}
                      min={f.min}
                      max={f.max}
                      step={f.step ?? (type === "number" ? "any" : undefined)}
                      maxLength={f.maxLength}
                      autoComplete={f.autoComplete ?? (type === "tel" ? "tel" : type === "email" ? "email" : type === "password" ? "current-password" : "off")}
                      value={String(raw[f.name] ?? "")}
                      onChange={(e) => set(f.name, e.target.value)}
                    />
                  );
                }}
              </Field>
          );
        })}
      </div>
      <div className="td-form__foot">
        {onCancel ? (
          <Button tone="ghost" onClick={onCancel}>
            {cancelLabel}
          </Button>
        ) : null}
        <Button type="submit" tone={danger ? "danger" : "primary"} busy={busy}>
          {busy ? "Saving…" : submitLabel}
        </Button>
      </div>
    </form>
  );
}

export interface FormDialogProps<R> {
  open: boolean;
  title: ReactNode;
  intro?: ReactNode;
  fields: PortalFormProps["fields"];
  /** initial values by field name (a field's own `value` wins) */
  values?: Values;
  submitLabel?: string;
  cancelLabel?: string;
  wide?: boolean;
  danger?: boolean;
  footerNote?: ReactNode;
  onChange?: (values: Values) => void;
  /**
   * Save. `idempotencyKey` is one key per submit attempt (F1): kept only when the attempt failed with no answer
   * (network), so a retry of the same body is de-duplicated by the server. Throw to keep the dialog open.
   */
  onSubmit: (values: Values, ctx: { idempotencyKey: string }) => Promise<R> | R;
  /** closed: the onSubmit result after a save, null after Cancel / Esc / × */
  onDone: (result: R | null) => void;
}

/** Modal + PortalForm. Mount it with `open`; it resets every time it opens. */
export function FormDialog<R = unknown>({ open, title, intro, fields, values, submitLabel, cancelLabel, wide, danger, footerNote, onChange, onSubmit, onDone }: FormDialogProps<R>) {
  const key = useRef(newIdempotencyKey());
  const withValues = useMemo(
    () => fields.map((f) => (f && values && f.name in values && f.value === undefined ? { ...f, value: values[f.name] } : f)),
    [fields, values],
  );
  return (
    <Modal open={open} title={title} wide={wide} form onClose={() => onDone(null)}>
      {open ? (
        <div className="td-formdlg">
          {intro ? <div className="td-formdlg__intro">{intro}</div> : null}
          <PortalForm
            fields={withValues}
            submitLabel={submitLabel}
            cancelLabel={cancelLabel}
            danger={danger}
            onChange={onChange}
            onCancel={() => onDone(null)}
            onSubmit={async (v) => {
              try {
                const r = await onSubmit(v, { idempotencyKey: key.current });
                key.current = newIdempotencyKey();
                onDone((r === undefined ? true : r) as R);
              } catch (e) {
                if (!isPortalApiError(e) || e.status !== 0) key.current = newIdempotencyKey();
                throw e;
              }
            }}
          />
          {footerNote ? <div className="td-formdlg__note td-muted">{footerNote}</div> : null}
        </div>
      ) : null}
    </Modal>
  );
}
