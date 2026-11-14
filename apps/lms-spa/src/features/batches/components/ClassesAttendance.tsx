"use client";

import { useMemo, useState } from "react";
import { Badge, Button, Card, Checkbox, Dialog, EmptyState, FormField, Input, Reveal, SectionHeader, Segmented, StatGrid, StatTile, Table, TextArea, useToast } from "@/components/ui";
import { api } from "@/lib/api/client";
import { useApi, seg } from "@/features/trainer/shared/use-api";
import { Boundary, fieldErrorsOf, safeExternalUrl, useFailToast } from "@/features/trainer/shared/ui";
import { archivedBatchGuard } from "../lib/api";
import { MARK_LABEL, fmtDay, pctText, type BatchAttendance, type ClassSession, type Mark, type SessionAttendance, type SessionList } from "../lib/delivery";

type View = "upcoming" | "past" | "all";

const MARK_TONE: Record<Mark, string> = {
  P: "border-success-border bg-success-subtle text-success-fg",
  L: "border-warning-border bg-warning-subtle text-warning-fg",
  A: "border-danger-border bg-danger-subtle text-danger-fg",
};

/**
 * Batch "Classes & attendance" tab (moved from the website's Admin > Learning class register):
 * one class per date with topic, class link, recording and notes; attendance P / L / A per
 * student (late counts as attended). Used by Admin (/admin/batches/[id]) and trainers
 * (/trainer/batches/[id]); the api limits trainers to their own batches (`batch.class.manage`).
 */
