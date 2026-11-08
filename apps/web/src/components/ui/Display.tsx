import Link from "next/link";
import type { ComponentProps, ReactNode } from "react";
import { ApiError } from "@/lib/api/errors";
import { cn } from "@/lib/ui/cn";
import { Button } from "./Button";

/* ---------------------------------------------------------------- Skeleton */

/** Placeholder block; decorative (the container announces loading via aria-busy). */
export function Skeleton({ className }: { className?: string }) {
  return (
    <div aria-hidden="true" className={cn("animate-pulse rounded-md bg-surface-sunken motion-reduce:animate-none", className)} />
  );
}

/**
 * Loading placeholder for a whole region: one polite status with screen-reader text plus
 * decorative skeleton lines (audit S8: replaces ad-hoc copies that put aria-label on a role-less div).
 */
export function LoadingBlock({ label = "Loading…", lines = 3, className }: { label?: string; lines?: number; className?: string }) {
  return (
    <div role="status" className={cn("space-y-3", className)}>
      <span className="sr-only">{label}</span>
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} className={cn("h-4", i === lines - 1 ? "w-2/3" : "w-full")} />
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------- Badge */

export type BadgeTone = "neutral" | "brand" | "info" | "success" | "warning" | "danger";

/* Website `.lx-tag` (lms.css:30-35): pill, no border, 12px bold Plus Jakarta Sans, tinted
   background with a dark same-hue text colour (all pairs >= 4.5:1, see tokens check). */
const badgeTones: Record<BadgeTone, string> = {
  neutral: "bg-surface-sunken text-fg-secondary",
  brand: "bg-brand-subtle text-brand-on-subtle",
  info: "bg-info-subtle text-info-fg",
  success: "bg-success-subtle text-success-fg",
  warning: "bg-warning-subtle text-warning-fg",
  danger: "bg-danger-subtle text-danger-fg",
};

const dotTones: Record<BadgeTone, string> = {
  neutral: "bg-fg-muted",
  brand: "bg-brand",
  info: "bg-info-border",
  success: "bg-success-border",
  warning: "bg-warning-border",
  danger: "bg-danger-border",
};

/** Status label. Always carries text, never colour alone (WCAG 1.4.1). */
export function Badge({ tone = "neutral", children, className, dot = false }: { tone?: BadgeTone; children: ReactNode; className?: string; dot?: boolean }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 font-display text-xs font-bold leading-5",
        badgeTones[tone],
        className,
      )}
    >
      {dot ? <span aria-hidden="true" className={cn("h-1.5 w-1.5 shrink-0 rounded-full", dotTones[tone])} /> : null}
      {children}
    </span>
  );
}

/**
 * Status vocabulary (docs/redesign/design-system.md §Status): one tone + one human label per
 * machine status, so every page shows "Pending review" the same way. Unknown statuses fall back to
 * a neutral badge with the status humanised ("in_review" → "In review").
 */
