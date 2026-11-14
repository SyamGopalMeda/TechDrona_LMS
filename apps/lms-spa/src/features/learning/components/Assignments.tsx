"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { StatusBadge, Badge, Button, Card, ErrorState, PageHeader, Table, Tabs, useToast } from "@/components/ui";
import { api } from "@/lib/api/client";
import { formatDateTime, humanize } from "@/features/catalog/lib/format";
import type { Paged } from "@/features/catalog/lib/types";
import type { AssignmentDetailDto, AssignmentDto, AssignmentListItemDto, SubmissionBody, SubmissionDto } from "../lib/types";
import { MAX_ASSIGNMENT_FILE_MB, uploadAssignmentFile } from "../lib/upload";
import { StructuredAssignment } from "../assignment-workspace/StructuredAssignment";
import { isStructured } from "../assignment-manager/api";
import { useResource } from "../lib/use-resource";
import { ContentErrorState, LoadingBlock } from "./States";


const MAX_FILE_MB = MAX_ASSIGNMENT_FILE_MB;

export function AssignmentStatus({ status }: { status: string }) {
  const label = status === "returned" ? "Returned for changes" : humanize(status);
  return <StatusBadge status={status} label={label} />;
}

/**
 * Learner-facing status from the api's `my_status` (latest submission status or
 * "not_submitted"), the submission `window` and whether grades are released.
 */
export function displayStatus(a: Pick<AssignmentDto, "window" | "grades_released"> & { my_status: string }): string {
  switch (a.my_status) {
    case "not_submitted":
      return a.window === "closed" ? "missed" : "due";
    case "graded":
      return a.grades_released ? "graded" : "submitted";
    default:
      return a.my_status;
  }
}

const FILTERS: { id: string; label: string; includes: string[] }[] = [
  { id: "due", label: "Due", includes: ["due", "returned", "missed"] },
  { id: "submitted", label: "Submitted", includes: ["submitted", "late"] },
  { id: "graded", label: "Graded", includes: ["graded"] },
];

function AssignmentTable({ filter }: { filter: (typeof FILTERS)[number] }) {
  // LRN-08 returns all eligible assignments in one page and takes no status filter
  // (verified: learning/router.py my_assignments), so tabs filter client-side.
  const { data, error, loading, reload } = useResource<Paged<AssignmentListItemDto>>("me/assignments");
  const rows = data?.data.filter((r) => filter.includes.includes(displayStatus(r)));
  return (
    <Table<AssignmentListItemDto>
      caption={`${filter.label} assignments`}
      rows={rows}
      rowKey={(r) => r.id}
      loading={loading}
      error={error}
      onRetry={reload}
      empty={{
        title: filter.id === "due" ? "Nothing due right now" : `No ${filter.id} assignments`,
        description: filter.id === "due" ? "When your trainer assigns work, it appears here with its due date." : undefined,
      }}
      columns={[
        {
          key: "title",
          header: "Assignment",
          cell: (r) => (
            <Link href={`/app/assignments/${encodeURIComponent(r.id)}`} className="font-medium text-fg-link hover:text-fg-link-hover">
              {r.title}
            </Link>
          ),
        },
        { key: "due", header: "Due", cell: (r) => <span className="tabular-nums">{formatDateTime(r.due_at)}</span> },
        { key: "status", header: "Status", cell: (r) => <AssignmentStatus status={displayStatus(r)} /> },
        { key: "grade", header: "Grade", align: "right", cell: (r) => (r.my_score !== null ? <span className="tabular-nums">{`${r.my_score} / ${r.max_score}`}</span> : "—") },
      ]}
    />
  );
}

/** STU-007 assignments (LRN-08). */
export function AssignmentsList() {
  return <Tabs label="Assignment status" items={FILTERS.map((f) => ({ id: f.id, label: f.label, content: <AssignmentTable filter={f} /> }))} />;
}