export function ClassesAttendance({ batchId, canManage = false }: { batchId: string; canManage?: boolean }) {
  const sessions = useApi<SessionList>(`batches/${seg(batchId)}/sessions`);
  const summary = useApi<BatchAttendance>(`batches/${seg(batchId)}/attendance`);
  const [view, setView] = useState<View>("upcoming");
  const [editing, setEditing] = useState<ClassSession | "new" | null>(null);
  const [marking, setMarking] = useState<ClassSession | null>(null);
  const [generating, setGenerating] = useState(false);
  const toast = useToast();
  const fail = useFailToast();
  const reload = () => {
    void sessions.reload();
    void summary.reload();
  };

  const today = sessions.data?.today ?? "";
  const rows = useMemo(() => {
    const all = sessions.data?.data ?? [];
    if (view === "upcoming") return all.filter((s) => s.session_date >= today);
    if (view === "past") return [...all.filter((s) => s.session_date < today)].reverse();
    return all;
  }, [sessions.data, view, today]);

  const generate = async () => {
    setGenerating(true);
    try {
      const r = await archivedBatchGuard(api.post<{ created: number }>(`batches/${seg(batchId)}/sessions/generate`, {}));
      const n = r.kind === "ok" ? r.data.created : 0;
      toast.show({ tone: "success", title: n ? `Added ${n} classes from the plan` : "Every planned date already has a class" });
      reload();
    } catch (err) {
      fail(err, "Could not add the classes");
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div className="space-y-6">
      <Boundary state={summary} rows={1}>
        {(s) => (
          <StatGrid columns={3}>
            <StatTile icon="check" label="Batch attendance" value={pctText(s.batch.percent)} hint={`${s.classes_marked} classes marked`} tone={s.batch.percent === null ? "neutral" : "success"} />
            <StatTile icon="users" label="Students" value={String(s.data.length)} />
            <StatTile icon="alert" label="Below the minimum" value={s.min_attendance_percent ? String(s.data.filter((d) => d.below_minimum).length) : "—"} hint={s.min_attendance_percent ? `Minimum ${s.min_attendance_percent}%` : "No minimum set"} tone={s.data.some((d) => d.below_minimum) ? "warning" : "neutral"} />
          </StatGrid>
        )}
      </Boundary>

      <SectionHeader
        title="Classes"
        description={canManage ? "Add the batch's classes, share the link and recording, and mark attendance after each class." : undefined}
        actions={
          canManage ? (
            <>
              <Button variant="secondary" onClick={() => void generate()} loading={generating}>
                Add classes from the plan
              </Button>
              <Button onClick={() => setEditing("new")}>Add class</Button>
            </>
          ) : undefined
        }
      />
      <Segmented
        legend="Show"
        hideLegend
        name="class-view"
        variant="pills"
        value={view}
        onChange={setView}
        options={[
          { value: "upcoming", label: "Upcoming" },
          { value: "past", label: "Past" },
          { value: "all", label: "All" },
        ]}
      />
      <Boundary state={sessions} rows={3}>
        {(list) =>
          rows.length === 0 ? (
            <EmptyState icon="calendar" title={view === "past" ? "No past classes" : "No classes scheduled"} description={canManage ? "Add a class, or add every class of the plan at once." : undefined} />
          ) : (
            <Reveal as="ul" stagger className="grid gap-3 md:grid-cols-2" aria-label="Classes">
              {rows.map((s) => (
                <li key={s.id}>
                  <ClassCard s={s} today={list.today} students={list.students} canManage={canManage} onEdit={() => setEditing(s)} onMark={() => setMarking(s)} />
                </li>
              ))}
            </Reveal>
          )
        }
      </Boundary>

      <Boundary state={summary} rows={2}>
        {(s) => (
          <Card title="Attendance by student" titleSize="lg" padding="none">
            <Table
              caption="Attendance by student"
              columns={[
                { key: "name", header: "Student", cell: (r: BatchAttendance["data"][number]) => r.full_name ?? "Unnamed" },
                { key: "pct", header: "Attendance", cell: (r) => (r.below_minimum ? <Badge tone="warning">{pctText(r.percent)} · below minimum</Badge> : pctText(r.percent)) },
                { key: "p", header: "Present", align: "right" as const, cell: (r) => r.present },
                { key: "l", header: "Late", align: "right" as const, cell: (r) => r.late },
                { key: "a", header: "Absent", align: "right" as const, cell: (r) => r.absent },
              ]}
              rows={s.data}
              rowKey={(r) => r.user_id}
              empty={{ title: "No students in this batch yet" }}
            />
          </Card>
        )}
      </Boundary>

      {canManage ? (
        <>
          <ClassDialog batchId={batchId} session={editing} onClose={() => setEditing(null)} onDone={reload} />
          <MarkDialog batchId={batchId} session={marking} onClose={() => setMarking(null)} onDone={reload} />
        </>
      ) : null}
    </div>
  );
}

function ClassCard({ s, today, students, canManage, onEdit, onMark }: { s: ClassSession; today: string; students: number; canManage: boolean; onEdit: () => void; onMark: () => void }) {
  const join = safeExternalUrl(s.meet_url);
  const rec = safeExternalUrl(s.recording_url);
  const a = s.attendance;
  return (
    <article aria-label={`${fmtDay(s.session_date)}: ${s.topic || "Class"}`} className="flex h-full flex-col gap-2 rounded-2xl border border-line bg-surface p-4 shadow-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-full bg-brand-subtle px-3 py-0.5 font-display text-sm font-bold text-brand">{fmtDay(s.session_date)}</span>
        {s.starts_at ? <span className="text-sm text-fg-muted">{s.starts_at} IST</span> : null}
        {s.session_date === today ? <Badge tone="brand" dot>Today</Badge> : null}
        {s.cancelled ? <Badge tone="danger">Cancelled</Badge> : null}
      </div>
      <h3 className="font-display text-base font-bold text-fg-heading">{s.topic || "Class"}</h3>
      {s.notes ? <p className="line-clamp-2 text-sm text-fg-secondary">{s.notes}</p> : null}
      {a && a.marked ? (
        <p className="text-sm text-fg-secondary">
          {a.P} present · {a.L} late · {a.A} absent
          {students > a.marked ? ` · ${students - a.marked} not marked` : ""}
        </p>
      ) : null}
      <div className="mt-auto flex flex-wrap gap-2 pt-1">
        {join && !s.cancelled && s.session_date >= today ? (
          <a className="inline-flex min-h-touch items-center rounded-md bg-brand px-3 text-sm font-semibold text-brand-on md:min-h-9" href={join} target="_blank" rel="noopener noreferrer">
            Join class
          </a>
        ) : null}
        {rec ? (
          <a className="inline-flex min-h-touch items-center rounded-md border border-brand/30 px-3 text-sm font-semibold text-brand md:min-h-9" href={rec} target="_blank" rel="noopener noreferrer">
            Recording
          </a>
        ) : null}
        {canManage && !s.cancelled && s.session_date <= today ? (
          <Button size="sm" onClick={onMark}>
            {a && a.marked ? "Edit attendance" : "Mark attendance"}
          </Button>
        ) : null}
        {canManage ? (
          <Button size="sm" variant="secondary" onClick={onEdit} aria-label={`Edit class on ${fmtDay(s.session_date)}`}>
            Edit
          </Button>
        ) : null}
      </div>
    </article>
  );
}

/* ------------------------------------------------------------------ add / edit class */

interface ClassForm {
  session_date: string;
  starts_at: string;
  duration_minutes: string;
  topic: string;
  meet_url: string;
  recording_url: string;
  notes: string;
  cancelled: boolean;
}

function formOf(s: ClassSession | "new" | null): ClassForm {
  if (!s || s === "new") return { session_date: "", starts_at: "", duration_minutes: "", topic: "", meet_url: "", recording_url: "", notes: "", cancelled: false };
  return {
    session_date: s.session_date,
    starts_at: s.starts_at ?? "",
    duration_minutes: s.duration_minutes ? String(s.duration_minutes) : "",
    topic: s.topic,
    meet_url: s.meet_url ?? "",
    recording_url: s.recording_url ?? "",
    notes: s.notes ?? "",
    cancelled: s.cancelled,
  };
}

function ClassDialog({ batchId, session, onClose, onDone }: { batchId: string; session: ClassSession | "new" | null; onClose: () => void; onDone: () => void }) {
  const key = session === "new" ? "new" : (session?.id ?? "");
  return session ? <ClassDialogBody key={key} batchId={batchId} session={session} onClose={onClose} onDone={onDone} /> : null;
}

function ClassDialogBody({ batchId, session, onClose, onDone }: { batchId: string; session: ClassSession | "new"; onClose: () => void; onDone: () => void }) {
  const [f, setF] = useState<ClassForm>(() => formOf(session));
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const toast = useToast();
  const fail = useFailToast();
  const isNew = session === "new";
  const submit = async () => {
    if (!f.session_date) {
      setErrors({ session_date: "Choose the class date." });
      return;
    }
    setBusy(true);
    setErrors({});
    const body = {
      session_date: f.session_date,
      starts_at: f.starts_at || null,
      duration_minutes: f.duration_minutes ? Number(f.duration_minutes) : null,
      topic: f.topic.trim(),
      meet_url: f.meet_url.trim() || null,
      recording_url: f.recording_url.trim() || null,
      notes: f.notes.trim() || null,
      cancelled: f.cancelled,
    };
    try {
      await archivedBatchGuard(
        isNew ? api.post(`batches/${seg(batchId)}/sessions`, body) : api.patch(`batches/${seg(batchId)}/sessions/${seg(session.id)}`, body),
      );
      toast.show({ tone: "success", title: isNew ? "Class added" : "Class saved" });
      onDone();
      onClose();
    } catch (err) {
      setErrors(fieldErrorsOf(err));
      fail(err, "Could not save the class");
    } finally {
      setBusy(false);
    }
  };
  const remove = async () => {
    if (isNew) return;
    setBusy(true);
    try {
      await archivedBatchGuard(api.delete(`batches/${seg(batchId)}/sessions/${seg(session.id)}`));
      toast.show({ tone: "success", title: "Class deleted" });
      onDone();
      onClose();
    } catch (err) {
      fail(err, "Could not delete the class");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog
      open
      onClose={onClose}
      dismissible={!busy}
      size="lg"
      title={isNew ? "Add class" : "Edit class"}
      footer={
        <>
          {!isNew ? (
            <Button variant="danger-secondary" onClick={() => void remove()} disabled={busy} className="mr-auto">
              Delete
            </Button>
          ) : null}
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void submit()} loading={busy}>
            {isNew ? "Add class" : "Save"}
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-3">
        <FormField label="Date" required error={errors.session_date}>
          {(p) => <Input {...p} type="date" value={f.session_date} onChange={(e) => setF({ ...f, session_date: e.target.value })} />}
        </FormField>
        <FormField label="Time (IST)" error={errors.starts_at}>
          {(p) => <Input {...p} type="time" value={f.starts_at} onChange={(e) => setF({ ...f, starts_at: e.target.value })} />}
        </FormField>
        <FormField label="Minutes" error={errors.duration_minutes}>
          {(p) => <Input {...p} type="number" min={1} max={720} value={f.duration_minutes} onChange={(e) => setF({ ...f, duration_minutes: e.target.value })} />}
        </FormField>
      </div>
      <div className="mt-4 grid gap-4">
        <FormField label="Topic" error={errors.topic}>
          {(p) => <Input {...p} maxLength={200} value={f.topic} onChange={(e) => setF({ ...f, topic: e.target.value })} />}
        </FormField>
        <FormField label="Class link" hint="https:// (blank = the plan's class link)" error={errors.meet_url}>
          {(p) => <Input {...p} type="url" inputMode="url" value={f.meet_url} onChange={(e) => setF({ ...f, meet_url: e.target.value })} />}
        </FormField>
        <FormField label="Recording link" hint="https:// shown to learners after the class" error={errors.recording_url}>
          {(p) => <Input {...p} type="url" inputMode="url" value={f.recording_url} onChange={(e) => setF({ ...f, recording_url: e.target.value })} />}
        </FormField>
        <FormField label="Notes for staff" error={errors.notes}>
          {(p) => <TextArea {...p} rows={3} maxLength={4000} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} />}
        </FormField>
        <Checkbox label="Cancelled" description="Learners see it as cancelled; it does not count for attendance" checked={f.cancelled} onChange={(e) => setF({ ...f, cancelled: e.target.checked })} />
      </div>
    </Dialog>
  );
}

/* ------------------------------------------------------------------ attendance */

function MarkDialog({ batchId, session, onClose, onDone }: { batchId: string; session: ClassSession | null; onClose: () => void; onDone: () => void }) {
  return session ? <MarkDialogBody key={session.id} batchId={batchId} session={session} onClose={onClose} onDone={onDone} /> : null;
}

function MarkDialogBody({ batchId, session, onClose, onDone }: { batchId: string; session: ClassSession; onClose: () => void; onDone: () => void }) {
  const roster = useApi<SessionAttendance>(`batches/${seg(batchId)}/sessions/${seg(session.id)}/attendance`);
  const [draft, setDraft] = useState<Record<string, Mark | null>>({});
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const fail = useFailToast();
  const current = (uid: string, saved: Mark | null) => (uid in draft ? draft[uid]! : saved);
  const changed = Object.keys(draft).length;

  const save = async () => {
    const saved = Object.fromEntries((roster.data?.data ?? []).map((r) => [r.user_id, r.status]));
    const marks = Object.entries(draft)
      .filter(([u, st]) => saved[u] !== st)
      .map(([user_id, status]) => ({ user_id, status }));
    if (!marks.length) {
      onClose();
      return;
    }
    setBusy(true);
    try {
      await archivedBatchGuard(api.put(`batches/${seg(batchId)}/sessions/${seg(session.id)}/attendance`, { marks }));
      toast.show({ tone: "success", title: "Attendance saved" });
      onDone();
      onClose();
    } catch (err) {
      fail(err, "Could not save the attendance");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open
      onClose={onClose}
      dismissible={!busy}
      size="lg"
      title={`Attendance · ${fmtDay(session.session_date)}`}
      description={session.topic || undefined}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void save()} loading={busy} disabled={!changed}>
            Save attendance
          </Button>
        </>
      }
    >
      <Boundary state={roster} rows={4}>
        {(r) =>
          r.data.length === 0 ? (
            <EmptyState variant="inline" icon="users" title="No students in this batch" />
          ) : (
            <div className="space-y-3">
              <div className="flex flex-wrap gap-2">
                <Button size="sm" variant="secondary" onClick={() => setDraft(Object.fromEntries(r.data.map((x) => [x.user_id, "P" as Mark])))}>
                  Everyone present
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setDraft({ ...draft, ...Object.fromEntries(r.data.filter((x) => !current(x.user_id, x.status)).map((x) => [x.user_id, "A" as Mark])) })}>
                  Rest absent
                </Button>
              </div>
              <ul className="divide-y divide-line" aria-label="Students">
                {r.data.map((x) => {
                  const st = current(x.user_id, x.status);
                  const name = x.full_name ?? "Unnamed";
                  return (
                    <li key={x.user_id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                      <span className="min-w-0 font-medium text-fg">
                        {name}
                        {!x.in_batch ? <span className="ml-2 text-sm text-fg-muted">(left the batch)</span> : null}
                      </span>
                      <span role="group" aria-label={`Attendance for ${name}`} className="flex gap-1.5">
                        {(["P", "L", "A"] as Mark[]).map((m) => (
                          <button
                            key={m}
                            type="button"
                            aria-pressed={st === m}
                            aria-label={`${MARK_LABEL[m]}: ${name}`}
                            onClick={() => setDraft({ ...draft, [x.user_id]: st === m ? null : m })}
                            className={`h-11 w-11 rounded-lg border font-display text-base font-bold focus-visible:shadow-focus focus-visible:outline-none md:h-9 md:w-9 ${st === m ? MARK_TONE[m] : "border-line-control bg-surface text-fg-secondary hover:bg-surface-hover"}`}
                          >
                            {m}
                          </button>
                        ))}
                      </span>
                    </li>
                  );
                })}
              </ul>
              <p className="text-sm text-fg-muted">P present · L late (counts as attended) · A absent. Tap a selected letter again to clear it.</p>
            </div>
          )
        }
      </Boundary>
    </Dialog>
  );
}
