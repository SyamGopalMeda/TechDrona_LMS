"use client";

import { useCallback, useEffect, useState } from "react";
import { Badge, Button, Card, Dialog, ErrorState, FormField, LoadingBlock, Select, useToast } from "@/components/ui";
import { ApiError } from "@/lib/api/errors";
import { fmtMarks, itemTypeLabel, learnerApi, stripHtml, truncate } from "../assignment-manager/api";
import { AnswerView, QuestionText } from "../assignment-manager/AnswerView";
import type { RegradeOut, ResultItem, ResultOut } from "../assignment-manager/types";
import { formatDateTime } from "@/lib/format";

const REASON_MIN = 10;
const REASON_MAX = 2000;

/** Client check for the modification request reason (the api re-validates). */
export function reasonError(reason: string): string | null {
  const n = reason.trim().length;
  if (n < REASON_MIN) return `Explain what should be checked again (at least ${REASON_MIN} characters).`;
  if (n > REASON_MAX) return `Keep it under ${REASON_MAX} characters.`;
  return null;
}

function RegradeStatus({ r }: { r: RegradeOut }) {
  const tone = r.status === "open" ? "info" : r.status === "resolved" ? "success" : "neutral";
  const label = r.status === "open" ? "Modification request open" : r.status === "resolved" ? "Modification request resolved" : "Modification request declined";
  return (
    <div className="rounded-lg border border-line p-3 text-sm" data-testid="regrade-status">
      <Badge tone={tone}>{label}</Badge>
      <p className="mt-2 text-fg-secondary">
        Sent {formatDateTime(r.created_at, { year: true })}: {r.reason}
      </p>
      {r.resolution_note ? <p className="mt-1 text-fg">Trainer&apos;s note: {r.resolution_note}</p> : null}
    </div>
  );
}

function questionLabel(i: ResultItem, n: number): string {
  return `${n}. ${truncate(i.prompt_md ?? stripHtml(i.stem_html), 90) || itemTypeLabel(i.item_type)}`;
}