function SubmissionForm({ assignment, onSubmitted }: { assignment: AssignmentDetailDto; onSubmitted: () => Promise<void> }) {
  const toast = useToast();
  const kind = assignment.submission_type;
  const [files, setFiles] = useState<File[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [localError, setLocalError] = useState<string | null>(null);
  const allowed = assignment.allowed_file_types;
  const accept = allowed.length ? allowed.map((t) => (t.startsWith(".") ? t : `.${t}`)).join(",") : undefined;

  async function uploadFiles(): Promise<string[]> {
    const keys: string[] = [];
    for (const f of files) keys.push(await uploadAssignmentFile(f));
    return keys;
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLocalError(null);
    if (kind === "file") {
      if (files.length === 0) return setLocalError("Choose at least one file.");
      if (files.length > 5) return setLocalError("Attach at most 5 files.");
      const tooBig = files.find((f) => f.size > MAX_FILE_MB * 1024 * 1024);
      if (tooBig) return setLocalError(`${tooBig.name} is larger than ${MAX_FILE_MB} MB.`);
    } else if (!text.trim()) {
      return setLocalError(kind === "link" ? "Add a link." : "Write your answer.");
    }
    setBusy(true);
    try {
      const body: SubmissionBody = kind === "file" ? { file_s3_keys: await uploadFiles() } : kind === "link" ? { link_url: text.trim() } : { body_text: text };
      await api.post(`me/assignments/${encodeURIComponent(assignment.id)}/submissions`, body, { idempotencyKey: true });
      toast.show({ title: "Submission received.", tone: "success" });
      setFiles([]);
      setText("");
      await onSubmitted();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3" aria-label="Submit your work">
      {kind === "file" ? (
        <div>
          <label htmlFor="asg-files" className="block text-sm font-medium text-fg">
            Files
          </label>
          <input
            id="asg-files"
            type="file"
            multiple
            accept={accept}
            aria-describedby="asg-files-hint"
            onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
            className="mt-1 block text-sm text-fg"
          />
          <p id="asg-files-hint" className="mt-1 text-xs text-fg-muted">
            Up to 5 files, {MAX_FILE_MB} MB each{allowed.length ? `; allowed: ${allowed.join(", ")}` : ""}.
          </p>
        </div>
      ) : (
        <div>
          <label htmlFor="asg-text" className="block text-sm font-medium text-fg">
            {kind === "link" ? "Link (https://…)" : "Your answer"}
          </label>
          {kind === "link" ? (
            <input id="asg-text" type="url" value={text} onChange={(e) => setText(e.target.value)} className="mt-1 block w-full rounded-md border border-line bg-surface px-3 py-2 text-sm text-fg" />
          ) : (
            <textarea id="asg-text" rows={8} value={text} onChange={(e) => setText(e.target.value)} className="mt-1 block w-full rounded-md border border-line bg-surface px-3 py-2 text-sm text-fg" />
          )}
        </div>
      )}
      {localError ? (
        <p role="alert" className="text-sm text-danger-fg">
          {localError}
        </p>
      ) : null}
      <Button type="submit" loading={busy}>
        Submit work
      </Button>
      {error ? <ErrorState error={error} /> : null}
    </form>
  );
}

function canSubmit(a: AssignmentDetailDto): boolean {
  if (a.status !== "active" || a.window === "closed") return false;
  if (a.available_from && Date.parse(a.available_from) > Date.now()) return false;
  const last = a.submissions[a.submissions.length - 1];
  return !last || last.status === "returned" || a.submissions.length < a.max_attempts;
}

/** STU-008 assignment detail & submission (LRN-09, MED-02 → LRN-10). */
export function AssignmentDetail({ assignmentId }: { assignmentId: string }) {
  const { data, error, loading, reload } = useResource<AssignmentDetailDto>(`me/assignments/${encodeURIComponent(assignmentId)}`);
  if (error) return <ContentErrorState error={error} onRetry={reload} />;
  if (loading && !data) return <LoadingBlock label="Loading assignment" />;
  if (!data) return null;
  if (isStructured(data as AssignmentDto & { structured?: boolean })) return <StructuredAssignment assignmentId={assignmentId} />;
  const subs = data.submissions;
  const last: SubmissionDto | undefined = subs[subs.length - 1];
  const status = displayStatus({ ...data, my_status: last?.status ?? "not_submitted" });
  const graded = data.grades_released && last && typeof last.score === "number" ? last : null;
  return (
    <div className="space-y-6">
      <PageHeader
        breadcrumbs={[{ label: "Assignments", href: "/app/assignments" }, { label: data.title }]}
        title={data.title}
        description={data.due_at ? `Due ${formatDateTime(data.due_at)}` : undefined}
        meta={<AssignmentStatus status={status} />}
      />
      {data.instructions_md ? (
        <Card title="Instructions">
          <p className="whitespace-pre-line text-sm text-fg-secondary">{data.instructions_md}</p>
          {data.late_until ? (
            <p className="mt-3 text-xs text-fg-muted">
              Late submissions accepted until {formatDateTime(data.late_until)}
              {data.late_penalty_pct ? ` with a ${data.late_penalty_pct}% penalty` : ""}.
            </p>
          ) : null}
        </Card>
      ) : null}
      {graded ? (
        <Card title="Grade">
          <p className="font-display text-2xl font-bold tabular-nums text-fg">
            {graded.score} / {data.max_score}
          </p>
          {graded.feedback_md ? <p className="mt-2 whitespace-pre-line text-sm text-fg-secondary">{graded.feedback_md}</p> : null}
        </Card>
      ) : null}
      <Card title="Your submissions">
        {subs.length === 0 ? (
          <p className="text-sm text-fg-muted">You haven’t submitted anything yet.</p>
        ) : (
          <ul className="space-y-2">
            {subs.map((s) => (
              <li key={s.id} className="rounded-md border border-line p-3 text-sm">
                <p className="text-fg">
                  {formatDateTime(s.submitted_at)} · {humanize(s.status === "graded" && !data.grades_released ? "submitted" : s.status)}
                  {s.status === "late" ? <Badge tone="warning" className="ml-2">Late</Badge> : null}
                </p>
                {s.file_s3_keys.length ? <p className="text-xs text-fg-muted">{s.file_s3_keys.map((k) => k.split("/").pop()).join(", ")}</p> : null}
                {s.returned_reason ? <p className="text-xs text-fg-muted">Returned: {s.returned_reason}</p> : null}
              </li>
            ))}
          </ul>
        )}
      </Card>
      {canSubmit(data) && data.submission_type !== "code" ? (
        <Card title={subs.length ? "Resubmit" : "Submit your work"}>
          <SubmissionForm assignment={data} onSubmitted={reload} />
        </Card>
      ) : null}
    </div>
  );
}
