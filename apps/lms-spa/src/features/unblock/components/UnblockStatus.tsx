"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { StatusBadge, Button, Card, Dialog, ErrorState, FormField, Input, Skeleton, useToast } from "@/components/ui";
import { api } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { FormAlert } from "@/features/auth/components/shared";
import { problemFieldErrors, toFormError, type FormErrorInfo } from "@/features/auth/lib/errors";
import { cn } from "@/lib/ui/cn";
import { APL_REF, CLOSURE_COPY, EXPLANATION_MAX, EXPLANATION_MIN, NO_SECRETS_HINT, STATE_BADGE, STEPPER, looksLikeSecret, stepIndex, type UnblockState } from "../lib/copy";
import type { UnblockDetail, UnblockSla, UnblockTextBody } from "../lib/types";
import { formatDateTime } from "@/lib/format";

/**
 * Find an own request by its APL reference (GET security/unblock-requests/by-reference/{ref}).
 * The reference is never an authenticator: anything that is not the signed-in owner's own
 * request is the same 404, which this returns as null.
 */
export async function findOwnRequest(reference: string): Promise<UnblockDetail | null> {
  try {
    return await api.get<UnblockDetail>(`security/unblock-requests/by-reference/${encodeURIComponent(reference.toUpperCase())}`, { handle: { restriction: false } });
  } catch (err) {
    if (err instanceof ApiError && err.code === "not_found") return null;
    throw err;
  }
}

