"use client";

import { useCallback, useEffect, useState } from "react";
import { Badge, type BadgeTone, Button, Dialog, ErrorState, FormField, Input, LoadingBlock, useToast } from "@/components/ui";
import { ApiError } from "@/lib/api/errors";
import { TextArea, safeExternalUrl, useFailToast } from "@/features/trainer/shared/ui";
import { engineLabel, fmtMarks, itemTypeLabel, staffApi } from "./api";
import { AnswerView, QuestionText } from "./AnswerView";
import type { FinalizeIn, ReviewItem, ReviewOut } from "./types";

export interface ItemDraft {
  marks: string;
  feedback: string;
  reason: string;
}

const SOURCE: Record<string, { label: string; tone: BadgeTone }> = {
  auto: { label: "Auto", tone: "info" },
  ai: { label: "AI", tone: "brand" },
  human: { label: "Human", tone: "success" },
};

export function initialDraft(i: ReviewItem): ItemDraft {
  const marks = i.final_marks ?? i.suggested_marks;
  return { marks: marks === null || marks === undefined ? "" : String(marks), feedback: i.final_feedback_md ?? i.ai?.feedback_md ?? "", reason: "" };
}

/** An override reason is needed when the entered marks differ from the system's suggestion. */
export function needsReason(i: ReviewItem, d: ItemDraft): boolean {
  if (i.suggested_marks === null || i.suggested_marks === undefined || d.marks.trim() === "") return false;
  return Math.abs(Number(d.marks) - i.suggested_marks) > 1e-9;
}

/** Validate drafts and build the finalize body; errors are keyed by item id. */
export function buildFinalize(items: ReviewItem[], drafts: Record<string, ItemDraft>): { body: FinalizeIn | null; errors: Record<string, Partial<Record<keyof ItemDraft, string>>> } {
  const errors: Record<string, Partial<Record<keyof ItemDraft, string>>> = {};
  const out: FinalizeIn["items"] = [];
  for (const i of items) {
    const d = drafts[i.id] ?? initialDraft(i);
    const e: Partial<Record<keyof ItemDraft, string>> = {};
    const m = Number(d.marks);
    if (d.marks.trim() === "" || !Number.isFinite(m)) e.marks = "Enter marks.";
    else if (m < 0) e.marks = "Marks can't be negative.";
    else if (m > i.marks) e.marks = `At most ${fmtMarks(i.marks)}.`;
    const reasonNeeded = needsReason(i, d);
    if (reasonNeeded && d.reason.trim().length < 5) e.reason = "Explain the change (at least 5 characters).";
    if (Object.keys(e).length) errors[i.id] = e;
    out.push({
      item_id: i.id,
      marks: m,
      ...(d.feedback.trim() ? { feedback_md: d.feedback.trim() } : {}),
      ...(reasonNeeded ? { override_reason: d.reason.trim() } : {}),
    });
  }
  return { body: Object.keys(errors).length ? null : { items: out }, errors };
}

function aiNote(i: ReviewItem): string | null {
  const ai = i.ai;
  if (!ai || ai.status === "none") return null;
  if (ai.status === "queued" || ai.status === "pending") return "AI grading in progress…";
  if (ai.status === "failed") return `AI grading failed${ai.error ? `: ${ai.error}` : ""}.`;
  if (ai.confidence !== null && ai.confidence < 0.6) return `AI is unsure about this mark (confidence ${Math.round(ai.confidence * 100)}%). Check it carefully.`;
  return null;
}

