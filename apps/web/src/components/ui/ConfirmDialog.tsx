"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { ApiError } from "@/lib/api/errors";
import { Button } from "./Button";
import { Dialog } from "./Dialog";

/** "body.new_password" / "full_name" -> "New password" / "Full name" for inline field errors. */
function humanField(field: string): string {
  const last = field.split(".").pop() || field;
  const words = last.replace(/_/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : field;
}

/** Inline problem (title / detail / reference) for a failed action inside a dialog or panel. */
export function InlineProblem({ error }: { error: unknown }) {
  if (!error) return null;
  const api = error instanceof ApiError ? error : null;
  const raw = (api?.problem as { errors?: { field?: string; message?: string }[] } | null)?.errors ?? [];
  const fieldErrors = raw
    .filter((e) => e && typeof e.message === "string" && e.message)
    .map((e) => (e.field ? `${humanField(e.field)}: ${e.message}` : String(e.message)))
    .slice(0, 5);
  return (
    <div role="alert" className="rounded-lg border border-danger-border bg-danger-subtle p-3 text-sm">
      <p className="font-semibold text-danger-fg">{api?.title ?? "Something went wrong"}</p>
      {fieldErrors.length ? (
        // say which field and why (e.g. "Starting password: Choose a longer or less common password")
        <ul className="mt-1 list-disc space-y-0.5 pl-5 text-fg-secondary">
          {fieldErrors.map((e, i) => (
            <li key={i}>{e}</li>
          ))}
        </ul>
      ) : api?.detail && api.detail !== api.title ? (
        <p className="mt-0.5 text-fg-secondary">{api.detail}</p>
      ) : !api ? (
        <p className="mt-0.5 text-fg-secondary">Please try again.</p>
      ) : null}
      {api?.requestId ? (
        <p className="mt-1 text-xs text-fg-muted">
          Reference: <span className="select-all font-mono">{api.requestId}</span>
        </p>
      ) : null}
    </div>
  );
}

export interface ConfirmDialogProps {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: ReactNode;
  /** Verb-first label of the confirm button ("Delete batch"). */
  confirmLabel: string;
  /** Label of the dismiss button (default "Cancel"); set it when the confirm label also says "Cancel". */
  cancelLabel?: string;
  /** Use for irreversible actions: the confirm button becomes the red danger button. */
  danger?: boolean;
  /** Runs the confirmed action; throw (e.g. ApiError) to show the problem inline and keep the dialog open. */
  onConfirm: () => void | Promise<void>;
  /** Extra content (consequences, a reason field…). */
  children?: ReactNode;
}

/**
 * "Are you sure?" step before an irreversible or learner-visible action — use it instead of
 * `window.confirm`. Closes after `onConfirm` resolves; a thrown error is shown inline and the
 * dialog stays open. While it runs the dialog can't be dismissed and the button shows loading.
 */
export function ConfirmDialog({ open, onClose, title, description, confirmLabel, cancelLabel = "Cancel", danger, onConfirm, children }: ConfirmDialogProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const wasOpen = useRef(false);

  // A fresh dialog on every open: never show the previous attempt's problem.
  useEffect(() => {
    if (open && !wasOpen.current) setError(null);
    wasOpen.current = open;
  }, [open]);

  const close = () => {
    setError(null);
    onClose();
  };

  const confirm = async () => {
    setBusy(true);
    setError(null);
    try {
      await onConfirm();
      close();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={close}
      title={title}
      description={description}
      dismissible={!busy}
      size="sm"
      footer={
        <>
          <Button variant="secondary" onClick={close} disabled={busy}>
            {cancelLabel}
          </Button>
          <Button variant={danger ? "danger" : "primary"} loading={busy} onClick={() => void confirm()}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      {children || error ? (
        <div className="space-y-4">
          {children}
          <InlineProblem error={error} />
        </div>
      ) : null}
    </Dialog>
  );
}
