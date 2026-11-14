"use client";

import { useId, useLayoutEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Button, Dialog, FormField, InlineProblem, KeyValueList, Select, StatusBadge } from "@/components/ui";
import type { ApprovalPending } from "@/lib/api/client";
import { cellText, formatCountdown, formatDateTime, humanize, type MutationOutcome } from "../lib/console";

/* ------------------------------------------------------------ InlineProblem */

/** Inline problem (title/detail/reference) for a failed action inside a dialog or panel (kit version). */
export { InlineProblem };

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
  /**
   * Called each time the dialog opens (closed -> open), before paint. Use it to reset the
   * dialog's field state so text typed for one action can never be submitted with another
   * (audit 0.5). Don't reset fields here that the opener pre-fills.
   */
  onOpen?: () => void;
  /** Label of the dismiss button (default "Cancel"); set it when the submit label also says "Cancel". */
  cancelLabel?: string;
  children?: ReactNode;
}

/**
 * Confirm-and-submit dialog for console actions. Shows inline problems, and turns a 202
 * approval_pending into the "waiting for a second approver" state instead of closing.
 * Step-up (401 step_up_required) is handled globally by the API client + StepUpDialog.
 */
export function ActionDialog<T>({ open, onClose, title, description, submitLabel, danger, onSubmit, onDone, validate, onOpen, cancelLabel = "Cancel", children }: ActionDialogProps<T>) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [clientError, setClientError] = useState<string | null>(null);
  const [pending, setPending] = useState<ApprovalPending | null>(null);

  // Fresh dialog on every open: clear our own state and let the caller reset its fields.
  const onOpenRef = useRef(onOpen);
  onOpenRef.current = onOpen;
  const wasOpen = useRef(false);
  useLayoutEffect(() => {
    if (open && !wasOpen.current) {
      setError(null);
      setClientError(null);
      setPending(null);
      onOpenRef.current?.();
    }
    wasOpen.current = open;
  }, [open]);

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
              {cancelLabel}
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

/* ------------------------------------------------------------ ConfirmDialog */

/** Plain "are you sure?" step before an irreversible or learner-visible action (audit 0.7): the kit ConfirmDialog. */
export { ConfirmDialog, type ConfirmDialogProps } from "@/components/ui";

/* --------------------------------------------------------------- TextArea */

/** The kit Textarea (same look as Input); kept under this name for existing importers. */
export { TextArea } from "@/components/ui";

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

/* --------------------------------------------- KeyValueList / FilterBar (kit) */

export { FilterBar, KeyValueList } from "@/components/ui";

/* ---------------------------------------------------------------- StateBadge */

/**
 * Status pill for console records. Tone comes from the shared kit vocabulary (STATUS_VOCABULARY),
 * so a state has the same colour here as in every other portal; text is always present.
 */
export function StateBadge({ state, label }: { state: string | null | undefined; label?: string }) {
  if (!state) return <span className="text-fg-muted">—</span>;
  return <StatusBadge status={state} label={label ?? humanize(state)} />;
}

/* ---------------------------------------------------------------- JsonBlock */

/**
 * Raw JSON for staff who need the exact payload (audit 1.11). Collapsed by default under a
 * "Raw data" disclosure so the readable summary (ValueSummary, KeyValueList, a table) comes first;
 * pass `collapsed={false}` only where JSON is the point (e.g. a selector editor preview).
 */
export function JsonBlock({ value, label, collapsed = true }: { value: unknown; label: string; collapsed?: boolean }) {
  const pre = (
    <pre aria-label={label} className="max-h-80 overflow-auto rounded-md border border-line bg-surface-sunken p-3 font-mono text-xs text-fg">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
  if (!collapsed) return pre;
  return (
    <details className="group rounded-md text-sm">
      <summary className="inline-flex min-h-6 cursor-pointer items-center gap-1 font-medium text-fg-secondary hover:text-fg focus-visible:shadow-focus focus-visible:outline-none">
        Raw data<span className="sr-only">: {label}</span>
      </summary>
      <div className="mt-2">{pre}</div>
    </details>
  );
}

/* ------------------------------------------------------------- ValueSummary */

type Plain = Record<string, unknown>;
const isPlain = (v: unknown): v is Plain => typeof v === "object" && v !== null && !Array.isArray(v);
const isScalar = (v: unknown) => v === null || v === undefined || typeof v !== "object";

function SummaryValue({ value, depth, labels }: { value: unknown; depth: number; labels?: Record<string, string> }): ReactNode {
  const label = (k: string) => labels?.[k] ?? humanize(k);
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="text-fg-muted">None</span>;
    if (value.every(isScalar)) return cellText(value);
    if (depth >= 2) return `${value.length} item${value.length === 1 ? "" : "s"}`;
    return (
      <ol className="space-y-2">
        {value.slice(0, 20).map((v, i) => (
          <li key={i} className="rounded-md border border-line p-2">
            <SummaryValue value={v} depth={depth + 1} labels={labels} />
          </li>
        ))}
        {value.length > 20 ? <li className="text-xs text-fg-muted">…and {value.length - 20} more (see raw data)</li> : null}
      </ol>
    );
  }
  if (isPlain(value)) {
    const entries = Object.entries(value);
    if (entries.length === 0) return <span className="text-fg-muted">None</span>;
    if (depth >= 2) return `${entries.length} field${entries.length === 1 ? "" : "s"}`;
    return (
      <KeyValueList
        columns={depth === 0 ? 2 : 1}
        items={entries.map(([k, v]) => ({ key: k, label: label(k), value: isScalar(v) ? cellText(v) : <SummaryValue value={v} depth={depth + 1} labels={labels} />, wide: !isScalar(v) }))}
      />
    );
  }
  return cellText(value);
}

/**
 * Readable rendering of an API payload (audit before/after, approval payloads, reconciliation
 * mismatches, shadow reports): scalar fields as a key/value list with humanized keys, nested
 * objects as indented lists, and the exact JSON under a collapsed "Raw data" disclosure.
 */
export function ValueSummary({ value, label, labels, raw = true }: { value: unknown; label: string; labels?: Record<string, string>; raw?: boolean }) {
  return (
    <div className="space-y-3" aria-label={label} role="group">
      <div className="text-sm">
        <SummaryValue value={value} depth={0} labels={labels} />
      </div>
      {raw ? <JsonBlock label={label} value={value} /> : null}
    </div>
  );
}

/* ------------------------------------------------------------- linkButton */

/** Small secondary-looking link: 44px touch target on phones/tablets, 36px from `md` (WCAG 2.5.8). */
export const linkButton =
  "inline-flex min-h-touch md:min-h-9 items-center justify-center rounded-md border border-line-control bg-surface px-3 text-sm font-medium text-fg hover:bg-surface-hover focus-visible:shadow-focus focus-visible:outline-none";

export const textLink = "font-medium text-fg-link underline-offset-2 hover:text-fg-link-hover hover:underline focus-visible:shadow-focus focus-visible:outline-none";
