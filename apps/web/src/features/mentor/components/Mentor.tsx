"use client";

import Link from "next/link";
import { useState } from "react";
import { Button, Card, Dialog, FormField, Input, StatTile, Table, Tabs, useToast } from "@/components/ui";
import { useApi, seg } from "@/features/trainer/shared/use-api";
import { Boundary, StatusBadge, TextArea, fieldErrorsOf, formatDateTime, safeExternalUrl, useFailToast } from "@/features/trainer/shared/ui";
import { KIND_LABEL, LIVE_STATUSES, SCORE_LABEL, isHttpsUrl, send } from "../lib/api";
import {
  SCORE_KEYS,
  type Feedback,
  type MentorStudentDetail,
  type MentorStudentSummary,
  type Note,
  type ReviewQueueItem,
  type ScoreKey,
  type Session,
  type SessionDetail,
  type SessionList,
} from "../lib/types";
import { BookingBadge, FeedbackView, NotesPanel } from "./shared";

export type { MentorStudentDetail, MentorStudentSummary } from "../lib/types";

/** External meeting link: https/http only, opens in a new tab without referrer or opener. */
export function MeetingLink({ url }: { url: string | null | undefined }) {
  const safe = safeExternalUrl(url);
  if (!safe) return <span className="text-sm text-fg-muted">No meeting link yet</span>;
  let host = "";
  try {
    host = new URL(safe).hostname;
  } catch {
    /* already validated */
  }
  return (
    <a className="text-fg-link underline" href={safe} target="_blank" rel="noopener noreferrer">
      Join meeting{host ? ` (${host})` : ""}
      <span className="sr-only"> — opens in a new tab</span>
    </a>
  );
}

/* ------------------------------------------------------------------ MEN-001 */

function SessionTable({ view, caption }: { view: "upcoming" | "pending_feedback" | "past"; caption: string }) {
  const list = useApi<SessionList>("mentor/sessions", { view, limit: 50 });
  return (
    <Table
      caption={caption}
      columns={[
        { key: "w", header: "When", cell: (s: Session) => formatDateTime(s.starts_at) },
        {
          key: "s",
          header: "Student",
          cell: (s) => (
            <Link className="text-fg-link underline" href={`/mentor/sessions/${seg(s.id)}`}>
              {s.student_name ?? "Student"}
            </Link>
          ),
        },
        { key: "k", header: "Type", cell: (s) => `${KIND_LABEL[s.session_kind] ?? s.session_kind} · ${s.duration_minutes} min` },
        { key: "st", header: "Status", cell: (s) => <BookingBadge status={s.status} /> },
        {
          key: "f",
          header: "Feedback",
          cell: (s) =>
            s.feedback ? "Given" : s.feedback_overdue ? <span className="text-danger-fg">Overdue</span> : view === "upcoming" ? "—" : `Due ${formatDateTime(s.feedback_due_at)}`,
        },
      ]}
      rows={list.data?.data}
      rowKey={(s) => s.id}
      loading={list.loading}
      error={list.error}
      onRetry={() => void list.reload()}
      empty={{
        title: view === "upcoming" ? "No upcoming sessions" : view === "pending_feedback" ? "No feedback owed" : "No past sessions",
        description: view === "upcoming" ? "Publish availability so students can book you." : undefined,
      }}
    />
  );
}

/** MEN-001 dashboard: upcoming sessions, pending feedback, résumé reviews. */
export function MentorSessions() {
  const counts = useApi<SessionList>("mentor/sessions", { view: "all", limit: 1 });
  const reviews = useApi<{ data: ReviewQueueItem[] }>("mentor/resume-reviews", { status: "open" });
  const c = counts.data?.counts;
  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-3">
        <StatTile label="Upcoming sessions" value={counts.loading ? null : (c?.upcoming ?? 0)} />
        <StatTile label="Feedback owed" value={counts.loading ? null : (c?.pending_feedback ?? 0)} hint="Due within 48 h of each session" />
        <StatTile
          label="Résumé reviews waiting"
          value={reviews.loading ? null : (reviews.data?.data.length ?? 0)}
          hint={
            <Link className="text-fg-link underline" href="/mentor/resume-reviews">
              Open queue
            </Link>
          }
        />
      </div>
      <Tabs
        label="Sessions"
        items={[
          { id: "upcoming", label: "Upcoming", content: <SessionTable view="upcoming" caption="Upcoming sessions" /> },
          { id: "pending", label: "Pending feedback", content: <SessionTable view="pending_feedback" caption="Sessions needing feedback" /> },
          { id: "past", label: "Past", content: <SessionTable view="past" caption="Past sessions" /> },
        ]}
      />
      <p className="text-sm">
        <Link className="text-fg-link underline" href="/mentor/slots">
          Manage availability
        </Link>
        {" · "}
        <Link className="text-fg-link underline" href="/mentor/students">
          Assigned students
        </Link>
      </p>
    </div>
  );
}

