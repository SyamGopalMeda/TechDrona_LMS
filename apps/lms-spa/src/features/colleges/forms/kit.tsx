/**
 * Form-dialog kit for the hand-built portal dialogs (the old forms.js `openForm` / followups.js `formModal`):
 * a Modal holding a `td-form` with inline field errors, a form-level error, a danger zone and a sticky
 * Cancel / Save row. Fields are controlled by the dialog (so they can show / hide / filter like before).
 *
 *   <DialogForm open title="Add contact" submitLabel="Add contact" onDone={onDone}
 *     onSubmit={async (key) => portalApi.post("contacts", body, { idempotencyKey: key })}>
 *     {(err) => <><TextField name="name" label="Name" value={v.name} onChange={…} error={err.name} /></>}
 *   </DialogForm>
 *
 * onSubmit throws → errors with `fields` (validationError / a 400 PortalApiError) show under the inputs, anything
 * else above the form (+ a toast unless it is a 400). Return KEEP_OPEN to stay open without an error.
 */
import { useRef, useState, type FormEvent, type ReactNode } from "react";
import { isPortalApiError, newIdempotencyKey } from "../lib/api";
import { Button } from "../ui/Button";
import { cx } from "../ui/context";
import { Field } from "../ui/Form";
import { Modal, toast } from "../ui/Overlay";
import { addDays, today } from "./util";

export const KEEP_OPEN = Symbol("keep-open");

export interface DialogFormProps<R> {
  open?: boolean;
  title: ReactNode;
  intro?: ReactNode;
  submitLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  wide?: boolean;
  /** below the fields, above the Cancel / Save row (e.g. Delete) */
  extra?: ReactNode;
  /** extra class on the <form> (e.g. "fu-form") */
  className?: string;
  /** one idempotency key per submission (kept only after a network failure) */
  onSubmit: (idempotencyKey: string) => Promise<R | typeof KEEP_OPEN> | R | typeof KEEP_OPEN;
  /** closed: the onSubmit result after a save, null after Cancel / Esc / × */
  onDone: (result: R | null) => void;
  /** map of server field names → this form's field names */
  fieldMap?: Record<string, string>;
  /** children are not wrapped in the two-column `td-form__grid` */
  bare?: boolean;
  children: (errors: Record<string, string>) => ReactNode;
}

export function DialogForm<R>({ open = true, title, intro, submitLabel = "Save", cancelLabel = "Cancel", danger, wide, extra, className, onSubmit, onDone, fieldMap, bare, children }: DialogFormProps<R>) {
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const key = useRef(newIdempotencyKey());
  const formRef = useRef<HTMLFormElement>(null);

  const focusField = (name: string) => {
    const sel = `[data-field="${CSS.escape(name)}"]`;
    formRef.current?.querySelector<HTMLElement>(`${sel} input, ${sel} select, ${sel} textarea, ${sel} button`)?.focus();
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setErrors({});
    setFormError(null);
    setBusy(true);
    try {
      const r = await onSubmit(key.current);
      key.current = newIdempotencyKey();
      if (r === KEEP_OPEN) return;
      onDone((r === undefined ? true : r) as R);
    } catch (err) {
      if (!isPortalApiError(err) || err.status !== 0) key.current = newIdempotencyKey();
      const raw: Record<string, string> = isPortalApiError(err) ? err.fields : ((err as { fields?: Record<string, string> })?.fields ?? {});
      const fe = Object.fromEntries(Object.entries(raw).map(([k, v]) => [fieldMap?.[k] ?? k, String(v)]));
      const form = formRef.current;
      const known = Object.fromEntries(Object.entries(fe).filter(([k]) => !!form?.querySelector(`[data-field="${CSS.escape(k)}"]`)));
      const unknown = Object.entries(fe).filter(([k]) => !(k in known)).map(([, m]) => m);
      const msg = err instanceof Error ? err.message : "Could not save";
      setErrors(known);
      if (!Object.keys(known).length || unknown.length) setFormError(Object.keys(known).length ? unknown.join(" ") : [msg, ...unknown.filter((m) => m !== msg)].join(" — "));
      const first = Object.keys(known)[0];
      if (first) requestAnimationFrame(() => focusField(first));
      if (!(isPortalApiError(err) && err.status === 400) && !Object.keys(raw).length) toast(msg, "bad");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} title={title} wide={wide} form onClose={() => !busy && onDone(null)}>
      {open ? (
        <form className={cx("td-form", className)} noValidate onSubmit={submit} ref={formRef} aria-busy={busy || undefined}>
          {intro ? <div className="td-formdlg__intro">{intro}</div> : null}
          {formError ? (
            <div className="td-form__error" role="alert">
              {formError}
            </div>
          ) : null}
          {bare ? children(errors) : <div className="td-form__grid">{children(errors)}</div>}
          {extra ?? null}
          <div className="td-form__foot">
            <Button tone="ghost" onClick={() => onDone(null)} disabled={busy}>
              {cancelLabel}
            </Button>
            <Button type="submit" tone={danger ? "danger" : "primary"} busy={busy}>
              {busy ? "Saving…" : submitLabel}
            </Button>
          </div>
        </form>
      ) : null}
    </Modal>
  );
}

