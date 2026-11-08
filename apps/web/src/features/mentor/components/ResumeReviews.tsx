"use client";

import { useState } from "react";
import { Badge, Button, Card, EmptyState, FormField, Input, Tabs, useToast } from "@/components/ui";
import { useApi, seg } from "@/features/trainer/shared/use-api";
import { Boundary, TextArea, fieldErrorsOf, formatDateTime, useFailToast } from "@/features/trainer/shared/ui";
import { send } from "../lib/api";
import type { ResumeContent, ReviewComment, ReviewQueueItem } from "../lib/types";

export const RESUME_SECTIONS = ["summary", "education", "skills", "projects", "internships", "achievements", "certifications"] as const;

/** Read-only résumé rendering (mentor queue + student preview). */
export function ResumePreview({ content }: { content: ResumeContent }) {
  const list = (items: string[]) => (items.length ? <ul className="list-inside list-disc">{items.map((i, n) => <li key={n}>{i}</li>)}</ul> : <p className="text-fg-muted">—</p>);
  return (
    <div className="space-y-3 text-sm text-fg">
      {content.headline ? <p className="font-medium">{content.headline}</p> : null}
      {content.summary ? <p className="whitespace-pre-line text-fg-secondary">{content.summary}</p> : null}
      <section>
        <h4 className="font-semibold">Education</h4>
        {list((content.education ?? []).map((e) => [e.degree, e.field, e.institution, [e.start_year, e.end_year].filter(Boolean).join("–"), e.score].filter(Boolean).join(" · ")))}
      </section>
      <section>
        <h4 className="font-semibold">Skills</h4>
        <p>{(content.skills ?? []).join(", ") || "—"}</p>
      </section>
      <section>
        <h4 className="font-semibold">Projects</h4>
        {list((content.projects ?? []).map((p) => [p.title, p.description].filter(Boolean).join(" — ")))}
      </section>
      <section>
        <h4 className="font-semibold">Internships</h4>
        {list((content.internships ?? []).map((i) => [i.role, i.company, i.description].filter(Boolean).join(" · ")))}
      </section>
      <section>
        <h4 className="font-semibold">Achievements</h4>
        {list(content.achievements ?? [])}
      </section>
      <section>
        <h4 className="font-semibold">Certifications</h4>
        {list((content.certifications ?? []).map((c) => [c.title, c.issuer].filter(Boolean).join(" · ")))}
      </section>
    </div>
  );
}

/** Inline comments per section + summary (PLC-52). */
export function ReviewFeedbackForm({ review, onDone }: { review: ReviewQueueItem; onDone: (r: ReviewQueueItem) => void }) {
  const [comments, setComments] = useState<Record<string, string>>({});
  const [summary, setSummary] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const fail = useFailToast();
  const toast = useToast();

  async function submit() {
    const errs: Record<string, string> = {};
    if (!summary.trim()) errs.summary = "Write a short summary for the student";
    setErrors(errs);
    if (Object.keys(errs).length) return;
    const list: ReviewComment[] = RESUME_SECTIONS.filter((s) => comments[s]?.trim()).map((s) => ({ section: s, comment: comments[s]!.trim() }));
    setBusy(true);
    try {
      const r = await send<ReviewQueueItem>("post", `mentor/resume-reviews/${seg(review.id)}/feedback`, { comments: list, summary: summary.trim() }, { idempotencyKey: true });
      toast.show({ tone: "success", title: "Review sent to the student" });
      onDone(r);
    } catch (err) {
      const fe = fieldErrorsOf(err);
      if (Object.keys(fe).length) setErrors(fe);
      else fail(err, "Couldn't send the review");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      noValidate
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      {RESUME_SECTIONS.map((s) => (
        <FormField key={s} label={`Comment on ${s}`}>
          {(c) => <Input {...c} value={comments[s] ?? ""} maxLength={2000} onChange={(e) => setComments((m) => ({ ...m, [s]: e.target.value }))} />}
        </FormField>
      ))}
      <FormField label="Summary" required error={errors.summary}>
        {(c) => <TextArea {...c} value={summary} maxLength={5000} onChange={(e) => setSummary(e.target.value)} />}
      </FormField>
      <Button type="submit" loading={busy}>
        Send review
      </Button>
    </form>
  );
}

function Queue({ status }: { status: "open" | "completed" }) {
  const state = useApi<{ data: ReviewQueueItem[] }>("mentor/resume-reviews", { status });
  const [open, setOpen] = useState<string | null>(null);
  return (
    <Boundary state={state}>
      {(d) =>
        d.data.length ? (
          <ul className="space-y-4">
            {d.data.map((r) => (
              <li key={r.id}>
                <Card
                  title={`${r.student_name ?? "Student"} · v${r.resume.version_no}`}
                  actions={
                    <Badge tone={r.status === "completed" ? "success" : "info"}>
                      {r.status === "completed" ? "Completed" : r.status === "in_review" ? "In review" : "Requested"}
                    </Badge>
                  }
                >
                  <p className="text-sm text-fg-muted">
                    Requested {formatDateTime(r.requested_at)} · checklist score {r.resume.checklist_score}/100
                  </p>
                  {r.note ? <p className="mt-2 text-sm text-fg-secondary">Student note: {r.note}</p> : null}
                  {open === r.id ? (
                    <div className="mt-4 grid gap-6 lg:grid-cols-2">
                      <ResumePreview content={r.resume.content} />
                      {r.status === "completed" ? (
                        <div className="space-y-2 text-sm">
                          <p>{r.summary}</p>
                          <ul className="list-inside list-disc">
                            {r.comments.map((c, i) => (
                              <li key={i}>
                                <span className="font-medium">{c.section}:</span> {c.comment}
                              </li>
                            ))}
                          </ul>
                        </div>
                      ) : (
                        <ReviewFeedbackForm
                          review={r}
                          onDone={() => {
                            setOpen(null);
                            void state.reload();
                          }}
                        />
                      )}
                    </div>
                  ) : (
                    <Button className="mt-3" size="sm" variant="secondary" onClick={() => setOpen(r.id)}>
                      {r.status === "completed" ? "View review" : "Review"}
                    </Button>
                  )}
                </Card>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState title={status === "open" ? "No résumés waiting for review" : "No completed reviews yet"} />
        )
      }
    </Boundary>
  );
}

/** MEN-005 résumé review queue. */
export function MentorResumeReviews() {
  return (
    <Tabs
      label="Résumé reviews"
      items={[
        { id: "open", label: "Waiting", content: <Queue status="open" /> },
        { id: "completed", label: "Completed", content: <Queue status="completed" /> },
      ]}
    />
  );
}