/* ------------------------------------------------------------------ MEN-003 */

const EMPTY_SCORES: Record<ScoreKey, string> = { communication: "", problem_solving: "", technical_depth: "", confidence: "", overall: "" };

/** Rubric feedback: 5 criteria, each 1–5 (all required), plus optional comments. */
export function FeedbackForm({ bookingId, onDone }: { bookingId: string; onDone: (f: Feedback) => void }) {
  const [scores, setScores] = useState(EMPTY_SCORES);
  const [comments, setComments] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const fail = useFailToast();
  const toast = useToast();

  async function submit() {
    const errs: Record<string, string> = {};
    for (const k of SCORE_KEYS) if (!scores[k]) errs[k] = `Score ${SCORE_LABEL[k].toLowerCase()} from 1 to 5`;
    if (comments.length > 5000) errs.comments = "Keep comments under 5,000 characters";
    setErrors(errs);
    if (Object.keys(errs).length) return;
    setBusy(true);
    try {
      const body = { scores: Object.fromEntries(SCORE_KEYS.map((k) => [k, Number(scores[k])])), ...(comments.trim() ? { comments: comments.trim() } : {}) };
      const f = await send<Feedback>("post", `mentor/bookings/${seg(bookingId)}/feedback`, body, { idempotencyKey: true });
      toast.show({ tone: "success", title: "Feedback shared with the student" });
      onDone(f);
    } catch (err) {
      const fe = fieldErrorsOf(err);
      const mapped: Record<string, string> = {};
      for (const [k, v] of Object.entries(fe)) mapped[k.replace(/^scores\./, "")] = v;
      if (Object.keys(mapped).length) setErrors(mapped);
      else fail(err, "Couldn't save feedback");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      className="space-y-4"
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {SCORE_KEYS.map((k) => (
          <FormField key={k} label={SCORE_LABEL[k]} required error={errors[k]}>
            {(c) => (
              <select
                {...c}
                className="h-10 w-full rounded-md border border-line-control bg-surface px-3 text-sm text-fg"
                value={scores[k]}
                onChange={(e) => setScores((s) => ({ ...s, [k]: e.target.value }))}
              >
                <option value="">Choose 1–5</option>
                {[1, 2, 3, 4, 5].map((n) => (
                  <option key={n} value={String(n)}>
                    {n}
                  </option>
                ))}
              </select>
            )}
          </FormField>
        ))}
      </div>
      <FormField label="Comments" hint="Visible to the student." error={errors.comments}>
        {(c) => <TextArea {...c} value={comments} maxLength={5000} onChange={(e) => setComments(e.target.value)} />}
      </FormField>
      <Button type="submit" loading={busy}>
        Submit feedback
      </Button>
    </form>
  );
}

function MeetingLinkEditor({ session, onSaved }: { session: SessionDetail; onSaved: (s: SessionDetail) => void }) {
  const [value, setValue] = useState(session.meeting_url ?? "");
  const [error, setError] = useState<string | undefined>();
  const [busy, setBusy] = useState(false);
  const fail = useFailToast();
  async function save() {
    if (!isHttpsUrl(value.trim())) return setError("Use an https:// meeting link");
    setBusy(true);
    setError(undefined);
    try {
      onSaved(await send<SessionDetail>("patch", `mentor/sessions/${seg(session.id)}`, { meeting_url: value.trim() }));
    } catch (err) {
      const fe = fieldErrorsOf(err);
      if (fe.meeting_url) setError(fe.meeting_url);
      else fail(err, "Couldn't save the link");
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="flex flex-wrap items-end gap-2">
      <div className="min-w-64 flex-1">
        <FormField label="Meeting link" error={error} hint="External meeting URL (https only).">
          {(c) => <Input {...c} type="url" value={value} placeholder="https://meet.example.com/…" onChange={(e) => setValue(e.target.value)} />}
        </FormField>
      </div>
      <Button variant="secondary" loading={busy} onClick={() => void save()}>
        Save link
      </Button>
    </div>
  );
}

/** MEN-003 session detail: student snapshot, meeting link, rubric feedback, no-show, private notes. */
export function MentorSessionDetail({ bookingId }: { bookingId: string }) {
  const state = useApi<SessionDetail>(`mentor/sessions/${seg(bookingId)}`);
  const [local, setLocal] = useState<SessionDetail | null>(null);
  const [noShow, setNoShow] = useState<"student" | "mentor" | null>(null);
  const [busy, setBusy] = useState(false);
  const fail = useFailToast();
  const toast = useToast();

  async function markNoShow() {
    if (!noShow) return;
    setBusy(true);
    try {
      const s = await send<Session>("post", `mentor/bookings/${seg(bookingId)}/no-show`, { party: noShow }, { idempotencyKey: true });
      setLocal((prev) => ({ ...(prev ?? state.data!), ...s }));
      toast.show({ tone: "success", title: noShow === "mentor" ? "Marked as missed — the student's credit is restored" : "Marked student no-show" });
      setNoShow(null);
    } catch (err) {
      fail(err, "Couldn't record the no-show");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Boundary state={state}>
      {(fetched) => {
        const d = local ?? fetched;
        const live = LIVE_STATUSES.includes(d.status);
        const started = Date.parse(d.starts_at) <= Date.now();
        return (
          <div className="space-y-6">
            <div className="flex flex-wrap items-center gap-3 text-sm text-fg-secondary">
              <Link className="text-fg-link underline" href={`/mentor/students/${seg(d.student_id)}`}>
                {d.student_name ?? "Student"}
              </Link>
              <span>
                {KIND_LABEL[d.session_kind] ?? d.session_kind} · {formatDateTime(d.starts_at)} · {d.duration_minutes} min
              </span>
              <BookingBadge status={d.status} />
            </div>
            <div className="grid gap-4 lg:grid-cols-2">
              <Card title="Meeting">
                <div className="space-y-3">
                  <MeetingLink url={d.meeting_url} />
                  {live ? <MeetingLinkEditor session={d} onSaved={(s) => setLocal(s)} /> : null}
                </div>
              </Card>
              <Card title="Readiness snapshot">
                {d.weak_topics.length ? <p className="text-sm text-fg-secondary">Weakest topics: {d.weak_topics.join(", ")}</p> : <p className="text-sm text-fg-muted">No weak topics recorded.</p>}
              </Card>
            </div>
            <Card title="Rubric feedback">
              {d.feedback ? (
                <FeedbackView feedback={d.feedback} />
              ) : live && started ? (
                <div className="space-y-3">
                  <p className={`text-sm ${d.feedback_overdue ? "text-danger-fg" : "text-fg-muted"}`}>
                    {d.feedback_overdue ? "Overdue — " : ""}Feedback due by {formatDateTime(d.feedback_due_at)}.
                  </p>
                  <FeedbackForm bookingId={d.id} onDone={(f) => setLocal({ ...d, feedback: f, status: "completed" })} />
                </div>
              ) : live ? (
                <p className="text-sm text-fg-muted">You can give feedback once the session has started.</p>
              ) : (
                <p className="text-sm text-fg-muted">No feedback for this session.</p>
              )}
            </Card>
            {live && started && !d.feedback ? (
              <Card title="No-show">
                <p className="text-sm text-fg-muted">Student no-show can be recorded 10 minutes after the start. If you missed the session, the student&apos;s credit is restored automatically.</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  <Button variant="secondary" onClick={() => setNoShow("student")}>
                    Student didn&apos;t join
                  </Button>
                  <Button variant="secondary" onClick={() => setNoShow("mentor")}>
                    I missed this session
                  </Button>
                </div>
              </Card>
            ) : null}
            <Card title="Private notes">
              <NotesPanel studentId={d.student_id} bookingId={d.id} notes={d.notes} onAdded={(n: Note) => setLocal({ ...d, notes: [n, ...d.notes] })} />
            </Card>
            <Dialog
              open={noShow !== null}
              onClose={() => setNoShow(null)}
              title={noShow === "mentor" ? "Record that you missed this session?" : "Record a student no-show?"}
              description={noShow === "mentor" ? "The student gets the session credit back and an apology." : "The session credit stays used."}
              footer={
                <>
                  <Button variant="secondary" onClick={() => setNoShow(null)}>
                    Keep as is
                  </Button>
                  <Button loading={busy} onClick={() => void markNoShow()}>
                    Confirm
                  </Button>
                </>
              }
            />
          </div>
        );
      }}
    </Boundary>
  );
}

/* ------------------------------------------------------------------ MEN-004 */

/** Assigned students (`GET /mentor/students`, cursor envelope). */
export function MentorStudents() {
  const list = useApi<{ data: MentorStudentSummary[] }>("mentor/students", { limit: 100 });
  return (
    <Table
      caption="Assigned students"
      columns={[
        {
          key: "n",
          header: "Student",
          cell: (s: MentorStudentSummary) => (
            <Link className="text-fg-link underline" href={`/mentor/students/${seg(s.user_id)}`}>
              {s.full_name ?? "Student"}
            </Link>
          ),
        },
        { key: "b", header: "Batch", cell: (s) => (s.batches.length ? s.batches.map((b) => b.name ?? "Batch").join(", ") : (s.batch_name ?? "—")) },
        { key: "c", header: "Target companies", cell: (s) => (s.target_companies.length ? s.target_companies.join(", ") : "—") },
        { key: "x", header: "Next session", cell: (s) => (s.next_session_at ? formatDateTime(s.next_session_at) : "—") },
      ]}
      rows={list.data?.data}
      rowKey={(s) => s.user_id}
      loading={list.loading}
      error={list.error}
      onRetry={() => void list.reload()}
      empty={{ title: "No students assigned yet", description: "Students appear here once you're assigned to their batch or they book a session with you." }}
    />
  );
}

/** MEN-004 student readiness (PLC-46), feedback history and private notes. */
export function MentorStudent({ userId }: { userId: string }) {
  const detail = useApi<MentorStudentDetail>(`mentor/students/${seg(userId)}`);
  const [added, setAdded] = useState<Note[]>([]);

  return (
    <Boundary state={detail}>
      {(d) => (
        <div className="space-y-6">
          <p className="text-sm text-fg-secondary">
            {d.full_name ?? "Student"}
            {d.batch_name ? ` · ${d.batch_name}` : ""}
            {d.target_companies.length ? ` · Targets: ${d.target_companies.join(", ")}` : ""}
            {d.next_session_at ? ` · Next session ${formatDateTime(d.next_session_at)}` : ""}
          </p>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="Readiness">
              <p className="text-sm text-fg-muted">Company readiness is not available yet.</p>
              {d.weak_topics.length ? <p className="mt-3 text-sm text-fg-secondary">Weakest topics: {d.weak_topics.join(", ")}</p> : null}
            </Card>
            <Card title="Your notes">
              <NotesPanel studentId={d.user_id} notes={[...added, ...d.notes]} onAdded={(n) => setAdded((a) => [n, ...a])} />
            </Card>
          </div>
          <Table
            caption="Topic mastery"
            showCaption
            columns={[
              { key: "t", header: "Topic", cell: (t: MentorStudentDetail["topics"][number]) => t.name ?? "Topic" },
              { key: "b", header: "Band", cell: (t) => <StatusBadge status={t.band} /> },
              { key: "a", header: "Questions attempted", align: "right", cell: (t) => t.attempts },
            ]}
            rows={d.topics}
            rowKey={(t) => t.topic_id}
            empty={{ title: "No practice data yet" }}
          />
          <Card title="Feedback history">
            {d.feedback.length ? (
              <ul className="space-y-4">
                {d.feedback.map((f) => (
                  <li key={f.id} className="space-y-1">
                    <p className="text-sm font-medium text-fg">
                      {KIND_LABEL[f.session_kind] ?? f.session_kind} · {formatDateTime(f.starts_at)}
                    </p>
                    <FeedbackView feedback={f} />
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-fg-muted">No session feedback yet.</p>
            )}
          </Card>
        </div>
      )}
    </Boundary>
  );
}

