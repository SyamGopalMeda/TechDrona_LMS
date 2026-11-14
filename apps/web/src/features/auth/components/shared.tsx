"use client";

import Link from "next/link";
import { forwardRef, useEffect, useRef, useState, type ComponentProps, type ReactNode } from "react";
import { Button, Input, LinkButton } from "@/components/ui";
import { cn } from "@/lib/ui/cn";
import type { FormErrorInfo } from "../lib/errors";

/* --------------------------------------------------------------- AuthCard */

const featIcon = { "aria-hidden": true, viewBox: "0 0 24 24", width: 22, height: 22, fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round", strokeLinejoin: "round" } as const;

/** Brand-panel features (website `.al-feats`: icon in a white circle + one line). */
const AUTH_FEATURES: { label: string; path: string }[] = [
  { label: "Live classes & recorded lessons", path: "M4 5.5A1.5 1.5 0 0 1 5.5 4H11v16H5.5A1.5 1.5 0 0 1 4 18.5zM13 4h5.5A1.5 1.5 0 0 1 20 5.5v13a1.5 1.5 0 0 1-1.5 1.5H13z" },
  { label: "Tests & coding practice", path: "m8 9-3 3 3 3m8-6 3 3-3 3M14 5l-4 14" },
  { label: "Mentoring & placement prep", path: "M16 20v-1a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v1M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zm13 9v-1a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8" },
  { label: "Verified certificates", path: "M12 15a6 6 0 1 0 0-12 6 6 0 0 0 0 12zm-3.5-1.2L7 22l5-3 5 3-1.5-8.2" },
];

/**
 * Sign-in layout, after the website's back-office login (tech drona/src/pages/Admin.jsx `Login`,
 * CSS §27 `.al-*` → src/styles/site.css `td-al-*`): from 1024px a brand panel (classroom photo,
 * navy lockup, "Every course. Every learner. One place.", rule, tagline, feature list) beside a
 * white rounded card on a soft navy/green wash; below that just the card, with the logo on top.
 * The brand panel is decorative (aria-hidden), so the card's h1 stays the page's only h1.
 * Used by every auth step (log in, sign-up, MFA, device, recovery, verification).
 */
export function AuthCard({ title, description, children, eyebrow }: { title: string; description?: ReactNode; children: ReactNode; eyebrow?: string }) {
  return (
    <div className="td-al td-enter">
      <section className="td-al-brand" aria-hidden="true">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img className="td-al-photo" src="/brand/login-photo.webp" alt="" decoding="async" />
        <div className="td-al-brand-in">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img className="td-al-logo" src="/brand/logo-lockup-navy.svg" alt="" width={240} height={52} />
          <p className="td-al-head td-enter" style={{ ["--td-i" as string]: 1 }}>
            Every course.
            <br />
            Every learner.
            <br />
            <span>One place.</span>
          </p>
          <i className="td-al-rule" />
          <p className="td-al-tag">Debug your career. Deploy your dreams.</p>
          <ul className="td-al-feats">
            {AUTH_FEATURES.map((f, i) => (
              <li key={f.label} className="td-enter" style={{ ["--td-i" as string]: i + 2 }}>
                <span>
                  <svg {...featIcon}>
                    <path d={f.path} />
                  </svg>
                </span>
                {f.label}
              </li>
            ))}
          </ul>
        </div>
      </section>
      <div className="td-al-side">
        <Link href="/help" className="td-al-help">
          <svg {...featIcon} width={18} height={18}>
            <path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z" />
          </svg>
          Need help? <b>Contact support</b>
        </Link>
        <div className="td-al-card">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img className="td-al-card-logo" src="/brand/logo-lockup-navy.svg" alt="" width={200} height={44} />
          {eyebrow ? <p className="td-al-eyebrow">{eyebrow}</p> : null}
          <h1 className="td-al-title font-extrabold">{title}</h1>
          {description ? <div className="td-al-sub">{description}</div> : null}
          <div className="mt-7">{children}</div>
        </div>
        <p className="td-al-foot">Your Tech Drona learning portal · one sign-in for every module</p>
      </div>
    </div>
  );
}

/** "or" rule between Google sign-in and the password form (decorative). */
export function OrDivider() {
  return (
    <div className="my-5 flex items-center gap-3 text-xs text-fg-muted" aria-hidden="true">
      <span className="h-px flex-1 bg-line" />
      or
      <span className="h-px flex-1 bg-line" />
    </div>
  );
}

/** Up-front "this step/link no longer works" card shown instead of a form that can't succeed. */
export function ExpiredNotice({ title, children, href, linkLabel }: { title: string; children: ReactNode; href: string; linkLabel: string }) {
  return (
    <div className="space-y-4">
      <Notice tone="warning" title={title}>
        <p>{children}</p>
      </Notice>
      <LinkButton href={href} size="lg" className="w-full">
        {linkLabel}
      </LinkButton>
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