export const STATUS_VOCABULARY: Record<string, { tone: BadgeTone; label: string }> = {
  // waiting on someone
  pending: { tone: "warning", label: "Pending" },
  pending_review: { tone: "warning", label: "Pending review" },
  in_review: { tone: "warning", label: "In review" },
  awaiting_payment: { tone: "warning", label: "Awaiting payment" },
  requested: { tone: "warning", label: "Requested" },
  submitted: { tone: "info", label: "Submitted" },
  // good / done
  approved: { tone: "success", label: "Approved" },
  active: { tone: "success", label: "Active" },
  published: { tone: "success", label: "Published" },
  completed: { tone: "success", label: "Completed" },
  passed: { tone: "success", label: "Passed" },
  paid: { tone: "success", label: "Paid" },
  verified: { tone: "success", label: "Verified" },
  graded: { tone: "success", label: "Graded" },
  resolved: { tone: "success", label: "Resolved" },
  enabled: { tone: "success", label: "On" },
  // in motion
  scheduled: { tone: "info", label: "Scheduled" },
  in_progress: { tone: "info", label: "In progress" },
  processing: { tone: "info", label: "Processing" },
  open: { tone: "info", label: "Open" },
  live: { tone: "brand", label: "Live" },
  new: { tone: "brand", label: "New" },
  // problems
  rejected: { tone: "danger", label: "Rejected" },
  failed: { tone: "danger", label: "Failed" },
  blocked: { tone: "danger", label: "Blocked" },
  suspended: { tone: "danger", label: "Suspended" },
  overdue: { tone: "danger", label: "Overdue" },
  // parked / off
  inactive: { tone: "neutral", label: "Inactive" },
  disabled: { tone: "neutral", label: "Off" },
  draft: { tone: "neutral", label: "Draft" },
  archived: { tone: "neutral", label: "Archived" },
  closed: { tone: "neutral", label: "Closed" },
  expired: { tone: "neutral", label: "Expired" },
  cancelled: { tone: "neutral", label: "Cancelled" },
  canceled: { tone: "neutral", label: "Cancelled" },
  refunded: { tone: "neutral", label: "Refunded" },
  not_started: { tone: "neutral", label: "Not started" },
};

export function humanizeStatus(status: string): string {
  const s = status.replace(/[_-]+/g, " ").trim().toLowerCase();
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : status;
}

/** Badge for a machine status string using STATUS_VOCABULARY. `label`/`tone` override the mapping. */
export function StatusBadge({ status, label, tone, className }: { status: string; label?: ReactNode; tone?: BadgeTone; className?: string }) {
  const known = STATUS_VOCABULARY[status.toLowerCase()];
  return (
    <Badge tone={tone ?? known?.tone ?? "neutral"} dot className={className}>
      {label ?? known?.label ?? humanizeStatus(status)}
    </Badge>
  );
}

/* -------------------------------------------------------------------- Card */

export interface CardProps extends Omit<ComponentProps<"section">, "title"> {
  title?: ReactNode;
  /** One line under the title saying what the card is for. */
  description?: ReactNode;
  actions?: ReactNode;
}

