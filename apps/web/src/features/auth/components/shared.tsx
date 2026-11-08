"use client";

import { forwardRef, useEffect, useRef, useState, type ComponentProps, type ReactNode } from "react";
import { Button, Input } from "@/components/ui";
import { cn } from "@/lib/ui/cn";
import type { FormErrorInfo } from "../lib/errors";

/* --------------------------------------------------------------- AuthCard */

/** Single-column card, max 480 px (wireframes §3/§4). */
export function AuthCard({ title, description, children, eyebrow }: { title: string; description?: ReactNode; children: ReactNode; eyebrow?: string }) {
  return (
    <div className="mx-auto w-full max-w-[480px]">
      <div className="rounded-xl border border-line bg-surface p-6 shadow-xs">
        {eyebrow ? <p className="text-xs font-semibold uppercase tracking-wide text-fg-muted">{eyebrow}</p> : null}
        <h1 className="font-display text-2xl font-bold text-fg">{title}</h1>
        {description ? <div className="mt-1 text-sm text-fg-muted">{description}</div> : null}
        <div className="mt-6">{children}</div>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------- FormAlert */

/** Inline form-level error (problem title/detail + reference). Focusable for error-summary focus. */
export const FormAlert = forwardRef<HTMLDivElement, { error: FormErrorInfo | null; children?: ReactNode }>(function FormAlert({ error, children }, ref) {
  if (!error) return null;
  return (
    <div ref={ref} tabIndex={-1} role="alert" className="rounded-lg border border-danger-border bg-danger-subtle p-4 text-sm focus:outline-none focus-visible:shadow-focus">
      <p className="font-semibold text-danger-fg">{error.title}</p>
      {error.detail ? <p className="mt-1 text-fg-secondary">{error.detail}</p> : null}
      {children}
      {error.requestId ? (
        <p className="mt-2 text-xs text-fg-muted">
          Reference: <span className="select-all font-mono">{error.requestId}</span>
        </p>
      ) : null}
    </div>
  );
});

/* ---------------------------------------------------------- ErrorSummary */

/** Error summary at the top of a form on submit (wireframes §3); links move focus to the field. */
export function ErrorSummary({ errors, fieldIds }: { errors: Record<string, string>; fieldIds: Record<string, string> }) {
  const ref = useRef<HTMLDivElement>(null);
  const entries = Object.entries(errors);
  const key = entries.map(([k]) => k).join(",");
  useEffect(() => {
    if (key) ref.current?.focus();
  }, [key]);
  if (entries.length === 0) return null;
  return (
    <div ref={ref} tabIndex={-1} role="alert" aria-labelledby="error-summary-title" className="rounded-lg border border-danger-border bg-danger-subtle p-4 text-sm focus:outline-none focus-visible:shadow-focus">
      <p id="error-summary-title" className="font-semibold text-danger-fg">
        Please fix {entries.length === 1 ? "this problem" : `these ${entries.length} problems`}
      </p>
      <ul className="mt-2 list-disc space-y-1 pl-5">
        {entries.map(([field, msg]) => (
          <li key={field}>
            {fieldIds[field] ? (
              <a
                href={`#${fieldIds[field]}`}
                className="text-fg-link underline"
                onClick={(e) => {
                  e.preventDefault();
                  const target = fieldIds[field]!;
                  (document.getElementById(target) ?? document.getElementsByName(target)[0])?.focus();
                }}
              >
                {msg}
              </a>
            ) : (
              msg
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

/* ---------------------------------------------------------- Notice */

export function Notice({ tone = "info", title, children, className }: { tone?: "info" | "success" | "warning"; title?: ReactNode; children?: ReactNode; className?: string }) {
  const tones = {
    info: "border-info-border bg-info-subtle text-info-fg",
    success: "border-success-border bg-success-subtle text-success-fg",
    warning: "border-warning-border bg-warning-subtle text-warning-fg",
  } as const;
  return (
    <div role="status" className={cn("rounded-lg border p-4 text-sm", tones[tone], className)}>
      {title ? <p className="font-semibold">{title}</p> : null}
      {children ? <div className={cn(title ? "mt-1" : undefined, "text-fg-secondary")}>{children}</div> : null}
    </div>
  );
}

/* ---------------------------------------------------------- PasswordInput */

/** Password with a show/hide toggle. Value is never logged or put in a URL. */
export function PasswordInput(props: Omit<ComponentProps<"input">, "type">) {
  const [shown, setShown] = useState(false);
  return (
    <div className="relative">
      <Input {...props} type={shown ? "text" : "password"} className={cn("pr-20", props.className)} spellCheck={false} autoCapitalize="none" />
      <button
        type="button"
        onClick={() => setShown((s) => !s)}
        aria-pressed={shown}
        aria-controls={props.id}
        className="absolute inset-y-0 right-0 my-1 mr-1 rounded-md px-3 text-xs font-medium text-fg-secondary hover:bg-surface-hover focus-visible:shadow-focus focus-visible:outline-none"
      >
        {shown ? "Hide" : "Show"}
        <span className="sr-only"> password</span>
      </button>
    </div>
  );
}

/* --------------------------------------------------------------- OtpInput */

/** Single 6-digit field (one input is easier for screen readers and paste than 6 boxes). */
export function OtpInput(props: Omit<ComponentProps<"input">, "onChange" | "value"> & { value: string; onValueChange: (v: string) => void; length?: number }) {
  const { value, onValueChange, length = 6, ...rest } = props;
  return (
    <Input
      {...rest}
      inputMode="numeric"
      autoComplete="one-time-code"
      pattern="[0-9]*"
      maxLength={length}
      value={value}
      onChange={(e) => onValueChange(e.target.value.replace(/\D/g, "").slice(0, length))}
      className={cn("max-w-[12rem] font-mono tracking-[0.4em]", rest.className)}
    />
  );
}

/* --------------------------------------------------------------- Countdown */

export function useCountdown(): [number, (seconds: number) => void] {
  const [left, setLeft] = useState(0);
  useEffect(() => {
    if (left <= 0) return;
    const t = setTimeout(() => setLeft((s) => s - 1), 1000);
    return () => clearTimeout(t);
  }, [left]);
  return [left, setLeft];
}

/* --------------------------------------------------------------- Copy chip */

/** Case reference chip with copy button (DS §5.13). */
export function ReferenceChip({ value, label = "Copy reference" }: { value: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <span className="inline-flex items-center gap-2">
      <span className="select-all rounded-md bg-surface-subtle px-2 py-0.5 font-mono text-sm text-fg">{value}</span>
      <Button
        variant="ghost"
        size="sm"
        aria-label={`${label} ${value}`}
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(value);
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
          } catch {
            /* clipboard unavailable: the value is selectable */
          }
        }}
      >
        {copied ? "Copied" : "Copy"}
      </Button>
      <span className="sr-only" aria-live="polite">
        {copied ? "Copied" : ""}
      </span>
    </span>
  );
}