/** "Review — learner" modal: per-item answer, suggestion, marks + feedback, finalize. */
export function ReviewModal({ submissionId, onClose, onFinalized }: { submissionId: string | null; onClose: () => void; onFinalized: () => void | Promise<void> }) {
  const toast = useToast();
  const fail = useFailToast();
  const [data, setData] = useState<ReviewOut | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [drafts, setDrafts] = useState<Record<string, ItemDraft>>({});
  const [errors, setErrors] = useState<Record<string, Partial<Record<keyof ItemDraft, string>>>>({});
  const [busy, setBusy] = useState<"ai" | "finalize" | null>(null);
  const [fileBusy, setFileBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!submissionId) return;
    setError(null);
    try {
      const r = await staffApi.review(submissionId);
      setData(r);
      setDrafts(Object.fromEntries(r.sections.flatMap((s) => s.items).map((i) => [i.id, initialDraft(i)])));
      setErrors({});
    } catch (err) {
      setError(err);
    }
  }, [submissionId]);

  useEffect(() => {
    setData(null);
    void load();
  }, [load]);

  const items = data ? data.sections.flatMap((s) => s.items) : [];
  const setDraft = (id: string, patch: Partial<ItemDraft>) => setDrafts((d) => ({ ...d, [id]: { ...d[id]!, ...patch } }));

  const runAI = async () => {
    if (!submissionId) return;
    setBusy("ai");
    try {
      const r = await staffApi.runSubmissionAIGrading(submissionId);
      toast.show({ tone: "info", title: "AI grading started", description: `${r.queued_items} answer(s) queued, ${r.auto_scored_items} scored by rules.` });
      await load();
    } catch (err) {
      fail(err, "Couldn't start AI grading");
    } finally {
      setBusy(null);
    }
  };

  const finalize = async () => {
    if (!submissionId) return;
    const { body, errors: errs } = buildFinalize(items, drafts);
    setErrors(errs);
    if (!body) return;
    setBusy("finalize");
    try {
      const r = await staffApi.finalize(submissionId, body);
      setData(r);
      toast.show({ tone: "success", title: "Marks finalized" });
      await onFinalized();
      onClose();
    } catch (err) {
      if (err instanceof ApiError && err.problem?.errors?.length) {
        const fe: typeof errs = {};
        for (const e of err.problem.errors) {
          const m = /^(?:body\.)?items\.(\d+)\.(marks|override_reason|feedback_md)$/.exec(e.field);
          const it = m ? items[Number(m[1])] : undefined;
          if (it && m) {
            const k = m[2] === "override_reason" ? "reason" : m[2] === "feedback_md" ? "feedback" : "marks";
            fe[it.id] = { ...fe[it.id], [k]: e.message };
          }
        }
        if (Object.keys(fe).length) setErrors(fe);
        else fail(err, "Couldn't finalize");
      } else {
        fail(err, "Couldn't finalize");
      }
    } finally {
      setBusy(null);
    }
  };

  const openFile = async (key: string, localIndex: number) => {
    if (!data) return;
    const all = data.submission.file_s3_keys ?? [];
    const idx = all.indexOf(key);
    setFileBusy(key);
    try {
      const r = await staffApi.fileUrl(data.submission.id, idx >= 0 ? idx : localIndex);
      const url = safeExternalUrl(r.url);
      if (url) window.open(url, "_blank", "noopener,noreferrer");
    } catch (err) {
      fail(err, "Couldn't open the file");
    } finally {
      setFileBusy(null);
    }
  };

  const numbers = new Map(items.map((i, idx) => [i.id, idx + 1]));
  return (
    <Dialog
      open={submissionId !== null}
      onClose={onClose}
      dismissible={busy === null}
      title={data ? `Review — ${data.learner.name ?? data.learner.email ?? "Learner"}` : "Review"}
      description={
        data ? `Suggested ${fmtMarks(data.totals.suggested)} / ${fmtMarks(data.totals.max)}${data.totals.final !== null ? ` · finalized ${fmtMarks(data.totals.final)}` : ""}` : undefined
      }
      className="max-w-4xl"
      footer={
        <>
          <Button variant="secondary" onClick={() => void runAI()} loading={busy === "ai"} disabled={!data || busy !== null}>
            Run AI grading
          </Button>
          <Button variant="secondary" onClick={onClose} disabled={busy !== null}>
            Close
          </Button>
          <Button onClick={() => void finalize()} loading={busy === "finalize"} disabled={!data || busy !== null}>
            Finalize &amp; save
          </Button>
        </>
      }
    >
      {error ? (
        <ErrorState error={error} onRetry={() => void load()} />
      ) : !data ? (
        <LoadingBlock rows={3} label="Loading" size="row" />
      ) : (
        <div className="max-h-[65vh] space-y-6 overflow-y-auto pr-1">
          {data.sections.map((s) => (
            <section key={s.id} aria-label={s.title} className="space-y-4">
              <h3 className="font-display text-sm font-semibold uppercase tracking-wide text-fg-muted">
                {s.title} <span className="font-normal normal-case">· {engineLabel(s.engine)}</span>
              </h3>
              {s.items.map((i) => {
                const num = numbers.get(i.id) ?? 0;
                const d = drafts[i.id] ?? initialDraft(i);
                const e = errors[i.id] ?? {};
                const src = i.source ? SOURCE[i.source] : null;
                const note = aiNote(i);
                return (
                  <article key={i.id} className="rounded-lg border border-line p-4" aria-label={`Question ${num}`}>
                    <header className="flex flex-wrap items-center gap-2">
                      <span className="font-semibold text-fg">Q{num}.</span>
                      <Badge>{itemTypeLabel(i.item_type)}</Badge>
                      {src ? <Badge tone={src.tone}>{src.label}</Badge> : <Badge>Not graded</Badge>}
                      <span className="ml-auto text-sm tabular-nums text-fg-muted">/ {fmtMarks(i.marks)}</span>
                    </header>
                    <QuestionText prompt_md={i.prompt_md} stem_html={i.stem_html} className="mt-2" />
                    <div className="mt-3">
                      <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-fg-muted">Learner&apos;s answer</p>
                      <AnswerView
                        itemType={i.item_type}
                        response={i.response}
                        options={i.options}
                        code={i.code}
                        renderFile={(k, idx) => (
                          <Button size="sm" variant="secondary" loading={fileBusy === k} onClick={() => void openFile(k, idx)} aria-label={`Download ${k.split("/").pop()}`}>
                            Download
                          </Button>
                        )}
                      />
                    </div>
                    {note ? <p className="mt-2 text-xs text-warning-fg">{note}</p> : null}
                    <div className="mt-3 grid gap-3 sm:grid-cols-[8rem_1fr]">
                      <FormField label={`Marks for Q${num}`} error={e.marks} hint={i.suggested_marks !== null ? `Suggested: ${fmtMarks(i.suggested_marks)}` : undefined}>
                        {(p) => <Input {...p} type="number" min={0} max={i.marks} step="any" inputMode="decimal" value={d.marks} onChange={(ev) => setDraft(i.id, { marks: ev.target.value })} />}
                      </FormField>
                      <FormField label={`Feedback for Q${num}`} error={e.feedback}>
                        {(p) => <TextArea {...p} rows={2} maxLength={10000} value={d.feedback} onChange={(ev) => setDraft(i.id, { feedback: ev.target.value })} />}
                      </FormField>
                    </div>
                    {needsReason(i, d) ? (
                      <div className="mt-3">
                        <FormField label={`Reason for changing the suggested mark (Q${num})`} required error={e.reason}>
                          {(p) => <Input {...p} value={d.reason} maxLength={1000} onChange={(ev) => setDraft(i.id, { reason: ev.target.value })} />}
                        </FormField>
                      </div>
                    ) : null}
                  </article>
                );
              })}
            </section>
          ))}
        </div>
      )}
    </Dialog>
  );
}
