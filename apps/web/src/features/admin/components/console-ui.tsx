"use client";

import { useId, useState, type FormEvent, type ReactNode } from "react";
import { Badge, Button, Dialog, FormField, Select, type BadgeTone } from "@/components/ui";
import type { ApprovalPending } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { cn } from "@/lib/ui/cn";
import { formatCountdown, formatDateTime, humanize, type MutationOutcome } from "../lib/console";

/* ------------------------------------------------------------ InlineProblem */

/** Inline problem (title/detail/reference) for a failed action inside a dialog or panel. */
export function InlineProblem({ error }: { error: unknown }) {
  if (!error) return null;
  const api = error instanceof ApiError ? error : null;
  return (
    <div role="alert" className="rounded-lg border border-danger-border bg-danger-subtle p-3 text-sm">
      <p className="font-semibold text-danger-fg">{api?.title ?? "Something went wrong"}</p>
      <p className="mt-0.5 text-fg-secondary">{api?.detail ?? "Please try again."}</p>
      {api?.requestId ? (
        <p className="mt-1 text-xs text-fg-muted">
          Reference: <span className="select-all font-mono">{api.requestId}</span>
        </p>
      ) : null}
    </div>
  );
}

/* ---------------------------------------------------- ApprovalPendingNotice */

/** 202 dual-control result (api-specification §1.7): who must approve and when it expires. */
export function ApprovalPendingNotice({ approval, title = "Waiting for a second approver" }: { approval: Pick<ApprovalPending, "approval_request_id"> & Partial<ApprovalPending>; title?: string }) {
  return (
    <div role="status" className="rounded-lg border border-info-border bg-info-subtle p-3 text-sm">
      <p className="font-semibold text-info-fg">
        <span aria-hidden="true">ⓘ </span>
        {title}
      </p>
      <p className="mt-0.5 text-fg-secondary">
        {approval.required_approver_role ? `Another ${humanize(approval.required_approver_role).toLowerCase()} must approve this. ` : "Another approver must approve this. "}
        {approval.expires_at ? `Expires ${formatCountdown(approval.expires_at)} (${formatDateTime(approval.expires_at)}).` : "Requests expire after 72 h."}
      </p>
      <p className="mt-1 text-xs text-fg-muted">
        Approval request <span className="select-all font-mono">{approval.approval_request_id}</span>
      </p>
    </div>
  );
}

/* ------------------------------------------------------------- ActionDialog */

export interface ActionDialogProps<T> {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: ReactNode;
  submitLabel: string;
  danger?: boolean;
  /** Return the mutation outcome; throw ApiError to show it inline. */
  onSubmit: () => Promise<MutationOutcome<T>>;
  /** Called after a 2xx (not approval_pending). Return a message to keep the dialog open with it. */
  onDone?: (outcome: MutationOutcome<T>) => void;
  /** Client validation: return an error message to block submit. */
  validate?: () => string | null;
  children?: ReactNode;
}

/**
 * Confirm-and-submit dialog for console actions. Shows inline problems, and turns a 202
 * approval_pending into the "waiting for a second approver" state instead of closing.
 * Step-up (401 step_up_required) is handled globally by the API client + StepUpDialog.
 */
export function ActionDialog<T>({ open, onClose, title, description, submitLabel, danger, onSubmit, onDone, validate, children }: ActionDialogProps<T>) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [clientError, setClientError] = useState<string | null>(null);
  const [pending, setPending] = useState<ApprovalPending | null>(null);

  const close = () => {
    setError(null);
    setClientError(null);
    setPending(null);
    onClose();
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const msg = validate?.() ?? null;
    setClientError(msg);
    if (msg) return;
    setBusy(true);
    setError(null);
    try {
      const outcome = await onSubmit();
      if (outcome.kind === "approval_pending") {
        setPending(outcome.approval);
        onDone?.(outcome);
      } else {
        onDone?.(outcome);
        close();
      }
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={close} title={title} description={description} dismissible={!busy}>
      {pending ? (
        <div className="space-y-4">
          <ApprovalPendingNotice approval={pending} />
          <div className="flex justify-end">
            <Button variant="secondary" onClick={close}>
              Close
            </Button>
          </div>
        </div>
      ) : (
        <form onSubmit={submit} className="space-y-4" noValidate>
          {children}
          {clientError ? (
            <p role="alert" className="text-sm font-medium text-danger-fg">
              {clientError}
            </p>
          ) : null}
          <InlineProblem error={error} />
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="secondary" onClick={close} disabled={busy}>
              Cancel
            </Button>
            <Button type="submit" variant={danger ? "danger" : "primary"} loading={busy}>
              {submitLabel}
            </Button>
          </div>
        </form>
      )}
    </Dialog>
  );
}

/* --------------------------------------------------------------- TextArea */

