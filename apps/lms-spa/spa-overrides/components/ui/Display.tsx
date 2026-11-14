import Link from "next/link";
import type { ComponentProps, ReactNode } from "react";
import { ApiError } from "@/lib/api/errors";
import { cn } from "@/lib/ui/cn";
import { Button, LinkButton } from "./Button";

/* ---------------------------------------------------------------- Skeleton */

/** Placeholder block; decorative (the container announces loading via aria-busy). */
export function Skeleton({ className }: { className?: string }) {
  return (
    <div aria-hidden="true" className={cn("animate-pulse rounded-md bg-surface-sunken motion-reduce:animate-none", className)} />
  );
}

/** Skeleton line heights for LoadingBlock: text lines, list rows, cards. */
const loadingSizes = { line: "h-4", row: "h-12", card: "h-16" } as const;

/**
 * Loading placeholder for a whole region: one polite status with screen-reader text plus
 * decorative skeleton lines (audit S8: replaces ad-hoc copies that put aria-label on a role-less div).
 * This is the one kit loading pattern: `size="line"` (default, text), `"row"` (list rows) or
 * `"card"` (cards/tiles). `rows` is an alias of `lines`.
 */
export function LoadingBlock({
  label = "Loading…",
  lines,
  rows,
  size = "line",
  className,
}: {
  label?: string;
  lines?: number;
  rows?: number;
  size?: keyof typeof loadingSizes;
  className?: string;
}) {
  const count = Math.max(1, rows ?? lines ?? 3);
  return (
    <div role="status" aria-busy="true" className={cn(size === "line" ? "space-y-3" : "space-y-2", className)}>
      <span className="sr-only">{label}</span>
      {Array.from({ length: count }, (_, i) => (
        <Skeleton key={i} className={cn(loadingSizes[size], size === "line" && count > 1 && i === count - 1 ? "w-2/3" : "w-full")} />
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
 * Status vocabulary (docs/redesign/design-system.md §5): one tone + one human label per machine
 * status, so every page and every portal shows the same state the same way ("same status ⇒ same
 * colour"). Unknown statuses fall back to a neutral badge with the status humanised
 * ("awaiting_evaluator" → "Awaiting evaluator"). Domain wrappers (admin `StateBadge`, support
 * `TicketStatusBadge`, trainer/engage `StatusBadge`) take their tone from here and may only
 * override the label.
 *
 *   warning  waiting on someone / needs action
 *   success  done / good / on
 *   info     moving / scheduled / in motion
 *   brand    happening now / new / ready for you
 *   danger   problem / refused / stopped
 *   neutral  parked / off / ended
 */
export const STATUS_VOCABULARY: Record<string, { tone: BadgeTone; label: string }> = {
  // waiting on someone / needs action
  pending: { tone: "warning", label: "Pending" },
  pending_review: { tone: "warning", label: "Pending review" },
  in_review: { tone: "warning", label: "In review" },
  under_review: { tone: "warning", label: "Under review" },
  awaiting_payment: { tone: "warning", label: "Awaiting payment" },
  pending_payment: { tone: "warning", label: "Awaiting payment" },
  awaiting_approval: { tone: "warning", label: "Awaiting approval" },
  approval_pending: { tone: "warning", label: "Awaiting approval" },
  awaiting_requester: { tone: "warning", label: "Waiting for you" },
  pending_user: { tone: "warning", label: "Waiting on requester" },
  pending_internal: { tone: "warning", label: "With support" },
  requested: { tone: "warning", label: "Requested" },
  info_requested: { tone: "warning", label: "Info requested" },
  changes_requested: { tone: "warning", label: "Changes requested" },
  escalated: { tone: "warning", label: "Escalated" },
  proposed: { tone: "warning", label: "Proposed" },
  paused: { tone: "warning", label: "Paused" },
  grace: { tone: "warning", label: "Payment due" },
  returned: { tone: "warning", label: "Returned" },
  late: { tone: "warning", label: "Late" },
  cooling_off: { tone: "warning", label: "Cooling-off period" },
  bounced: { tone: "warning", label: "Bounced" },
  no_show_student: { tone: "warning", label: "Student no-show" },
  no_show_mentor: { tone: "warning", label: "Mentor no-show" },
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
  executed: { tone: "success", label: "Executed" },
  processed: { tone: "success", label: "Processed" },
  accepted: { tone: "success", label: "Accepted" },
  ready: { tone: "success", label: "Ready" },
  enabled: { tone: "success", label: "On" },
  // in motion
  submitted: { tone: "info", label: "Submitted" },
  auto_submitted: { tone: "info", label: "Auto-submitted" },
  scheduled: { tone: "info", label: "Scheduled" },
  planned: { tone: "info", label: "Planned" },
  confirmed: { tone: "info", label: "Confirmed" },
  in_progress: { tone: "info", label: "In progress" },
  processing: { tone: "info", label: "Processing" },
  uploading: { tone: "info", label: "Uploading" },
  created: { tone: "info", label: "Created" },
  received: { tone: "info", label: "Received" },
  identity_verification: { tone: "info", label: "Checking identity" },
  open: { tone: "info", label: "Open" },
  due: { tone: "info", label: "Due" },
  invited: { tone: "info", label: "Invited" },
  sent: { tone: "info", label: "Sent" },
  opened: { tone: "info", label: "Opened" },
  shadow: { tone: "info", label: "Shadow" },
  // happening now / new / ready for you
  live: { tone: "brand", label: "Live" },
  new: { tone: "brand", label: "New" },
  available: { tone: "brand", label: "Available" },
  // problems
  rejected: { tone: "danger", label: "Rejected" },
  failed: { tone: "danger", label: "Failed" },
  blocked: { tone: "danger", label: "Blocked" },
  suspended: { tone: "danger", label: "Suspended" },
  overdue: { tone: "danger", label: "Overdue" },
  halted: { tone: "danger", label: "Halted" },
  revoked: { tone: "danger", label: "Revoked" },
  invalidated: { tone: "danger", label: "Invalidated" },
  missed: { tone: "danger", label: "Missed" },
  // parked / off / ended
  inactive: { tone: "neutral", label: "Inactive" },
  disabled: { tone: "neutral", label: "Off" },
  draft: { tone: "neutral", label: "Draft" },
  archived: { tone: "neutral", label: "Archived" },
  retired: { tone: "neutral", label: "Retired" },
  closed: { tone: "neutral", label: "Closed" },
  finalised: { tone: "neutral", label: "Finalised" },
  expired: { tone: "neutral", label: "Expired" },
  cancelled: { tone: "neutral", label: "Cancelled" },
  canceled: { tone: "neutral", label: "Cancelled" },
  withdrawn: { tone: "neutral", label: "Withdrawn" },
  refunded: { tone: "neutral", label: "Refunded" },
  partially_refunded: { tone: "neutral", label: "Partially refunded" },
  removed: { tone: "neutral", label: "Removed" },
  graduated: { tone: "neutral", label: "Graduated" },
  locked: { tone: "neutral", label: "Locked" },
  spam: { tone: "neutral", label: "Spam" },
  not_started: { tone: "neutral", label: "Not started" },
};

export function humanizeStatus(status: string): string {
  const s = status.replace(/[_.-]+/g, " ").trim().toLowerCase();
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : status;
}

/** Tone for a machine status from the shared vocabulary (neutral when unknown). */
export function statusTone(status: string | null | undefined): BadgeTone {
  return (status && STATUS_VOCABULARY[status.toLowerCase()]?.tone) || "neutral";
}

/** Human label for a machine status from the shared vocabulary (humanised when unknown). */
export function statusLabel(status: string | null | undefined): string {
  if (!status) return "—";
  return STATUS_VOCABULARY[status.toLowerCase()]?.label ?? humanizeStatus(status);
}

export interface StatusBadgeProps {
  /** Machine status. null/undefined/"" renders a muted em dash (or `emptyLabel`), never a fake status. */
  status: string | null | undefined;
  /** Domain wording override (e.g. `status="pending" label="Awaiting evaluator"`); the tone stays the vocabulary's. */
  label?: ReactNode;
  /** Escape hatch only; prefer adding the status to STATUS_VOCABULARY so every portal agrees. */
  tone?: BadgeTone;
  /** Coloured dot before the text (default on). */
  dot?: boolean;
  emptyLabel?: ReactNode;
  className?: string;
}

/** Badge for a machine status using STATUS_VOCABULARY. `label`/`tone` override the mapping. */
export function StatusBadge({ status, label, tone, dot = true, emptyLabel, className }: StatusBadgeProps) {
  if (!status) return <span className={cn("text-fg-muted", className)}>{emptyLabel ?? "—"}</span>;
  return (
    <Badge tone={tone ?? statusTone(status)} dot={dot} className={className}>
      {label ?? statusLabel(status)}
    </Badge>
  );
}

/* -------------------------------------------------------------------- Card */

export interface CardProps extends Omit<ComponentProps<"section">, "title"> {
  title?: ReactNode;
  /** One line under the title saying what the card is for. */
  description?: ReactNode;
  actions?: ReactNode;
  /** Heading level of the title (default h2; use h3 for cards inside a titled section). */
  titleAs?: "h2" | "h3";
  /** "md" (default) is the 16px card title; "lg" is the 20px section-heading level. */
  titleSize?: "md" | "lg";
  /** "none" drops the padding (e.g. a Table or list that runs edge to edge). */
  padding?: "default" | "none";
  /** Small icon before the title (dashboard panels): a kit icon name or your own SVG. */
  icon?: IconName | ReactNode;
}

/* Website `.adm-panel` (global.css §28): white, 1px #e8ecf3 border, 18px radius, soft navy shadow; green-tinted title icon. */
export function Card({ title, description, actions, titleAs: TitleTag = "h2", titleSize = "md", padding = "default", icon, className, children, ...props }: CardProps) {
  return (
    <section className={cn("rounded-[18px] border border-[#e8ecf3] bg-surface shadow-[0_14px_30px_-28px_rgba(3,34,105,0.45)]", padding === "default" ? "p-5 sm:p-6" : "overflow-hidden", className)} {...props}>
      {title || actions || description ? (
        <header className={cn("mb-4 flex flex-wrap items-start justify-between gap-3", padding === "none" && "px-5 pt-5 sm:px-6 sm:pt-6")}>
          <div className="flex min-w-0 items-start gap-3">
            {icon ? (
              <span aria-hidden="true" className="grid h-9 w-9 shrink-0 place-items-center rounded-[10px] bg-accent-subtle text-accent [&_svg]:h-[1.125rem] [&_svg]:w-[1.125rem]">
                {isIconName(icon) ? <Icon name={icon} /> : icon}
              </span>
            ) : null}
            <div className="min-w-0 self-center">
            {title ? (
              <TitleTag className={cn("font-display font-bold text-fg-heading", titleSize === "lg" ? "text-lg font-extrabold" : "text-base")}>{title}</TitleTag>
            ) : null}
            {description ? <p className="mt-0.5 text-[0.9375rem] text-fg-muted">{description}</p> : null}
            </div>
          </div>
          {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
        </header>
      ) : null}
      {children}
    </section>
  );
}

/* ----------------------------------------------------------- SectionHeader */

/**
 * The ~20px section-heading level between the 28px page title (PageHeader h1) and the 16px card
 * title: use it above a group of cards/tiles/tables inside a page.
 */
export function SectionHeader({
  title,
  kicker,
  description,
  actions,
  as: Tag = "h2",
  id,
  className,
}: {
  title: ReactNode;
  /** Website `.eyebrow`: small uppercase green line above the heading (kicker + heading + lead). */
  kicker?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  as?: "h2" | "h3";
  id?: string;
  className?: string;
}) {
  return (
    <div className={cn("mb-4 flex flex-wrap items-end justify-between gap-3", className)}>
      <div className="min-w-0">
        {kicker ? <p className="mb-1 font-display text-xs font-bold uppercase tracking-[0.12em] text-accent">{kicker}</p> : null}
        <Tag id={id} className="font-display text-lg font-extrabold tracking-tight text-fg-heading">
          {title}
        </Tag>
        {description ? <p className="mt-0.5 max-w-prose text-[0.9375rem] text-fg-secondary">{description}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}

/* -------------------------------------------------------------- EmptyState */

/* Decorative 24px stroke icons (empty states, stat tiles, panels, quick actions). */
const ICON_PATHS = {
  home: "M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z",
  layers: "m12 3 9 5-9 5-9-5zm-9 9 9 5 9-5m-18 4 9 5 9-5",
  tag: "M3 12V4a1 1 0 0 1 1-1h8l9 9-9 9zM7.5 7.5h.01",
  receipt: "M6 3h12v18l-3-2-3 2-3-2-3 2zM9 8h6M9 12h6M9 16h3",
  refund: "M9 14 4 9l5-5M4 9h11a5 5 0 0 1 0 10h-3",
  repeat: "m17 2 3 3-3 3M3 11V9a4 4 0 0 1 4-4h13M7 22l-3-3 3-3m14-3v2a4 4 0 0 1-4 4H4",
  scale: "M12 3v18M5 21h14M6 7h12M6 7l-3 7a3 3 0 0 0 6 0zm12 0-3 7a3 3 0 0 0 6 0z",
  unlock: "M7 11V8a5 5 0 0 1 9.6-2M6 11h12a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1v-8a1 1 0 0 1 1-1z",
  sliders: "M4 6h9m4 0h3M4 12h3m4 0h9M4 18h11m4 0h1M15 4v4M9 10v4m8 2v4",
  toggle: "M8 7h8a5 5 0 0 1 0 10H8A5 5 0 0 1 8 7zm0 7.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z",
  key: "m21 3-9.4 9.4m3.9-4.9 3 3L21 8l-3-3m-6.4 7.4a5 5 0 1 1-7.07 7.07 5 5 0 0 1 7.07-7.07z",
  building: "M4 21V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v16m0-12h2a2 2 0 0 1 2 2v10M3 21h18M8 7h4m-4 4h4m-4 4h4",
  sparkles: "m12 3 1.8 4.7 4.7 1.8-4.7 1.8L12 16l-1.8-4.7-4.7-1.8 4.7-1.8zm7 12 .8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z",
  target: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zm0-4a5 5 0 1 0 0-10 5 5 0 0 0 0 10zm0-4a1 1 0 1 0 0-2 1 1 0 0 0 0 2z",
  map: "M9 4 3 6v14l6-2 6 2 6-2V4l-6 2zm0 0v14m6-12v14",
  folder: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z",
  image: "M5 4h14a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1zm-1 13 4.5-5 3.5 4 2.5-3 5.5 5M15.5 9.5h.01",
  branch: "M6 3v12m0 0a3 3 0 1 0 0 6 3 3 0 0 0 0-6zm12-6a3 3 0 1 0 0-6 3 3 0 0 0 0 6zm0 0a9 9 0 0 1-9 9",
  briefcase: "M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2M4 7h16a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V8a1 1 0 0 1 1-1zm-1 6h18",
  trending: "m3 17 6-6 4 4 8-8m-6 0h6v6",
  box: "m21 8-9-5-9 5v8l9 5 9-5zM3 8l9 5 9-5m-9 5v8",
  list: "M8 6h13M8 12h13M8 18h13M3.5 6h.01M3.5 12h.01M3.5 18h.01",
  mic: "M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3zM5 11a7 7 0 0 0 14 0m-7 7v3",
  ticket: "M4 6h16v4a2 2 0 0 0 0 4v4H4v-4a2 2 0 0 0 0-4zm10 0v12",
  panel: "M4 4h16a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1zm5 0v16",
  chevronDown: "m6 9 6 6 6-6",
  inbox: "M4 13h4l1.5 3h5l1.5-3h4M4 13l2.5-7h11l2.5 7v5a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z",
  search: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zm9 2-4-4",
  document: "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zm0 0v5h5M9 13h6M9 17h4",
  book: "M4 5.5A1.5 1.5 0 0 1 5.5 4H11v16H5.5A1.5 1.5 0 0 1 4 18.5zM13 4h5.5A1.5 1.5 0 0 1 20 5.5v13a1.5 1.5 0 0 1-1.5 1.5H13z",
  calendar: "M7 3v3m10-3v3M4 9h16M5 5h14a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z",
  chart: "M4 20h16M7 16v-5m5 5V8m5 8v-3",
  check: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zm-4-9 3 3 5-6",
  lock: "M7 11V8a5 5 0 0 1 10 0v3M6 11h12a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1v-8a1 1 0 0 1 1-1z",
  users: "M16 19v-1a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v1m6.5-9a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM21 19v-1a4 4 0 0 0-3-3.87M16 3.13a3.5 3.5 0 0 1 0 6.75",
  bell: "M18 16v-5a6 6 0 1 0-12 0v5l-2 2h16zm-8 4h4",
  code: "m8 8-4 4 4 4m8-8 4 4-4 4M14 5l-4 14",
  card: "M3 7a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2zm0 3h18M7 15h4",
  chat: "M4 5h16v11H8l-4 4z",
  award: "M12 15a6 6 0 1 0 0-12 6 6 0 0 0 0 12zm-3.5-1L7 21l5-3 5 3-1.5-7",
  shield: "M12 3 5 6v5c0 4.5 3 8.5 7 10 4-1.5 7-5.5 7-10V6z",
  hourglass: "M6 3h12M6 21h12M7 3c0 5 10 5 10 9s-10 4-10 9M17 3c0 5-10 5-10 9s10 4 10 9",
  bolt: "M13 3 5 14h6l-1 7 8-11h-6z",
  megaphone: "M3 10v4a1 1 0 0 0 1 1h3l6 4V5L7 9H4a1 1 0 0 0-1 1zm14-2a5 5 0 0 1 0 8",
  rupee: "M6 4h12M6 9h12M9 4c6 0 6 10 0 10H6l8 6",
  user: "M20 21v-1a5 5 0 0 0-5-5H9a5 5 0 0 0-5 5v1m8-9a4.5 4.5 0 1 0 0-9 4.5 4.5 0 0 0 0 9z",
  userPlus: "M15 21v-1a5 5 0 0 0-5-5H7a5 5 0 0 0-5 5v1m6.5-9a4.5 4.5 0 1 0 0-9 4.5 4.5 0 0 0 0 9zM19 8v6m3-3h-6",
  clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zm0-13v4l3 2",
  alert: "M12 9v4m0 4h.01M10.3 3.9 2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z",
  grid: "M4 4h7v7H4zm9 0h7v7h-7zM4 13h7v7H4zm9 0h7v7h-7z",
  pen: "M4 20h4L19 9l-4-4L4 16zM13.5 6.5l4 4",
  play: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zm-2-12 5 3-5 3z",
  settings: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zm7.4-3a7.4 7.4 0 0 0-.1-1.2l2-1.6-2-3.4-2.4 1a7 7 0 0 0-2-1.2L14.5 3h-5l-.4 2.6a7 7 0 0 0-2 1.2l-2.4-1-2 3.4 2 1.6a7.4 7.4 0 0 0 0 2.4l-2 1.6 2 3.4 2.4-1a7 7 0 0 0 2 1.2l.4 2.6h5l.4-2.6a7 7 0 0 0 2-1.2l2.4 1 2-3.4-2-1.6c.1-.4.1-.8.1-1.2z",
  external: "M14 4h6v6m0-6-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5",
  logout: "M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3M10 16l-4-4 4-4M6 12h10",
  arrowRight: "M5 12h14m-5-5 5 5-5 5",
} as const;

export type IconName = keyof typeof ICON_PATHS;

export function isIconName(icon: unknown): icon is IconName {
  return typeof icon === "string" && icon in ICON_PATHS;
}

/** A decorative 24px stroke icon from the kit set (always aria-hidden; label the control instead). */
export function Icon({ name, className }: { name: IconName; className?: string }) {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" className={cn("h-5 w-5", className)}>
      <path d={ICON_PATHS[name]} />
    </svg>
  );
}

export type EmptyStateIcon = IconName;

export interface EmptyStateProps {
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  /** A named topic icon ("search", "calendar", "book", …) or your own decorative SVG. Default "inbox". */
  icon?: EmptyStateIcon | ReactNode;
  /** "card" (default): dashed box for a whole region. "inline": no box, for use inside a Card. */
  variant?: "card" | "inline";
  className?: string;
}

const isEmptyIconName = isIconName;

/** "E" state (PRD §6): explanation + primary next action. Website `.lx-empty` (lms.css:48-51). */
export function EmptyState({ title, description, action, icon = "inbox", variant = "card", className }: EmptyStateProps) {
  const inline = variant === "inline";
  return (
    <div
      className={cn(
        "flex flex-col items-center text-center",
        inline ? "px-4 py-8" : "rounded-xl border border-dashed border-line-strong bg-surface px-6 py-12",
        className,
      )}
    >
      <span aria-hidden="true" className={cn("mb-3 grid place-items-center rounded-full bg-brand-subtle text-brand", inline ? "h-11 w-11" : "h-14 w-14")}>
        {isEmptyIconName(icon) ? (
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className={inline ? "h-5 w-5" : "h-6 w-6"}>
            <path d={ICON_PATHS[icon]} />
          </svg>
        ) : (
          icon
        )}
      </span>
      <p className="font-display text-base font-extrabold text-fg-heading">{title}</p>
      {description ? <p className="mt-1 max-w-prose text-[0.9375rem] text-fg-muted">{description}</p> : null}
      {action ? <div className={inline ? "mt-4" : "mt-5"}>{action}</div> : null}
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
  /** Shown as "Try again" unless the problem cannot be fixed by retrying (401/403/404/410). */
  onRetry?: () => void;
  /** HTTP status when `error` is not an ApiError (e.g. a server-rendered problem). */
  status?: number;
  /** A way out that always works, e.g. `{ href: "/app", label: "Go to dashboard" }`. */
  secondaryAction?: { href: string; label: string };
}

/** Statuses where "Try again" can never succeed: show only the way out. */
const NON_RETRYABLE = new Set([401, 403, 404, 410]);

/** "X" state (PRD §6): problem title + way out + muted reference; never a stack trace. */
export function ErrorState({ error, title, detail, requestId, onRetry, status, secondaryAction }: ErrorStateProps) {
  const api = error instanceof ApiError ? error : null;
  const heading = title ?? api?.title ?? "Something went wrong";
  const rawBody = detail ?? api?.detail ?? "Please try again.";
  // Problem responses often repeat the title as the detail; don't print it twice.
  const body = typeof rawBody === "string" && rawBody.trim().toLowerCase() === heading.trim().toLowerCase() ? null : rawBody;
  const ref = requestId ?? api?.requestId ?? null;
  const code = status ?? api?.status;
  const canRetry = Boolean(onRetry) && !(code !== undefined && NON_RETRYABLE.has(code));
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
        {body ? <p className="mt-1 text-sm text-fg-secondary">{body}</p> : null}
        {canRetry || secondaryAction ? (
          <div className="mt-3 flex flex-wrap gap-2">
            {canRetry ? (
              <Button variant="secondary" size="sm" onClick={onRetry}>
                Try again
              </Button>
            ) : null}
            {secondaryAction ? (
              <LinkButton href={secondaryAction.href} variant={canRetry ? "ghost" : "secondary"} size="sm">
                {secondaryAction.label}
              </LinkButton>
            ) : null}
          </div>
        ) : null}
        {ref ? (
          <p className="mt-3 text-xs text-fg-muted">
            Reference: <span className="select-all font-mono">{ref}</span>
          </p>
        ) : null}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------- ProgressBar */

// Lives in Progress.tsx with ProgressRing; re-exported here for existing "./Display" importers.
export { ProgressBar, ProgressRing } from "./Progress";

/* ---------------------------------------------------------------- StatTile */

/** `highlight` = the one solid-navy tile a dashboard leads with (e.g. "Active learners"). */
export type StatTileTone = "brand" | "success" | "warning" | "danger" | "neutral" | "highlight";

export interface StatTileProps {
  label: string;
  /** Pre-formatted value; pass null when unknown (renders an em dash, never a fake number). */
  value: ReactNode | null;
  hint?: ReactNode;
  trend?: { direction: "up" | "down" | "flat"; label: string };
  /** Small decorative icon: a named kit icon ("users", "document", …) or your own inline SVG. */
  icon?: IconName | ReactNode;
  /**
   * Colours the status dot before the label, e.g. `tone={pending > 0 ? "warning" : "neutral"}` on a
   * "needs attention" count. `highlight` fills the tile with the brand navy.
   */
  tone?: StatTileTone;
  /** The whole tile becomes a link to the list behind the number (e.g. the approvals queue). */
  href?: string;
  /** "compact" uses a smaller value for dense dashboards and long values. */
  size?: "default" | "compact";
  className?: string;
}

const statDotTones: Record<StatTileTone, string> = {
  brand: "bg-brand",
  success: "bg-success-solid",
  warning: "bg-warning-solid",
  danger: "bg-danger-solid",
  neutral: "bg-fg-muted",
  highlight: "bg-accent-on-brand",
};

/* Dashboard KPI card (2026-11 redesign): white card, soft shadow, a coloured status dot + label on
   top with a small tinted icon on the right, then a big 800-weight number and a muted hint.
   `highlight` is the one solid-navy card a dashboard leads with; `compact` is the small inline tile
   used inside panels. DOM order stays label → value → hint (screen readers say "Students, 1,100"). */
const kpiTones: Record<StatTileTone, { icon: string }> = {
  brand: { icon: "bg-[#eaf0fb] text-brand" },
  success: { icon: "bg-[#e4f5ec] text-[#0d7a4f]" },
  warning: { icon: "bg-[#fff4e0] text-[#a35a00]" },
  danger: { icon: "bg-danger-subtle text-danger-fg" },
  neutral: { icon: "bg-[#eef1f6] text-[#475569]" },
  highlight: { icon: "bg-white/10 text-[#8ee0b8]" },
};

export function StatTile({ label, value, hint, trend, icon, tone = "brand", href, size = "default", className }: StatTileProps) {
  const hi = tone === "highlight";
  const compact = size === "compact";
  const t = kpiTones[tone];
  const iconEl =
    icon && !compact ? (
      <span aria-hidden="true" className={cn("hidden h-9 w-9 shrink-0 place-items-center rounded-[10px] sm:grid xl:hidden 2xl:grid [&_svg]:h-[18px] [&_svg]:w-[18px]", t.icon)}>
        {isIconName(icon) ? <Icon name={icon} /> : icon}
      </span>
    ) : null;
  const body = (
    <>
      <div className="flex min-w-0 items-start justify-between gap-2">
        <p className={cn("flex min-w-0 items-center gap-1.5 font-semibold", compact ? "text-[0.8125rem]" : "text-[0.8125rem] sm:text-sm", hi ? "text-white/85" : "text-fg-secondary")}>
          <span aria-hidden="true" className={cn("h-1.5 w-1.5 shrink-0 rounded-full", statDotTones[tone])} />
          <span className="min-w-0 break-words">{label}</span>
        </p>
        {iconEl}
      </div>
      <p
        className={cn(
          "break-words font-display font-extrabold tabular-nums leading-none tracking-tight",
          hi ? "text-white" : "text-fg-heading",
          compact ? "mt-1.5 text-xl sm:text-2xl" : "mt-2 text-[1.75rem] sm:text-[2rem]",
        )}
      >
        {value ?? "—"}
      </p>
      {trend ? (
        <p className={cn("mt-1 text-xs", hi ? "text-white/80" : "text-fg-secondary")}>
          <span aria-hidden="true">{trend.direction === "up" ? "▲ " : trend.direction === "down" ? "▼ " : "■ "}</span>
          {trend.label}
        </p>
      ) : null}
      {hint ? <p className={cn("mt-1.5 text-[0.78rem] leading-snug", hi ? "text-white/75" : "text-fg-muted")}>{hint}</p> : null}
    </>
  );
  const classes = cn(
    "relative flex min-w-0 flex-col overflow-hidden border",
    compact ? "rounded-xl p-3.5 sm:p-4" : "rounded-2xl p-4 sm:p-5",
    hi
      ? "border-transparent bg-[linear-gradient(140deg,#0b3a8f,#04215f_70%)] shadow-[0_18px_36px_-22px_rgba(3,34,105,0.9)]"
      : compact
        ? "border-line-subtle bg-surface-subtle"
        : "border-[#e6eaf2] bg-surface shadow-[0_14px_34px_-24px_rgba(15,35,80,0.45)]",
    href &&
      cn(
        "group no-underline transition-[box-shadow,border-color,transform] duration-base hover:shadow-md motion-safe:hover:-translate-y-0.5 focus-visible:shadow-focus focus-visible:outline-none",
        !hi && "hover:border-[#c7d2ee]",
      ),
    className,
  );
  return href ? (
    <Link href={href} className={classes}>
      {body}
    </Link>
  ) : (
    <div className={classes}>{body}</div>
  );
}

/** Responsive grid for StatTiles: 2 per row on phones (design-system §3), up to `columns` on desktop. */
export function StatGrid({ children, columns = 4, className }: { children: ReactNode; columns?: 2 | 3 | 4 | 5 | 6; className?: string }) {
  return (
    <div
      className={cn(
        "grid grid-cols-2 gap-3 sm:gap-4",
        columns === 6 ? "md:grid-cols-3 xl:grid-cols-6" : columns === 5 ? "md:grid-cols-3 lg:grid-cols-5" : columns === 4 ? "lg:grid-cols-4" : columns === 3 ? "lg:grid-cols-3" : null,
        className,
      )}
    >
      {children}
    </div>
  );
}

/* ------------------------------------------------------------- Breadcrumbs */

export interface Crumb {
  label: ReactNode;
  /** Omit for the current page (last crumb). */
  href?: string;
}

/**
 * "Where am I" trail for pages at depth ≥ 2. The last crumb is the current page (aria-current);
 * long labels (entity names) truncate instead of wrapping the trail onto many lines.
 */
export function Breadcrumbs({ items, className }: { items: Crumb[]; className?: string }) {
  if (!items.length) return null;
  return (
    <nav aria-label="Breadcrumb" className={cn("text-[0.8125rem]", className)}>
      <ol className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-fg-muted">
        {items.map((c, i) => {
          const last = i === items.length - 1;
          return (
            <li key={i} className="flex min-w-0 max-w-full items-center gap-1.5">
              {c.href && !last ? (
                <Link
                  href={c.href}
                  className="inline-flex min-h-6 min-w-0 max-w-[16rem] items-center font-medium text-fg-secondary no-underline hover:text-brand hover:underline focus-visible:shadow-focus focus-visible:outline-none"
                >
                  <span className="truncate">{c.label}</span>
                </Link>
              ) : (
                <span aria-current={last ? "page" : undefined} className={cn("min-w-0 max-w-[20rem] truncate", last && "font-semibold text-fg")}>
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

export interface PageHeaderProps {
  /** The h1. Match the sidebar label on list pages; use the entity's name on detail pages. */
  title: ReactNode;
  description?: ReactNode;
  /** One primary action (plus secondary ones); stacks under the title on phones. */
  actions?: ReactNode;
  eyebrow?: string;
  /** Trail for depth ≥ 2, e.g. `[{ label: "Batches", href: "/admin/batches" }, { label: batch.name }]`. */
  breadcrumbs?: Crumb[];
  /** Simple "← Back to X" link (use instead of breadcrumbs on shallow pages). */
  back?: { href: string; label: string };
  /** Small items beside the title, e.g. a StatusBadge for the entity's state. */
  meta?: ReactNode;
}

/**
 * Page layout pattern: [breadcrumbs | back] → eyebrow → title (h1) [+ meta] → one-line purpose → actions.
 * Website `.lx-top` (lms.css:111-113): 800-weight Plus Jakarta Sans title in ink-2, muted subline.
 */
export function PageHeader({ title, description, actions, eyebrow, breadcrumbs, back, meta }: PageHeaderProps) {
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
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <h1 className="min-w-0 break-words font-display text-[1.5rem] font-extrabold leading-8 tracking-tight text-fg-heading sm:text-[1.75rem] sm:leading-9">{title}</h1>
            {meta ? <div className="flex flex-wrap items-center gap-2">{meta}</div> : null}
          </div>
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
