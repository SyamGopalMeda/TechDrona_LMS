"use client";

import Link from "next/link";
import { useState } from "react";
import { Button, Card, Dialog, FormField, Input, StatTile, Table, useToast } from "@/components/ui";
import { api } from "@/lib/api/client";
import { useApi, seg, type ApiState } from "@/features/trainer/shared/use-api";
import { Boundary, StatusBadge, fieldErrorsOf, formatDate, useFailToast } from "@/features/trainer/shared/ui";
import { AddMemberDialog, BatchActions, BatchStaff, MemberActionDialog } from "./BatchManage";
import { LessonFunnelView, ProgressDistributionView } from "@/features/trainer/shared/report-sections";
import type { Batch, BatchCreateBody, BatchMember, BatchReport } from "../lib/types";

/** Admin batch (cohort) list + create (single-company plan §3, ADM-013). */
export function BatchList({ hrefFor = (id: string) => `/admin/batches/${seg(id)}` }: { hrefFor?: (batchId: string) => string }) {
  const batches = useApi<{ data: Batch[] }>("batches");
  const [open, setOpen] = useState(false);
  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button onClick={() => setOpen(true)}>Create batch</Button>
      </div>
      <Table
        caption="Batches"
        columns={[
          {
            key: "name",
            header: "Batch",
            cell: (b: Batch) => (
              <Link className="text-fg-link underline" href={hrefFor(b.id)}>
                {b.name}
              </Link>
            ),
          },
          { key: "code", header: "Code", cell: (b) => b.code },
          { key: "intake", header: "Intake", cell: (b) => b.academic_year ?? "—" },
          { key: "year", header: "Graduation year", cell: (b) => b.graduation_year ?? "—" },
          { key: "dates", header: "Dates", cell: (b) => `${formatDate(b.starts_on)} – ${formatDate(b.ends_on)}` },
          { key: "status", header: "Status", cell: (b) => <StatusBadge status={b.status} /> },
        ]}
        rows={batches.data?.data}
        rowKey={(b) => b.id}
        loading={batches.loading}
        error={batches.error}
        onRetry={() => void batches.reload()}
        empty={{ title: "No batches yet", description: "Create a batch for each cohort you train.", action: <Button onClick={() => setOpen(true)}>Create batch</Button> }}
      />
      <CreateBatchDialog
        open={open}
        onClose={() => setOpen(false)}
        onCreated={() => {
          setOpen(false);
          void batches.reload();
        }}
      />
    </div>
  );
}

function CreateBatchDialog({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: () => void }) {
  const toast = useToast();
  const fail = useFailToast();
  const [f, setF] = useState({ name: "", code: "", academic_year: "", graduation_year: "", starts_on: "", ends_on: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }));

  const submit = async () => {
    const errs: Record<string, string> = {};
    if (!f.name.trim()) errs.name = "Enter a batch name.";
    if (!/^[A-Za-z0-9._-]+$/.test(f.code)) errs.code = "Use letters, numbers, dots, dashes or underscores.";
    if (f.starts_on && f.ends_on && f.ends_on < f.starts_on) errs.ends_on = "End date is before the start date.";
    setErrors(errs);
    if (Object.keys(errs).length) return;
    setBusy(true);
    try {
      await api.post("batches", {
        name: f.name.trim(),
        code: f.code,
        academic_year: f.academic_year.trim() || null,
        graduation_year: f.graduation_year ? Number(f.graduation_year) : null,
        starts_on: f.starts_on || null,
        ends_on: f.ends_on || null,
      } satisfies BatchCreateBody);
      toast.show({ tone: "success", title: `Created ${f.name.trim()}` });
      setF({ name: "", code: "", academic_year: "", graduation_year: "", starts_on: "", ends_on: "" });
      onCreated();
    } catch (err) {
      const fe = fieldErrorsOf(err);
      if (Object.keys(fe).length) setErrors(fe);
      else fail(err, "Couldn't create the batch");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      dismissible={!busy}
      title="Create batch"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void submit()} loading={busy}>
            Create
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <FormField label="Name" required error={errors.name}>
          {(p) => <Input {...p} value={f.name} onChange={set("name")} placeholder="Full-stack cohort – Jan 2027" />}
        </FormField>
        <FormField label="Code" required hint="Short unique code, e.g. FS-JAN-27" error={errors.code}>
          {(p) => <Input {...p} value={f.code} onChange={set("code")} />}
        </FormField>
        <FormField label="Intake" hint="e.g. 2026-27" error={errors.academic_year}>
          {(p) => <Input {...p} value={f.academic_year} onChange={set("academic_year")} maxLength={9} />}
        </FormField>
        <FormField label="Graduation year" error={errors.graduation_year}>
          {(p) => <Input {...p} type="number" inputMode="numeric" min={1990} max={2100} value={f.graduation_year} onChange={set("graduation_year")} />}
        </FormField>
        <div className="grid gap-3 sm:grid-cols-2">
          <FormField label="Starts on" error={errors.starts_on}>
            {(p) => <Input {...p} type="date" value={f.starts_on} onChange={set("starts_on")} />}
          </FormField>
          <FormField label="Ends on" error={errors.ends_on}>
            {(p) => <Input {...p} type="date" value={f.ends_on} onChange={set("ends_on")} />}
          </FormField>
        </div>
      </div>
    </Dialog>
  );
}

