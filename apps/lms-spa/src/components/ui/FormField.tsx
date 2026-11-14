import { useId, type ReactNode } from "react";

export interface FieldControlProps {
  id: string;
  "aria-describedby"?: string;
  "aria-invalid"?: true;
  "aria-required"?: true;
}

export interface FormFieldProps {
  label: ReactNode;
  hint?: ReactNode;
  /** Error text (e.g. from problem+json `errors[].message`). */
  error?: ReactNode;
  required?: boolean;
  /** Render the control with the wiring props (id, aria-describedby, aria-invalid). */
  children: (control: FieldControlProps) => ReactNode;
}

/**
 * Label + control + hint + error with correct ARIA wiring. The error is tied to the control via
 * aria-describedby + aria-invalid (read when the field is focused); it is NOT a live region, so an
 * empty submit does not fire one alert per field (audit S7). Forms announce once, through their
 * error summary / a single live region, and move focus to the first invalid field or the summary.
 */
export function FormField({ label, hint, error, required, children }: FormFieldProps) {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(" ") || undefined;
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block text-sm font-semibold text-fg">
        {label}
        {required ? (
          <span className="text-danger-fg" aria-hidden="true">
            {" "}
            *
          </span>
        ) : null}
      </label>
      {children({
        id,
        "aria-describedby": describedBy,
        ...(error ? { "aria-invalid": true as const } : {}),
        ...(required ? { "aria-required": true as const } : {}),
      })}
      {hint ? (
        <p id={hintId} className="text-[0.8125rem] leading-snug text-fg-muted">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p
          id={errorId}
          className="flex items-start gap-1.5 text-[0.8125rem] font-medium leading-snug text-danger-fg before:mt-px before:inline-flex before:h-4 before:w-4 before:shrink-0 before:items-center before:justify-center before:rounded-full before:bg-danger-solid before:text-[0.625rem] before:font-bold before:text-danger-on-solid before:content-['!']"
        >
          {error}
        </p>
      ) : null}
    </div>
  );
}

/** Map problem+json validation errors to a field → message record. */
export function fieldErrors(errors: { field: string; message: string }[] | undefined): Record<string, string> {
  const out: Record<string, string> = {};
  for (const e of errors ?? []) if (!(e.field in out)) out[e.field] = e.message;
  return out;
}