/** Status tracker for one request (DS §9.8), with reply / withdraw / appeal actions (UNB-07/08/09). */
export function UnblockStatusCard({ reference, requestId: knownId, sla }: { reference: string; requestId?: string; sla?: UnblockSla }) {
  const toast = useToast();
  const [requestId, setRequestId] = useState<string | null>(knownId ?? null);
  const [detail, setDetail] = useState<UnblockDetail | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [notFound, setNotFound] = useState(false);
  const [loading, setLoading] = useState(true);
  const [mode, setMode] = useState<"reply" | "appeal" | null>(null);
  const [confirmWithdraw, setConfirmWithdraw] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setNotFound(false);
    try {
      const found = knownId
        ? await api.get<UnblockDetail>(`security/unblock-requests/${encodeURIComponent(knownId)}`, { handle: { restriction: false } })
        : await findOwnRequest(reference);
      if (!found) {
        setNotFound(true);
        return;
      }
      setRequestId(found.request_id);
      setDetail(found);
    } catch (err) {
      if (err instanceof ApiError && err.code === "not_found") setNotFound(true);
      else setError(err);
    } finally {
      setLoading(false);
    }
  }, [reference, knownId]);

  useEffect(() => {
    void load();
  }, [load]);

  const withdraw = async () => {
    if (!requestId) return;
    setBusy(true);
    try {
      await api.post(`security/unblock-requests/${encodeURIComponent(requestId)}/withdraw`, {}, { idempotencyKey: true, handle: { restriction: false } });
      toast.show({ tone: "success", title: "Request withdrawn." });
      setConfirmWithdraw(false);
      await load();
    } catch (err) {
      const e = toFormError(err);
      toast.show({ tone: "danger", title: e.title, description: e.detail, requestId: e.requestId });
    } finally {
      setBusy(false);
    }
  };

  if (loading && !detail) {
    return (
      <div aria-busy="true" className="space-y-2">
        <span className="sr-only">Loading your request…</span>
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }
  if (notFound) {
    return (
      <div role="alert" className="rounded-lg border border-line bg-surface p-4 text-sm">
        <p className="font-semibold text-fg">We couldn&apos;t find request {reference} on your account</p>
        <p className="mt-1 text-fg-secondary">Check the reference in your acknowledgement message. You can only see requests for the account you&apos;re signed in to.</p>
      </div>
    );
  }
  if (error || !detail) return <ErrorState error={error} onRetry={load} />;

  const state = detail.state as UnblockState;
  const idx = stepIndex(state);
  const lastInfo = [...detail.timeline].reverse().find((t) => t.state === "info_requested");
  // SLA due dates are only returned when the request is created (UNB-01), not by the status view.
  const firstDue = sla?.first_response_due;
  const decisionDue = sla?.decision_due;

  let body: ReactNode;
  switch (state) {
    case "draft":
      body = "You've started a review request. It's saved for 7 days.";
      break;
    case "submitted":
      body = `We've received your request ${detail.reference}. A reviewer will pick it up soon.${firstDue ? ` First response by ${formatDateTime(firstDue)}.` : ""}`;
      break;
    case "under_review":
      body = `A reviewer is looking at your case.${decisionDue ? ` We'll reply by ${formatDateTime(decisionDue)}.` : ""}`;
      break;
    case "info_requested":
      body = (
        <>
          The reviewer asked: “{lastInfo?.message ?? "please add more information"}”.
          {detail.info_requested_due ? ` Please reply by ${formatDateTime(detail.info_requested_due)}.` : ""} Your review is paused until you reply.
        </>
      );
      break;
    case "escalated":
      body = `Your case is with a senior reviewer for a second check.${decisionDue ? ` We'll reply by ${formatDateTime(decisionDue)}.` : ""}`;
      break;
    case "approved":
      body = `Good news: we're lifting the pause.${detail.decision?.summary ? ` ${detail.decision.summary}` : ""} Confirm it's you with a code, then your access returns.`;
      break;
    case "rejected":
      body = (
        <>
          We&apos;ve reviewed your request and the pause stays. Reason: {detail.decision?.summary ?? "see the decision summary"}.{" "}
          {detail.appeal?.allowed ? `You can appeal once, within 14 days${detail.appeal.deadline ? ` (until ${formatDateTime(detail.appeal.deadline)})` : ""}.` : ""} You can also contact our{" "}
          <Link href={detail.grievance_route?.startsWith("/") ? detail.grievance_route : "/help/grievance"} className="text-fg-link underline">
            Grievance Officer
          </Link>
          .
        </>
      );
      break;
    case "closed":
      body = CLOSURE_COPY[detail.closure_reason ?? ""] ?? "This case is closed.";
      break;
    default:
      body = detail.state_label ?? detail.state;
  }

  const canWithdraw = state === "submitted" || state === "under_review" || state === "info_requested";

  return (
    <Card
      aria-label={`Review request ${detail.reference}`}
      title={
        <span className="flex flex-wrap items-center gap-2">
          <span className="font-mono">{detail.reference}</span>
          {detail.case_ref ? <span className="text-sm font-normal text-fg-muted">for {detail.case_ref}</span> : null}
        </span>
      }
    >
      <div className="space-y-4">
        <div className="rounded-lg border border-line bg-surface-subtle p-4" role="status">
          <StatusBadge status={state} label={STATE_BADGE[state] ?? detail.state_label ?? detail.state} />
          <p className="mt-2 text-sm text-fg-secondary">{body}</p>
        </div>

        <ol className="flex flex-col gap-2 sm:flex-row sm:gap-4" aria-label="Progress">
          {STEPPER.map((step, i) => {
            const done = i <= idx;
            const entry = detail.timeline.find((t) => (step.key === "decision" ? t.state === "approved" || t.state === "rejected" : t.state === step.key));
            return (
              <li key={step.key} className="flex items-center gap-2 text-sm" aria-current={i === idx ? "step" : undefined}>
                <span aria-hidden="true" className={cn("h-3 w-3 rounded-full border-2", done ? "border-brand bg-brand" : "border-line-strong bg-surface")} />
                <span className={done ? "font-medium text-fg" : "text-fg-muted"}>
                  {step.label}
                  {entry ? <span className="block text-xs font-normal text-fg-muted">{formatDateTime(entry.at)}</span> : null}
                  <span className="sr-only">{done ? " (done)" : " (not yet)"}</span>
                </span>
              </li>
            );
          })}
        </ol>

        {mode ? (
          <ReplyForm
            mode={mode}
            requestId={requestId!}
            onCancel={() => setMode(null)}
            onDone={async () => {
              setMode(null);
              await load();
            }}
          />
        ) : (
          <div className="flex flex-wrap gap-2">
            {state === "info_requested" ? <Button onClick={() => setMode("reply")}>Reply</Button> : null}
            {state === "rejected" && detail.appeal?.allowed ? <Button onClick={() => setMode("appeal")}>Appeal</Button> : null}
            {canWithdraw ? (
              <Button variant="ghost" onClick={() => setConfirmWithdraw(true)}>
                Withdraw request
              </Button>
            ) : null}
          </div>
        )}
      </div>

      <Dialog
        open={confirmWithdraw}
        onClose={() => setConfirmWithdraw(false)}
        dismissible={!busy}
        title="Withdraw this request?"
        description="Your case stays open and the pause stays until it ends. You can send a new request later (up to 3 in 30 days)."
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirmWithdraw(false)} disabled={busy}>
              Keep request
            </Button>
            <Button variant="danger" loading={busy} onClick={withdraw}>
              Withdraw
            </Button>
          </>
        }
      />
    </Card>
  );
}