/* Website `.lx-card` (lms.css:41-43): white, 1px #e6eaf1 border, 16px radius, hairline shadow. */
export function Card({ title, description, actions, className, children, ...props }: CardProps) {
  return (
    <section className={cn("rounded-xl border border-line bg-surface p-5 shadow-xs sm:p-6", className)} {...props}>
      {title || actions || description ? (
        <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            {title ? <h2 className="font-display text-base font-bold text-fg-heading">{title}</h2> : null}
            {description ? <p className="mt-0.5 text-sm text-fg-muted">{description}</p> : null}
          </div>
          {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
        </header>
      ) : null}
      {children}
    </section>
  );
}

/* -------------------------------------------------------------- EmptyState */

/** "E" state (PRD §6): explanation + primary next action. Website `.lx-empty` (lms.css:48-51). */
export function EmptyState({ title, description, action, icon }: { title: string; description?: ReactNode; action?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center rounded-xl border border-dashed border-line-strong bg-surface px-6 py-12 text-center">
      <span aria-hidden="true" className="mb-3 grid h-14 w-14 place-items-center rounded-full bg-brand-subtle text-brand">
        {icon ?? (
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="h-6 w-6">
            <path d="M4 13h4l1.5 3h5l1.5-3h4M4 13l2.5-7h11l2.5 7v5a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z" />
          </svg>
        )}
      </span>
      <p className="font-display text-base font-extrabold text-fg-heading">{title}</p>
      {description ? <p className="mt-1 max-w-prose text-sm text-fg-muted">{description}</p> : null}
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}

/* -------------------------------------------------------------- ErrorState */

export interface ErrorStateProps {
  /** An ApiError (title/detail/request_id are user-safe) or explicit text. */
  error?: unknown;
  title?: string;
  detail?: ReactNode;
  requestId?: string | null;
  onRetry?: () => void;
}

/** "X" state (PRD §6): problem title + request_id + retry; never a stack trace. */
export function ErrorState({ error, title, detail, requestId, onRetry }: ErrorStateProps) {
  const api = error instanceof ApiError ? error : null;
  const heading = title ?? api?.title ?? "Something went wrong";
  const body = detail ?? api?.detail ?? "Please try again.";
  const ref = requestId ?? api?.requestId ?? null;
  return (
    <div role="alert" className="flex gap-3 rounded-xl border border-danger-border/40 bg-danger-subtle p-5">
      <span
        aria-hidden="true"
        className="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full bg-danger-solid font-display text-xs font-bold text-danger-on-solid"
      >
        !
      </span>
      <div className="min-w-0">
        <p className="font-display font-bold text-danger-fg">{heading}</p>
        <p className="mt-1 text-sm text-fg-secondary">{body}</p>
        {ref ? (
          <p className="mt-2 text-xs text-fg-muted">
            Reference: <span className="select-all font-mono">{ref}</span>
          </p>
        ) : null}
        {onRetry ? (
          <Button variant="secondary" size="sm" className="mt-3" onClick={onRetry}>
            Try again
          </Button>
        ) : null}
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- StatTile */

export interface StatTileProps {
  label: string;
  /** Pre-formatted value; pass null when unknown (renders an em dash, never a fake number). */
  value: ReactNode | null;
  hint?: ReactNode;
  trend?: { direction: "up" | "down" | "flat"; label: string };
  /** Small decorative icon (inline SVG) shown in a tinted square, website `.lx-stat-ic`. */
  icon?: ReactNode;
  tone?: "brand" | "success" | "warning" | "danger";
}

const statIconTones = {
  brand: "bg-brand-subtle text-brand",
  success: "bg-success-subtle text-success-fg",
  warning: "bg-warning-subtle text-warning-fg",
  danger: "bg-danger-subtle text-danger-fg",
} as const;

/* Website `.lx-stat` (lms.css:55-59): white tile, 800-weight Jakarta value, 13px label. */
export function StatTile({ label, value, hint, trend, icon, tone = "brand" }: StatTileProps) {
  return (
    <div className="flex items-start gap-3 rounded-xl border border-line bg-surface p-4 shadow-xs">
      {icon ? (
        <span aria-hidden="true" className={cn("grid h-10 w-10 shrink-0 place-items-center rounded-lg [&_svg]:h-5 [&_svg]:w-5", statIconTones[tone])}>
          {icon}
        </span>
      ) : null}
      <div className="min-w-0">
        <p className="text-[0.8125rem] font-semibold text-fg-secondary">{label}</p>
        <p className="mt-0.5 font-display text-2xl font-extrabold tabular-nums leading-tight text-fg-heading">{value ?? "—"}</p>
        {trend ? (
          <p className="mt-1 text-xs text-fg-secondary">
            <span aria-hidden="true">{trend.direction === "up" ? "▲ " : trend.direction === "down" ? "▼ " : "■ "}</span>
            {trend.label}
          </p>
        ) : null}
        {hint ? <p className="mt-1 text-xs text-fg-muted">{hint}</p> : null}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------- Breadcrumbs */

export interface Crumb {
  label: ReactNode;
  /** Omit for the current page (last crumb). */
  href?: string;
}

/** "Where am I" trail. The last crumb is the current page (aria-current). */
export function Breadcrumbs({ items, className }: { items: Crumb[]; className?: string }) {
  if (!items.length) return null;
  return (
    <nav aria-label="Breadcrumb" className={cn("text-[0.8125rem]", className)}>
      <ol className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-fg-muted">
        {items.map((c, i) => {
          const last = i === items.length - 1;
          return (
            <li key={i} className="flex items-center gap-1.5">
              {c.href && !last ? (
                <Link href={c.href} className="inline-flex min-h-6 items-center font-medium text-fg-secondary no-underline hover:text-brand hover:underline focus-visible:shadow-focus focus-visible:outline-none">
                  {c.label}
                </Link>
              ) : (
                <span aria-current={last ? "page" : undefined} className={last ? "font-semibold text-fg" : undefined}>
                  {c.label}
                </span>
              )}
              {last ? null : (
                <span aria-hidden="true" className="text-fg-disabled">
                  /
                </span>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

/* -------------------------------------------------------------- PageHeader */

/** Internal PRD screen ids ("ADM-004", "SEC · ADM-006") are for developers: an eyebrow containing one is not shown. */
const SCREEN_CODE = /\b[A-Z]{2,4}-\d{2,4}\b/;
export function isScreenCode(text: string | undefined): boolean {
  return !!text && SCREEN_CODE.test(text);
}

/**
 * Page layout pattern: [breadcrumbs] → eyebrow → title (h1) → one-line purpose → primary action(s).
 * Website `.lx-top` (lms.css:111-113): 800-weight Plus Jakarta Sans title in ink-2, muted subline.
 */
export function PageHeader({
  title,
  description,
  actions,
  eyebrow,
  breadcrumbs,
  back,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  eyebrow?: string;
  breadcrumbs?: Crumb[];
  /** Simple "← Back to X" link (use instead of breadcrumbs on shallow pages). */
  back?: { href: string; label: string };
}) {
  return (
    <header className="mb-6 space-y-3 sm:mb-8">
      {breadcrumbs?.length ? <Breadcrumbs items={breadcrumbs} /> : null}
      {back ? (
        <Link
          href={back.href}
          className="inline-flex min-h-6 items-center gap-1 text-[0.8125rem] font-semibold text-fg-secondary no-underline hover:text-brand focus-visible:shadow-focus focus-visible:outline-none"
        >
          <span aria-hidden="true">←</span> {back.label}
        </Link>
      ) : null}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          {eyebrow && !isScreenCode(eyebrow) ? <p className="mb-1 font-display text-xs font-bold uppercase tracking-[0.12em] text-accent">{eyebrow}</p> : null}
          <h1 className="font-display text-2xl font-extrabold tracking-tight text-fg-heading sm:text-[1.75rem] sm:leading-9">{title}</h1>
          {description ? <p className="mt-1.5 max-w-prose text-[0.9375rem] text-fg-secondary">{description}</p> : null}
        </div>
        {actions ? <div className="flex shrink-0 flex-wrap gap-2">{actions}</div> : null}
      </div>
    </header>
  );
}

/* -------------------------------------------------------------- Pagination */

export interface CursorPaginationProps {
  /** True when the server returned page.has_more. */
  hasMore: boolean;
  /** True when there is a previous page in the client-side cursor stack. */
  hasPrevious: boolean;
  onNext: () => void;
  onPrevious: () => void;
  loading?: boolean;
  label?: string;
}

/**
 * Cursor pagination (api-specification §1.10: opaque cursors, no total counts). Keep a
 * stack of cursors client-side for "Previous" (nextCursorStack / previousCursorStack).
 */
export function Pagination({ hasMore, hasPrevious, onNext, onPrevious, loading, label = "Pagination" }: CursorPaginationProps) {
  return (
    <nav aria-label={label} className="flex items-center justify-end gap-2 pt-4">
      <Button variant="secondary" size="sm" onClick={onPrevious} disabled={!hasPrevious || loading}>
        Previous
      </Button>
      <Button variant="secondary" size="sm" onClick={onNext} disabled={!hasMore || loading}>
        Next
      </Button>
    </nav>
  );
}

/** Cursor stack: [undefined (first page), c1, c2, ...]; the last entry is the current page. */
export function nextCursorStack(stack: (string | undefined)[], next: string | null): (string | undefined)[] {
  return next ? [...stack, next] : stack;
}

export function previousCursorStack(stack: (string | undefined)[]): (string | undefined)[] {
  return stack.length > 1 ? stack.slice(0, -1) : stack;
}