/** Learner result for a submitted structured assignment, with "Request modification". */
export function ResultsView({ assignmentId }: { assignmentId: string }) {
  const toast = useToast();
  const [data, setData] = useState<ResultOut | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [open, setOpen] = useState<ResultItem | null>(null);
  const [asking, setAsking] = useState(false);
  const [reason, setReason] = useState("");
  const [itemId, setItemId] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      setData(await learnerApi.result(assignmentId));
    } catch (err) {
      setError(err);
    }
  }, [assignmentId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (error) return <ErrorState error={error} onRetry={() => void load()} />;
  if (!data) return <LoadingBlock label="Loading result" size="card" />;

  const sub = data.submission;
  const regradeOpen = data.regrade?.status === "open";
  const items = [...data.items];

  const send = async () => {
    if (!sub) return;
    const e = reasonError(reason);
    setFormError(e);
    if (e) return;
    setBusy(true);
    try {
      await learnerApi.requestRegrade(sub.id, { reason: reason.trim(), ...(itemId ? { item_id: itemId } : {}) });
      toast.show({ tone: "success", title: "Request sent", description: "Your trainer will review it." });
      setAsking(false);
      setReason("");
      setItemId("");
      await load();
    } catch (err) {
      if (err instanceof ApiError) {
        const fe = err.problem?.errors?.find((x) => x.field.endsWith("reason"));
        setFormError(fe?.message ?? (err.code === "conflict" ? "You already have an open request." : err.detail));
      } else setFormError("Couldn't send the request. Please try again.");
    } finally {
      setBusy(false);
    }
  };

  const n = (i: ResultItem) => items.indexOf(i) + 1;

  return (
    <div className="space-y-4">
      <h1 className="font-display text-2xl font-bold text-fg">{data.assignment.title}</h1>
      <Card>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="flex items-center gap-2 font-semibold text-success-fg">
              <span aria-hidden="true">✓</span> Submitted{sub?.submitted_at ? ` on ${formatDateTime(sub.submitted_at, { year: true })}` : ""}
              {sub?.status === "late" ? <Badge tone="warning">Late</Badge> : null}
            </p>
            <p className="mt-1 text-lg tabular-nums text-fg" data-testid="final-score">
              {data.published && sub && sub.score !== null ? `Final score: ${fmtMarks(sub.score)} / ${fmtMarks(sub.max_score)}` : "Awaiting results"}
            </p>
          </div>
          {data.published && sub ? (
            <div className="flex flex-col items-start gap-1 sm:items-end">
              <Button
                variant="secondary"
                disabled={regradeOpen}
                onClick={() => {
                  setFormError(null);
                  setAsking(true);
                }}
              >
                Request modification
              </Button>
              {regradeOpen ? <p className="text-xs text-fg-muted">You can send another request once this one is answered.</p> : null}
            </div>
          ) : null}
        </div>
        {data.published && sub?.feedback_md ? <p className="mt-3 whitespace-pre-line text-sm text-fg-secondary">{sub.feedback_md}</p> : null}
      </Card>

      {data.regrade ? <RegradeStatus r={data.regrade} /> : null}

      <Card title="Questions">
        <ul className="divide-y divide-line" aria-label="Your answers">
          {items.map((i) => (
            <li key={i.id}>
              <button
                type="button"
                onClick={() => setOpen(i)}
                className="flex w-full items-center gap-3 py-3 text-left hover:bg-surface-hover focus-visible:shadow-focus focus-visible:outline-none"
                aria-label={`Open question ${n(i)}`}
              >
                <Badge>{itemTypeLabel(i.item_type)}</Badge>
                <span className="min-w-0 flex-1 truncate text-sm text-fg">{questionLabel(i, n(i))}</span>
                {i.feedback_md ? <span className="text-xs text-fg-muted">Feedback</span> : null}
                <span className="text-sm tabular-nums text-fg-secondary">
                  {data.published && i.final_marks !== null ? fmtMarks(i.final_marks) : "—"} / {fmtMarks(i.marks)}
                </span>
                <span aria-hidden="true" className="text-fg-muted">
                  ›
                </span>
              </button>
            </li>
          ))}
        </ul>
      </Card>

      <Dialog open={open !== null} onClose={() => setOpen(null)} title={open ? `Question ${n(open)}` : ""} className="max-w-2xl" footer={<Button variant="secondary" onClick={() => setOpen(null)}>Close</Button>}>
        {open ? (
          <div className="max-h-[65vh] space-y-4 overflow-y-auto">
            <QuestionText prompt_md={open.prompt_md} stem_html={open.stem_html} />
            <div>
              <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-fg-muted">Your answer</h3>
              <AnswerView itemType={open.item_type} response={open.response} options={open.options} />
            </div>
            <div>
              <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-fg-muted">Feedback</h3>
              {data.published ? (
                <>
                  <p className="text-sm tabular-nums text-fg">
                    Score: {open.final_marks !== null ? fmtMarks(open.final_marks) : "—"} / {fmtMarks(open.marks)}
                  </p>
                  <p className="mt-1 whitespace-pre-wrap text-sm text-fg-secondary">{open.feedback_md || "No feedback for this question."}</p>
                </>
              ) : (
                <p className="text-sm text-fg-muted">Feedback appears once results are published.</p>
              )}
            </div>
          </div>
        ) : null}
      </Dialog>

      <Dialog
        open={asking}
        onClose={() => setAsking(false)}
        dismissible={!busy}
        title="Request modification"
        description="Ask your trainer to look at your marks again. Explain what you think was missed."
        footer={
          <>
            <Button variant="secondary" onClick={() => setAsking(false)} disabled={busy}>
              Cancel
            </Button>
            <Button onClick={() => void send()} loading={busy}>
              Send request
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <FormField label="Question (optional)">
            {(p) => (
              <Select
                {...p}
                value={itemId}
                onChange={(e) => setItemId(e.target.value)}
                options={[{ value: "", label: "Whole assignment" }, ...items.map((i) => ({ value: i.id, label: questionLabel(i, n(i)) }))]}
              />
            )}
          </FormField>
          <FormField label="Reason" required error={formError ?? undefined} hint={`${REASON_MIN}–${REASON_MAX} characters.`}>
            {(p) => (
              <textarea
                {...p}
                rows={5}
                maxLength={REASON_MAX}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                className="block w-full rounded-md border border-line-control bg-surface px-3 py-2 text-sm text-fg focus-visible:shadow-focus focus-visible:outline-none"
              />
            )}
          </FormField>
        </div>
      </Dialog>
    </div>
  );
}