/* ----------------------------------------------------------- batch detail + report */

/**
 * ADM-014 / TRN-002 batch detail: members (ORG-25) + batch report (ANL-06). With `manageable`
 * (the Admin view) it also offers edit / archive, add / move / remove members and
 * trainer / evaluator assignment.
 */
export function BatchDetail({ batchId, studentHref, manageable = false }: { batchId: string; studentHref?: (userId: string) => string; manageable?: boolean }) {
  const batch = useApi<Batch>(`batches/${encodeURIComponent(batchId)}`);
  const members = useApi<{ data: BatchMember[] }>(`batches/${encodeURIComponent(batchId)}/members`);
  const report = useApi<BatchReport>(`analytics/reports/batches/${encodeURIComponent(batchId)}`);
  const [adding, setAdding] = useState(false);
  const [memberAction, setMemberAction] = useState<{ member: BatchMember; kind: "remove" | "move" } | null>(null);
  const manage = manageable && !!batch.data && batch.data.status !== "archived";
  const refresh = () => {
    void members.reload();
    void report.reload();
  };

  return (
    <div className="space-y-6">
      <Boundary state={batch} rows={1}>
        {(b) => (
          <div className="flex flex-wrap items-center gap-3 text-sm text-fg-secondary">
            <span className="font-display text-lg font-semibold text-fg">{b.name}</span>
            <span>{b.code}</span>
            <StatusBadge status={b.status} />
            <span>
              {formatDate(b.starts_on)} – {formatDate(b.ends_on)}
            </span>
            {manageable ? (
              <span className="ml-auto">
                <BatchActions
                  batch={b}
                  onChanged={() => {
                    void batch.reload();
                    refresh();
                  }}
                />
              </span>
            ) : null}
          </div>
        )}
      </Boundary>
      <Card title="Batch progress">
        <BatchReportView state={report} studentHref={studentHref} names={Object.fromEntries((members.data?.data ?? []).map((m) => [m.user_id, m.full_name]))} />
      </Card>
      <Table
        caption="Batch members"
        showCaption
        columns={[
          {
            key: "name",
            header: "Name",
            cell: (m: BatchMember) =>
              studentHref && m.member_role === "student" ? (
                <Link className="text-fg-link underline" href={studentHref(m.user_id)}>
                  {m.full_name ?? "Unnamed"}
                </Link>
              ) : (
                (m.full_name ?? "Unnamed")
              ),
          },
          { key: "role", header: "Role", cell: (m) => m.member_role.replace(/^\w/, (c) => c.toUpperCase()) },
          { key: "added", header: "Added", cell: (m) => formatDate(m.added_at) },
          ...(manage
            ? [
                {
                  key: "actions",
                  header: <span className="sr-only">Actions</span>,
                  align: "right" as const,
                  cell: (m: BatchMember) => (
                    <span className="flex justify-end gap-2">
                      <Button size="sm" variant="secondary" aria-label={`Move ${m.full_name ?? "member"}`} onClick={() => setMemberAction({ member: m, kind: "move" })}>
                        Move
                      </Button>
                      <Button size="sm" variant="secondary" aria-label={`Remove ${m.full_name ?? "member"} from batch`} onClick={() => setMemberAction({ member: m, kind: "remove" })}>
                        Remove
                      </Button>
                    </span>
                  ),
                },
              ]
            : []),
        ]}
        rows={members.data?.data}
        rowKey={(m) => `${m.user_id}-${m.member_role}`}
        loading={members.loading}
        error={members.error}
        onRetry={() => void members.reload()}
        empty={{ title: "No members in this batch yet" }}
      />
      {manageable ? <BatchStaff batchId={batchId} readOnly={!manage} /> : null}
      {manage ? (
        <>
          <div className="flex justify-end">
            <Button onClick={() => setAdding(true)}>Add student</Button>
          </div>
          <AddMemberDialog
            batchId={batchId}
            existing={new Set((members.data?.data ?? []).filter((m) => m.member_role === "student").map((m) => m.user_id))}
            open={adding}
            onClose={() => setAdding(false)}
            onDone={refresh}
          />
          <MemberActionDialog
            batchId={batchId}
            member={memberAction?.member ?? null}
            kind={memberAction?.kind ?? null}
            onClose={() => setMemberAction(null)}
            onDone={refresh}
          />
        </>
      ) : null}
    </div>
  );
}