/* ------------------------------------------------------------------ controlled fields */

export interface Opt {
  value: string;
  label: string;
  disabled?: boolean;
}

interface BaseProps {
  name: string;
  label: ReactNode;
  required?: boolean;
  help?: ReactNode;
  error?: string;
  full?: boolean;
  hidden?: boolean;
  disabled?: boolean;
}

function Wrap({ hidden, children }: { hidden?: boolean; children: ReactNode }) {
  return hidden ? null : <>{children}</>;
}

export function TextField({
  value,
  onChange,
  type = "text",
  placeholder,
  maxLength,
  min,
  max,
  step,
  autoComplete,
  list,
  ...b
}: BaseProps & {
  value: string;
  onChange: (v: string) => void;
  type?: "text" | "tel" | "email" | "url" | "date" | "number" | "search";
  placeholder?: string;
  maxLength?: number;
  min?: string | number;
  max?: string | number;
  step?: string | number;
  autoComplete?: string;
  list?: string;
}) {
  return (
    <Wrap hidden={b.hidden}>
      <Field name={b.name} label={b.label} required={b.required} help={b.help} error={b.error} full={b.full}>
        {(id, describedBy) => (
          <input
            id={id}
            name={b.name}
            type={type}
            className={cx("td-input", (type === "number" || type === "date" || type === "tel") && "td-num")}
            value={value}
            placeholder={placeholder}
            maxLength={maxLength}
            min={min}
            max={max}
            step={step ?? (type === "number" ? "any" : undefined)}
            inputMode={type === "number" ? "decimal" : undefined}
            autoComplete={autoComplete ?? (type === "tel" ? "tel" : type === "email" ? "email" : "off")}
            list={list}
            disabled={b.disabled}
            aria-describedby={describedBy}
            aria-invalid={b.error ? true : undefined}
            aria-required={b.required || undefined}
            onChange={(e) => onChange(e.target.value)}
          />
        )}
      </Field>
    </Wrap>
  );
}

export function TextAreaField({ value, onChange, rows = 3, placeholder, ...b }: BaseProps & { value: string; onChange: (v: string) => void; rows?: number; placeholder?: string }) {
  return (
    <Wrap hidden={b.hidden}>
      <Field name={b.name} label={b.label} required={b.required} help={b.help} error={b.error} full={b.full ?? true}>
        {(id, describedBy) => (
          <textarea
            id={id}
            name={b.name}
            className="td-input"
            rows={rows}
            value={value}
            placeholder={placeholder}
            disabled={b.disabled}
            aria-describedby={describedBy}
            aria-invalid={b.error ? true : undefined}
            onChange={(e) => onChange(e.target.value)}
          />
        )}
      </Field>
    </Wrap>
  );
}