function ReplyForm({ mode, requestId, onCancel, onDone }: { mode: "reply" | "appeal"; requestId: string; onCancel: () => void; onDone: () => void | Promise<void> }) {
  const toast = useToast();
  const [text, setText] = useState("");
  const [fieldErr, setFieldErr] = useState<string | undefined>();
  const [error, setError] = useState<FormErrorInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const alertRef = useRef<HTMLDivElement>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const t = text.trim();
    if (t.length < EXPLANATION_MIN) return setFieldErr(`Write at least ${EXPLANATION_MIN} characters.`);
    if (t.length > EXPLANATION_MAX) return setFieldErr(`Use ${EXPLANATION_MAX.toLocaleString("en-IN")} characters or fewer.`);
    if (looksLikeSecret(t)) return setFieldErr(NO_SECRETS_HINT);
    setFieldErr(undefined);
    setBusy(true);
    setError(null);
    try {
      const path = `security/unblock-requests/${encodeURIComponent(requestId)}/${mode === "reply" ? "responses" : "appeal"}`;
      const body: UnblockTextBody = { explanation: t, attachment_ids: [] };
      await api.post(path, body, { idempotencyKey: true, handle: { restriction: false } });
      toast.show({ tone: "success", title: mode === "reply" ? "Reply sent." : "Appeal sent. A different, senior reviewer will look at it." });
      await onDone();
    } catch (err) {
      const f = problemFieldErrors(err);
      if (err instanceof ApiError && err.code === "dlp_rejected") setFieldErr(NO_SECRETS_HINT);
      else if (f.explanation) setFieldErr(f.explanation);
      else {
        setError(toFormError(err));
        setTimeout(() => alertRef.current?.focus(), 0);
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} noValidate className="space-y-3">
      <FormAlert ref={alertRef} error={error} />
      <FormField label={mode === "reply" ? "Your reply" : "Why should we look again?"} hint={`${NO_SECRETS_HINT} ${text.length}/${EXPLANATION_MAX}`} error={fieldErr} required>
        {(f) => (
          <textarea
            {...f}
            rows={5}
            maxLength={EXPLANATION_MAX}
            value={text}
            onChange={(e) => setText(e.target.value)}
            className="block w-full rounded-md border border-line-control bg-surface p-3 text-sm text-fg focus-visible:shadow-focus focus-visible:outline-none aria-[invalid=true]:border-danger-border"
          />
        )}
      </FormField>
      <div className="flex gap-2">
        <Button type="submit" loading={busy}>
          {mode === "reply" ? "Send reply" : "Send appeal"}
        </Button>
        <Button variant="ghost" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

/** Status lookup by APL reference (own requests only). */
export function UnblockLookup({ initialReference }: { initialReference?: string | null }) {
  const [value, setValue] = useState(initialReference ?? "");
  const [ref, setRef] = useState<string | null>(initialReference && APL_REF.test(initialReference) ? initialReference : null);
  const [err, setErr] = useState<string | undefined>();

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const v = value.trim().toUpperCase();
    if (!APL_REF.test(v)) {
      setErr("Enter the reference from your acknowledgement, like APL-2611-3HX9RB.");
      return;
    }
    setErr(undefined);
    setRef(v);
  };

  return (
    <div className="space-y-4">
      <form onSubmit={submit} noValidate className="flex flex-col gap-3 sm:flex-row sm:items-end">
        <div className="flex-1">
          <FormField label="Request reference" hint="Starts with APL-. You'll find it in the acknowledgement we sent you." error={err}>
            {(f) => <Input {...f} name="reference" autoComplete="off" spellCheck={false} className="font-mono uppercase" value={value} onChange={(e) => setValue(e.target.value)} />}
          </FormField>
        </div>
        <Button type="submit" variant="secondary" className={err ? "sm:mb-6" : undefined}>
          Check status
        </Button>
      </form>
      {ref ? (
        <div>
          <p className="sr-only" aria-live="polite">
            Showing request {ref}
          </p>
          <UnblockStatusCard key={ref} reference={ref} />
        </div>
      ) : null}
    </div>
  );
}