export function TextArea({ className, ...props }: React.ComponentProps<"textarea">) {
  const invalid = props["aria-invalid"] === true || props["aria-invalid"] === "true";
  return (
    <textarea
      className={cn(
        "block min-h-[6rem] w-full rounded-md border bg-surface px-3 py-2 text-sm text-fg placeholder:text-fg-muted focus-visible:shadow-focus focus-visible:outline-none",
        invalid ? "border-danger-border" : "border-line-control",
        className,
      )}
      {...props}
    />
  );
}

/* ---------------------------------------------------------------- ReasonGate */

export const SECURITY_REASON_CODES = [
  { value: "case_review", label: "Case review" },
  { value: "appeal", label: "Appeal" },
  { value: "takeover_investigation", label: "Takeover investigation" },
  { value: "qa_sample", label: "QA sample" },
];

export interface ReasonChoice {
  reason_code: string;
}

/**
 * Reason-code prompt before any per-user security view (api-specification §6: M3 tier,
 * audited `security.view.*`). Renders children only once a reason is chosen.
 */
export function ReasonGate({ title, description, children, defaultReason = "case_review" }: { title: string; description?: ReactNode; children: (choice: ReasonChoice) => ReactNode; defaultReason?: string }) {
  const [reason, setReason] = useState(defaultReason);
  const [chosen, setChosen] = useState<ReasonChoice | null>(null);
  const id = useId();
  if (chosen) return <>{children(chosen)}</>;
  return (
    <section aria-labelledby={id} className="max-w-lg rounded-xl border border-line bg-surface p-5">
      <h2 id={id} className="font-display text-base font-semibold text-fg">
        {title}
      </h2>
      <p className="mt-1 text-sm text-fg-muted">{description ?? "Opening this view is recorded in the audit log. Choose why you need it."}</p>
      <form
        className="mt-4 space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          setChosen({ reason_code: reason });
        }}
      >
        <FormField label="Reason" required>
          {(f) => <Select {...f} value={reason} onChange={(e) => setReason(e.target.value)} options={SECURITY_REASON_CODES} />}
        </FormField>
        <Button type="submit">Open</Button>
      </form>
    </section>
  );
}

/* -------------------------------------------------------------- KeyValueList */

export function KeyValueList({ items, className }: { items: { label: string; value: ReactNode }[]; className?: string }) {
  return (
    <dl className={cn("grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2", className)}>
      {items.map((it) => (
        <div key={it.label} className="min-w-0">
          <dt className="text-xs font-semibold uppercase tracking-wide text-fg-muted">{it.label}</dt>
          <dd className="break-words text-fg">{it.value ?? "—"}</dd>
        </div>
      ))}
    </dl>
  );
}

/* --------------------------------------------------------------- FilterBar */

/** Responsive row of filter controls; children are FormFields. */
export function FilterBar({ children, label = "Filters" }: { children: ReactNode; label?: string }) {
  return (
    <form role="search" aria-label={label} onSubmit={(e) => e.preventDefault()} className="mb-4 grid grid-cols-1 gap-3 rounded-xl border border-line bg-surface p-4 sm:grid-cols-2 lg:grid-cols-4">
      {children}
    </form>
  );
}

/* ---------------------------------------------------------------- StateBadge */

const STATE_TONES: Record<string, BadgeTone> = {
  open: "info",
  submitted: "info",
  under_review: "brand",
  info_requested: "warning",
  escalated: "warning",
  pending: "warning",
  awaiting_approval: "warning",
  approval_pending: "warning",
  approved: "success",
  executed: "success",
  active: "success",
  verified: "success",
  paid: "success",
  processed: "success",
  resolved: "success",
  rejected: "danger",
  failed: "danger",
  expired: "neutral",
  cancelled: "neutral",
  closed: "neutral",
  draft: "neutral",
  shadow: "info",
  retired: "neutral",
};

/** Status pill: text always present; tone is secondary. */
export function StateBadge({ state, label }: { state: string | null | undefined; label?: string }) {
  if (!state) return <span className="text-fg-muted">—</span>;
  return <Badge tone={STATE_TONES[state] ?? "neutral"}>{label ?? humanize(state)}</Badge>;
}

/* ---------------------------------------------------------------- JsonBlock */

export function JsonBlock({ value, label }: { value: unknown; label: string }) {
  return (
    <pre aria-label={label} className="max-h-80 overflow-auto rounded-md border border-line bg-surface-sunken p-3 font-mono text-xs text-fg">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

/* ------------------------------------------------------------- linkButton */

export const linkButton =
  "inline-flex h-8 items-center justify-center rounded-md border border-line-control bg-surface px-3 text-sm font-medium text-fg hover:bg-surface-hover focus-visible:shadow-focus focus-visible:outline-none";

export const textLink = "font-medium text-fg-link underline-offset-2 hover:text-fg-link-hover hover:underline focus-visible:shadow-focus focus-visible:outline-none";