/** Select with real string values. `placeholder` adds the empty first option. */
export function SelectField({ value, onChange, options, placeholder, ...b }: BaseProps & { value: string; onChange: (v: string) => void; options: Opt[]; placeholder?: string }) {
  return (
    <Wrap hidden={b.hidden}>
      <Field name={b.name} label={b.label} required={b.required} help={b.help} error={b.error} full={b.full}>
        {(id, describedBy) => (
          <select
            id={id}
            name={b.name}
            className="td-input td-select"
            value={value}
            disabled={b.disabled}
            aria-describedby={describedBy}
            aria-invalid={b.error ? true : undefined}
            aria-required={b.required || undefined}
            onChange={(e) => onChange(e.target.value)}
          >
            {placeholder !== undefined ? <option value="">{placeholder}</option> : null}
            {options.map((o) => (
              <option key={o.value} value={o.value} disabled={o.disabled}>
                {o.label}
              </option>
            ))}
          </select>
        )}
      </Field>
    </Wrap>
  );
}

export function CheckField({ checked, onChange, ...b }: BaseProps & { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <Wrap hidden={b.hidden}>
      <Field name={b.name} label={b.label} help={b.help} error={b.error} full={b.full} check>
        {(id, describedBy) => <input id={id} name={b.name} type="checkbox" className="td-check" checked={checked} disabled={b.disabled} aria-describedby={describedBy} onChange={(e) => onChange(e.target.checked)} />}
      </Field>
    </Wrap>
  );
}

/** Checkbox list (the old `multiselect` field) with a search box when long. */
export function MultiField({ value, onChange, options, ...b }: BaseProps & { value: string[]; onChange: (v: string[]) => void; options: Opt[] }) {
  const [q, setQ] = useState("");
  return (
    <Wrap hidden={b.hidden}>
      <Field name={b.name} label={b.label} help={b.help} error={b.error} full>
        {(id, describedBy) => (
          <div className="td-multi" id={id} role="group" aria-describedby={describedBy}>
            <div className="td-multi__top">
              {options.length > 6 ? (
                <input type="search" className="td-input td-input--sm" placeholder="Search…" aria-label={`Search ${typeof b.label === "string" ? b.label : ""}`} value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && e.preventDefault()} />
              ) : null}
              <span className="td-multi__count td-num">{value.length ? `${value.length} selected` : "None selected"}</span>
            </div>
            <div className="td-multi__list">
              {options.length ? (
                options.map((o) => (
                  <label key={o.value} className="td-multi__opt" hidden={!!q && !o.label.toLowerCase().includes(q.toLowerCase())}>
                    <input type="checkbox" disabled={b.disabled} checked={value.includes(o.value)} onChange={(e) => onChange(e.target.checked ? [...value, o.value] : value.filter((x) => x !== o.value))} />
                    <span>{o.label}</span>
                  </label>
                ))
              ) : (
                <div className="td-muted td-multi__none">No options available</div>
              )}
            </div>
          </div>
        )}
      </Field>
    </Wrap>
  );
}

/** "Tomorrow / +3 days / Next week / +2 weeks" buttons that set a date field (followups.js quickDates). */
export function QuickDates({ onPick, list = [["Tomorrow", 1], ["+3 days", 3], ["Next week", 7], ["+2 weeks", 14]] as [string, number][], hidden }: { onPick: (iso: string) => void; list?: [string, number][]; hidden?: boolean }) {
  if (hidden) return null;
  return (
    <div className="fu-quick td-field--full" role="group" aria-label="Quick dates">
      {list.map(([l, n]) => (
        <Button key={l} size="sm" onClick={() => onPick(addDays(today(), n))}>
          {l}
        </Button>
      ))}
    </div>
  );
}

/** Danger zone under a form ("Delete this follow-up"). */
export function DangerZone({ title, text, children }: { title?: ReactNode; text?: ReactNode; children: ReactNode }) {
  return (
    <div className="vf-danger">
      {title || text ? (
        <div>
          {title ? <strong>{title}</strong> : null}
          {text ? <p>{text}</p> : null}
        </div>
      ) : null}
      {children}
    </div>
  );
}