const REASON_TEXT: Record<string, string> = {
  weak_required_topics: "Weak in 2+ required topics",
};

function hm(s: number | string): string | null {
  if (typeof s !== "number") return null;
  const m = Math.round(s / 60);
  return `${Math.floor(m / 60)} h ${m % 60} min`;
}

/** ANL-06 batch report view. verified shape: app/modules/analytics/reports.py batch_report. */
export function BatchReportView({
  state,
  studentHref,
  names,
}: {
  state: ApiState<BatchReport>;
  studentHref?: (userId: string) => string;
  names?: Record<string, string | null>;
}) {
  return (
    <Boundary state={state}>
      {(r) => {
        const attention = r.learners.filter((l) => l.needs_attention);
        const name = (id: string) => names?.[id] ?? "Student";
        return (
          <div className="space-y-5">
            <p className="text-xs text-fg-muted">Week starting {formatDate(r.week_start)}</p>
            <div className="grid gap-3 sm:grid-cols-3">
              <StatTile label="Students" value={r.learners_total.toLocaleString("en-IN")} />
              <StatTile label="Median learning time this week" value={r.weekly_learning_time.suppressed ? "Too few to show" : hm(r.weekly_learning_time.median_s)} />
              <StatTile label="90th percentile this week" value={r.weekly_learning_time.suppressed ? "Too few to show" : hm(r.weekly_learning_time.p90_s)} />
            </div>
            <section aria-labelledby="dist-h">
              <h3 id="dist-h" className="mb-2 text-sm font-semibold text-fg">
                Course progress distribution
              </h3>
              <ProgressDistributionView data={r.progress_distribution} />
            </section>
            <section aria-labelledby="funnel-h">
              <h3 id="funnel-h" className="mb-2 text-sm font-semibold text-fg">
                Lesson funnel
              </h3>
              <LessonFunnelView data={r.lesson_funnel} />
            </section>
            <Table
              caption="Students who may need attention"
              showCaption
              columns={[
                {
                  key: "n",
                  header: "Student",
                  cell: (s: BatchReport["learners"][number]) =>
                    studentHref ? (
                      <Link className="text-fg-link underline" href={studentHref(s.user_id)}>
                        {name(s.user_id)}
                      </Link>
                    ) : (
                      name(s.user_id)
                    ),
                },
                { key: "t", header: "Learning time this week", cell: (s) => hm(s.weekly_learning_s) },
                { key: "w", header: "Weak topics", align: "right", cell: (s) => s.weak_topics },
                { key: "r", header: "Why", cell: (s) => s.reasons.map((x) => REASON_TEXT[x] ?? x.replace(/_/g, " ")).join(", ") },
              ]}
              rows={attention}
              rowKey={(s) => s.user_id}
              empty={{ title: "Nobody flagged", description: "No student is currently weak in two or more required topics." }}
            />
          </div>
        );
      }}
    </Boundary>
  );
}

/** ADM-014: Admin view of one batch; student names open the admin account view. */
export function AdminBatchDetail({ batchId }: { batchId: string }) {
  return <BatchDetail batchId={batchId} manageable studentHref={(id) => `/admin/users/${seg(id)}`} />;
}
