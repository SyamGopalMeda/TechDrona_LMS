"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Badge,
  Button,
  Checkbox,
  Dialog,
  EmptyState,
  ErrorState,
  FormField,
  Input,
  Select,
  Table,
  useToast,
} from "@/components/ui";
import { api, type Page } from "@/lib/api/client";
import { isApiError } from "@/lib/api/errors";
import type { Body } from "@/lib/api-types";
import { useMemberNames, useTrainerBatches } from "../lib/batches";
import type { Assignment, AssignmentSummary, Submission } from "../lib/types";
import { useApi, seg, type SendBody } from "../shared/use-api";
import { useGradingBase } from "../shared/portal-base";
import { isStructured } from "@/features/learning/assignment-manager/api";
import {
  LoadingBlock,
  StatusBadge,
  fieldErrorsOf,
  formatDateTime,
  localInputToIso,
  safeExternalUrl,
  useFailToast,
} from "../shared/ui";

/**
 * TRN-008 grading queue: pick an assignment (`GET /assignments?scope=mine`),
 * LRN-16 submissions, LRN-17 grade, LRN-18 release grades, LRN-19 override.
 */
export function GradingQueue() {
  const { base: gradingBase } = useGradingBase();
  const toast = useToast();
  const fail = useFailToast();
  // verified: app/modules/learning/router.py list_assignments (cursor envelope)
  const assignments = useApi<Page<AssignmentSummary>>("assignments", {
    scope: "mine",
    limit: 100,
  });
  const [assignmentId, setAssignmentId] = useState("");
  // verified: app/modules/learning/router.py grading_queue → {data, page}; only `status` filter
  const submissions = useApi<Page<Submission>>(
    assignmentId ? `assignments/${seg(assignmentId)}/submissions` : null,
  );
  const [grading, setGrading] = useState<Submission | null>(null);
  const [busy, setBusy] = useState(false);
  const current = assignments.data?.data.find(
    (a) => a.assignment_id === assignmentId,
  );
  const nameOf = useMemberNames([current?.batch_id]);

  const releaseGrades = async () => {
    setBusy(true);
    try {
      await api.post<Assignment>(
        `assignments/${seg(assignmentId)}/release-grades`,
        {},
      );
      toast.show({ tone: "success", title: "Grades released to students" });
      await assignments.reload();
    } catch (err) {
      fail(err, "Couldn't release grades");
    } finally {
      setBusy(false);
    }
  };

  if (assignments.error)
    return (
      <ErrorState
        error={assignments.error}
        onRetry={() => void assignments.reload()}
      />
    );
  if (assignments.loading && !assignments.data) return <LoadingBlock />;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-64">
          <FormField label="Assignment">
            {(p) => (
              <Select
                {...p}
                value={assignmentId}
                onChange={(e) => setAssignmentId(e.target.value)}
                placeholder="Choose an assignment"
                // Structured assignments are graded on their evaluation screen (the legacy grade
                // endpoint answers 409 for them since SEC-11), so they are listed separately.
                options={(assignments.data?.data ?? []).filter((a) => !isStructured(a)).map((a) => ({
                  value: a.assignment_id,
                  label: `${a.title}${a.batch_name ? ` · ${a.batch_name}` : ""}${a.pending_count ? ` (${a.pending_count} to grade)` : ""}`,
                }))}
              />
            )}
          </FormField>
        </div>
        {assignmentId ? (
          <Button
            variant="secondary"
            onClick={() => void releaseGrades()}
            loading={busy}
            disabled={current?.grades_released}
          >
            {current?.grades_released ? "Grades released" : "Release grades"}
          </Button>
        ) : null}
      </div>
      {assignmentId ? (
        <Table
          caption="Submissions"
          columns={[
            {
              key: "s",
              header: "Student",
              cell: (s: Submission) => (
                <Link
                  className="text-fg-link underline"
                  href={`${gradingBase}/grading/${seg(s.id)}?assignment=${seg(assignmentId)}`}
                >
                  {nameOf(s.user_id)}
                </Link>
              ),
            },
            {
              key: "t",
              header: "Submitted",
              cell: (s) => formatDateTime(s.submitted_at),
            },
            {
              key: "st",
              header: "Status",
              cell: (s) => <StatusBadge status={s.status} />,
            },
            {
              key: "p",
              header: "Points",
              align: "right",
              cell: (s) => <ScoreText s={s} max={current?.max_points} />,
            },
            {
              key: "a",
              header: <span className="sr-only">Actions</span>,
              align: "right",
              cell: (s) => (
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => setGrading(s)}
                  aria-label={`Grade ${nameOf(s.user_id)}`}
                >
                  {s.status === "graded" ? "Regrade" : "Grade"}
                </Button>
              ),
            },
          ]}
          rows={submissions.data?.data}
          rowKey={(s) => s.id}
          loading={submissions.loading}
          error={submissions.error}
          onRetry={() => void submissions.reload()}
          empty={{
            title: "Nothing to grade",
            description: "No submissions for this assignment yet.",
          }}
        />
      ) : (
        <p className="text-sm text-fg-muted">
          Choose an assignment to see its submissions.
        </p>
      )}
      {grading ? (
        <GradeDialog
          submission={grading}
          studentName={nameOf(grading.user_id)}
          maxPoints={current?.max_points}
          rubric={current?.rubric ?? null}
          released={current?.grades_released ?? false}
          onClose={() => setGrading(null)}
          onDone={() => {
            setGrading(null);
            void submissions.reload();
            void assignments.reload();
          }}
        />
      ) : null}
    </div>
  );
}

export interface RubricCriterion {
  key: string;
  label: string;
  max: number | null;
}

/**
 * LRN-14 `assignments.rubric` is `{criteria: [{key, label, max_points}]}` (api `Rubric`). Older
 * rubrics stored before that schema may use `id|name`, `title`, `points|max`, or a flat
 * `{criterion: maxPoints}` map; anything else yields no criteria and grading uses plain points.
 */
export function parseRubric(rubric: unknown): RubricCriterion[] {
  if (!rubric || typeof rubric !== "object") return [];
  const num = (v: unknown) =>
    typeof v === "number" && Number.isFinite(v) && v > 0 ? v : null;
  const str = (v: unknown) => (typeof v === "string" && v.trim() ? v : null);
  const criteria = (rubric as { criteria?: unknown }).criteria;
  if (Array.isArray(criteria))
    return criteria.flatMap((c: unknown, i) => {
      if (!c || typeof c !== "object") return [];
      const o = c as Record<string, unknown>;
      const key =
        str(o.key) ?? str(o.id) ?? str(o.name) ?? `criterion_${i + 1}`;
      return [
        {
          key,
          label: str(o.label) ?? str(o.title) ?? str(o.name) ?? key,
          max: num(o.max_points) ?? num(o.points) ?? num(o.max),
        },
      ];
    });
  return Object.entries(rubric as Record<string, unknown>)
    .filter(([, v]) => num(v) !== null)
    .map(([k, v]) => ({ key: k, label: k, max: num(v) }));
}

/** Final score, with the raw score and late penalty when one was applied (BE-08). */
export function ScoreText({ s, max }: { s: Submission; max?: number }) {
  if (typeof s.score !== "number") return <>—</>;
  const late = typeof s.late_penalty_pct === "number" && s.late_penalty_pct > 0;
  return (
    <span>
      {s.score}
      {max !== undefined ? ` / ${max}` : ""}
      {late ? (
        <span className="block text-xs text-fg-muted">
          {s.raw_score ?? "?"} before −{s.late_penalty_pct}% late penalty
        </span>
      ) : null}
    </span>
  );
}

/**
 * LRN-14 `rubric` in the documented shape (apps/api learning/router.py `Rubric`):
 * `{criteria: [{key, label, max_points}]}`. Keys come from the labels and stay unique.
 */
export function buildRubric(rows: { label: string; max_points: string }[]): { criteria: { key: string; label: string; max_points: number }[] } | null {
  const filled = rows.filter((r) => r.label.trim() || r.max_points.trim());
  if (!filled.length) return null;
  const seen = new Set<string>();
  return {
    criteria: filled.map((r, i) => {
      const base = r.label.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 56) || `criterion_${i + 1}`;
      let key = base;
      for (let n = 2; seen.has(key); n++) key = `${base}_${n}`;
      seen.add(key);
      return { key, label: r.label.trim(), max_points: Number(r.max_points) };
    }),
  };
}

const rubricMessage = (errors: Record<string, string>) => errors.rubric ?? Object.entries(errors).find(([k]) => k.startsWith("rubric."))?.[1];

/** Client checks matching the api's `_check_rubric` (labels, points > 0, total ≤ max score). */
export function rubricErrors(rows: { label: string; max_points: string }[], maxScore: number): string | null {
  const r = buildRubric(rows);
  if (!r) return null;
  if (r.criteria.length > 30) return "Use at most 30 criteria.";
  if (r.criteria.some((c) => !c.label)) return "Give every criterion a name.";
  if (r.criteria.some((c) => !(c.max_points > 0))) return "Give every criterion points above 0.";
  const total = r.criteria.reduce((a, c) => a + c.max_points, 0);
  if (Number.isFinite(maxScore) && total > maxScore) return `The criteria add up to ${total}, more than the assignment's ${maxScore} points.`;
  return null;
}

/** ADM-47: LRN-16b short-lived download URL for one attached file, opened in a new tab. */
function SubmissionFiles({ submission }: { submission: Submission }) {
  const fail = useFailToast();
  const [busy, setBusy] = useState<number | null>(null);
  const open = async (i: number) => {
    setBusy(i);
    try {
      const r = await api.get<{ url: string; filename: string }>(
        `assignment-submissions/${seg(submission.id)}/files/${i}`,
      );
      const url = safeExternalUrl(r.url);
      if (url) window.open(url, "_blank", "noopener,noreferrer");
    } catch (err) {
      fail(err, "Couldn't open the file");
    } finally {
      setBusy(null);
    }
  };
  return (
    <ul aria-label="Attached files" className="space-y-1 text-sm">
      {submission.file_s3_keys.map((k, i) => {
        const name = k.split("/").pop() || `File ${i + 1}`;
        return (
          <li key={k} className="flex items-center justify-between gap-2">
            <span className="truncate text-fg-secondary">{name}</span>
            <Button
              size="sm"
              variant="secondary"
              loading={busy === i}
              onClick={() => void open(i)}
              aria-label={`Download ${name}`}
            >
              Download
            </Button>
          </li>
        );
      })}
    </ul>
  );
}

interface CodeSubmissionView {
  language_key: string;
  status: string;
  verdict: string | null;
  passed_cases: number | null;
  total_cases: number | null;
  source_code?: string | null;
}

/** ADM-47: `GET /coding/submissions/{id}` (staff with submission.code.read also get the source). */
function CodeSubmissionPanel({ id }: { id: string }) {
  const code = useApi<CodeSubmissionView>(`coding/submissions/${seg(id)}`);
  if (code.error)
    return isApiError(code.error) && code.error.status === 404 ? (
      <p className="text-sm text-fg-muted">
        The code for this submission isn&apos;t available with your access.
      </p>
    ) : (
      <ErrorState error={code.error} onRetry={() => void code.reload()} />
    );
  if (code.loading || !code.data)
    return <LoadingBlock rows={2} label="Loading code" />;
  const c = code.data;
  return (
    <div className="space-y-2">
      <p className="text-sm text-fg-secondary">
        {c.language_key} · {c.verdict ?? c.status}
        {c.total_cases != null
          ? ` · ${c.passed_cases ?? 0}/${c.total_cases} tests passed`
          : ""}
      </p>
      {c.source_code ? (
        <pre
          aria-label="Submitted code"
          className="max-h-72 overflow-auto rounded-lg bg-surface-sunken p-3 font-mono text-xs text-fg"
        >
          {c.source_code}
        </pre>
      ) : (
        <p className="text-sm text-fg-muted">
          Source code isn&apos;t shared with your role.
        </p>
      )}
    </div>
  );
}

function GradeDialog({
  submission,
  studentName,
  maxPoints,
  rubric,
  released,
  onClose,
  onDone,
}: {
  submission: Submission;
  studentName: string;
  maxPoints?: number;
  rubric?: unknown;
  released: boolean;
  onClose: () => void;
  onDone: () => void;
}) {
  const toast = useToast();
  const fail = useFailToast();
  const [points, setPoints] = useState(
    submission.score != null ? String(submission.score) : "",
  );
  const [feedback, setFeedback] = useState(submission.feedback_md ?? "");
  const [returnIt, setReturnIt] = useState(false);
  const [reason, setReason] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const isOverride = released && submission.status === "graded";
  const criteria = parseRubric(rubric);
  const [crit, setCrit] = useState<Record<string, string>>(() => {
    const prev = submission.rubric_scores ?? {};
    return Object.fromEntries(
      criteria.map((c) => [
        c.key,
        typeof prev[c.key] === "number" ? String(prev[c.key]) : "",
      ]),
    );
  });
  const critTotal = criteria.reduce(
    (n, c) => n + (Number(crit[c.key]) || 0),
    0,
  );
  const useRubric = criteria.length > 0 && !returnIt;

  const submit = async () => {
    const errs: Record<string, string> = {};
    if (useRubric)
      for (const c of criteria) {
        const v = Number(crit[c.key]);
        if (
          crit[c.key] === "" ||
          !Number.isFinite(v) ||
          v < 0 ||
          (c.max !== null && v > c.max)
        )
          errs[`rubric_scores.${c.key}`] =
            c.max !== null ? `Enter 0 to ${c.max}.` : "Enter the points.";
      }
    const n = useRubric ? critTotal : Number(points);
    if (
      !returnIt &&
      ((!useRubric && points === "") ||
        !Number.isFinite(n) ||
        n < 0 ||
        (maxPoints !== undefined && n > maxPoints))
    )
      errs.score =
        maxPoints !== undefined
          ? `Enter 0 to ${maxPoints}.`
          : "Enter the points.";
    if (isOverride && reason.trim().length < 5)
      errs.reason =
        "Changing a released grade needs a reason (at least 5 characters).";
    if (returnIt && !isOverride && reason.trim().length < 1)
      errs.returned_reason = "Say what the student should change.";
    setErrors(errs);
    if (Object.keys(errs).length) return;
    setBusy(true);
    try {
      if (isOverride)
        await api.post(
          `assignment-submissions/${seg(submission.id)}/grade-override`,
          {
            score: n,
            reason: reason.trim(),
            feedback_md: feedback.trim() || null,
          } satisfies Body<
            "assignment-submissions/{submission_id}/grade-override",
            "post"
          >,
        );
      else
        await api.post(
          `assignment-submissions/${seg(submission.id)}/grade`,
          (returnIt
            ? {
                action: "return",
                returned_reason: reason.trim(),
                feedback_md: feedback.trim() || null,
              }
            : {
                action: "grade",
                // With a rubric the api totals rubric_scores itself (LRN-17); score is omitted.
                ...(useRubric ? {} : { score: n }),
                ...(useRubric
                  ? {
                      rubric_scores: Object.fromEntries(
                        criteria.map((c) => [c.key, Number(crit[c.key])]),
                      ),
                    }
                  : {}),
                feedback_md: feedback.trim() || null,
              }) satisfies Body<
            "assignment-submissions/{submission_id}/grade",
            "post"
          >,
        );
      toast.show({
        tone: "success",
        title: returnIt ? "Returned for resubmission" : "Grade saved",
      });
      onDone();
    } catch (err) {
      const fe = fieldErrorsOf(err);
      if (Object.keys(fe).length) setErrors(fe);
      else fail(err, "Couldn't save the grade");
    } finally {
      setBusy(false);
    }
  };

  const link = safeExternalUrl(submission.link_url);

  return (
    <Dialog
      open
      onClose={onClose}
      dismissible={!busy}
      title={`Grade ${studentName}`}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void submit()} loading={busy}>
            {isOverride ? "Change grade" : returnIt ? "Return" : "Save grade"}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        {submission.body_text ? (
          <p className="whitespace-pre-wrap rounded-lg bg-surface-sunken p-3 text-sm text-fg">
            {submission.body_text}
          </p>
        ) : null}
        {link ? (
          <p className="text-sm">
            <a
              className="text-fg-link underline"
              href={link}
              target="_blank"
              rel="noopener noreferrer"
            >
              Open submitted link
            </a>
          </p>
        ) : null}
        {submission.file_s3_keys.length ? (
          <SubmissionFiles submission={submission} />
        ) : null}
        {typeof submission.late_penalty_pct === "number" && submission.late_penalty_pct > 0 ? (
          <p className="text-sm text-fg-secondary">
            Submitted late: a {submission.late_penalty_pct}% penalty applies. Last grade {submission.raw_score ?? "—"} → {submission.score ?? "—"} after the penalty.
          </p>
        ) : submission.status === "late" ? (
          <p className="text-sm text-fg-secondary">Submitted late: the assignment&apos;s late penalty is applied to the points you give.</p>
        ) : null}
        {submission.code_submission_id ? (
          <CodeSubmissionPanel id={submission.code_submission_id} />
        ) : null}
        {useRubric ? (
          <fieldset className="space-y-2 rounded-lg border border-line p-3">
            <legend className="px-1 text-sm font-semibold text-fg">
              Rubric
            </legend>
            {criteria.map((c) => (
              <FormField
                key={c.key}
                label={`${c.label}${c.max !== null ? ` (out of ${c.max})` : ""}`}
                required
                error={errors[`rubric_scores.${c.key}`]}
              >
                {(p) => (
                  <Input
                    {...p}
                    type="number"
                    min={0}
                    inputMode="decimal"
                    value={crit[c.key] ?? ""}
                    onChange={(e) =>
                      setCrit((x) => ({ ...x, [c.key]: e.target.value }))
                    }
                  />
                )}
              </FormField>
            ))}
          </fieldset>
        ) : null}
        <FormField
          label={`Points${maxPoints !== undefined ? ` (out of ${maxPoints})` : ""}`}
          required={!returnIt}
          error={errors.score}
        >
          {(p) => (
            <Input
              {...p}
              type="number"
              min={0}
              inputMode="decimal"
              value={useRubric ? String(critTotal) : points}
              onChange={(e) => setPoints(e.target.value)}
              disabled={returnIt}
              readOnly={useRubric}
            />
          )}
        </FormField>
        <FormField label="Feedback" error={errors.feedback_md}>
          {(p) => (
            <textarea
              {...p}
              rows={4}
              className="w-full rounded-md border border-line-control bg-surface p-2 text-sm text-fg focus-visible:shadow-focus focus-visible:outline-none"
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
            />
          )}
        </FormField>
        {isOverride ? (
          <FormField
            label="Reason for changing a released grade"
            required
            error={errors.reason}
          >
            {(p) => (
              <Input
                {...p}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
            )}
          </FormField>
        ) : (
          <>
            <Checkbox
              label="Return for resubmission"
              description="The student can submit again; no grade is recorded."
              checked={returnIt}
              onChange={(e) => setReturnIt(e.target.checked)}
            />
            {returnIt ? (
              <FormField
                label="What should the student change?"
                required
                error={errors.returned_reason}
              >
                {(p) => (
                  <Input
                    {...p}
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                  />
                )}
              </FormField>
            ) : null}
          </>
        )}
      </div>
    </Dialog>
  );
}

const SUBMISSION_TYPES = [
  { value: "file", label: "File upload" },
  { value: "text", label: "Text answer" },
  { value: "link", label: "Link" },
  { value: "code", label: "Code" },
];

/** TRN-012 assignments: list (`GET /assignments?scope=mine`) + create (LRN-14). */
export function TrainerAssignments() {
  const toast = useToast();
  const fail = useFailToast();
  const { batches } = useTrainerBatches();
  const list = useApi<Page<AssignmentSummary>>("assignments", {
    scope: "mine",
    limit: 100,
  });
  const [open, setOpen] = useState(false);
  const blank = {
    batch_id: "",
    title: "",
    instructions: "",
    due: "",
    max_points: "10",
    submission_type: "file" as Assignment["submission_type"],
  };
  const [f, setF] = useState(blank);
  const [criteria, setCriteria] = useState<{ label: string; max_points: string }[]>([]);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) =>
    setF((x) => ({ ...x, [k]: e.target.value }));

  const submit = async () => {
    const errs: Record<string, string> = {};
    const due = localInputToIso(f.due);
    if (!f.batch_id) errs.batch_id = "Choose a batch.";
    if (!f.title.trim()) errs.title = "Enter a title.";
    if (!f.instructions.trim())
      errs.instructions_md = "Enter instructions for students.";
    if (!due) errs.due_at = "Choose a due date.";
    if (!(Number(f.max_points) > 0))
      errs.max_score = "Points must be more than 0.";
    const rubricError = rubricErrors(criteria, Number(f.max_points));
    if (rubricError) errs.rubric = rubricError;
    setErrors(errs);
    if (Object.keys(errs).length) return;
    setBusy(true);
    try {
      await api.post("assignments", {
        batch_id: f.batch_id,
        title: f.title.trim(),
        instructions_md: f.instructions.trim(),
        submission_type: f.submission_type,
        due_at: due,
        max_score: Number(f.max_points),
        ...(buildRubric(criteria) ? { rubric: buildRubric(criteria)! } : {}),
      } satisfies SendBody<"assignments", "post">);
      toast.show({ tone: "success", title: "Assignment created" });
      setOpen(false);
      setF(blank);
      setCriteria([]);
      await list.reload();
    } catch (err) {
      const fe = fieldErrorsOf(err);
      if (Object.keys(fe).length) setErrors(fe);
      else fail(err, "Couldn't create the assignment");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button onClick={() => setOpen(true)}>New assignment</Button>
      </div>
      <Table
        caption="Assignments"
        columns={[
          {
            key: "t",
            header: "Assignment",
            cell: (a: AssignmentSummary) => a.title,
          },
          { key: "b", header: "Batch", cell: (a) => a.batch_name ?? "—" },
          { key: "d", header: "Due", cell: (a) => formatDateTime(a.due_at) },
          {
            key: "p",
            header: "To grade",
            align: "right",
            cell: (a) => a.pending_count,
          },
          {
            key: "r",
            header: "Grades",
            cell: (a) =>
              a.grades_released ? (
                <Badge tone="success">Released</Badge>
              ) : (
                <Badge>Not released</Badge>
              ),
          },
        ]}
        rows={list.data?.data}
        rowKey={(a) => a.assignment_id}
        loading={list.loading}
        error={list.error}
        onRetry={() => void list.reload()}
        empty={{
          title: "No assignments yet",
          action: <Button onClick={() => setOpen(true)}>New assignment</Button>,
        }}
      />
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        dismissible={!busy}
        title="New assignment"
        footer={
          <>
            <Button
              variant="secondary"
              onClick={() => setOpen(false)}
              disabled={busy}
            >
              Cancel
            </Button>
            <Button onClick={() => void submit()} loading={busy}>
              Create
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <FormField label="Batch" required error={errors.batch_id}>
            {(p) => (
              <Select
                {...p}
                value={f.batch_id}
                onChange={set("batch_id")}
                placeholder="Choose a batch"
                options={(batches ?? []).map((b) => ({
                  value: b.id,
                  label: b.name,
                }))}
              />
            )}
          </FormField>
          <FormField label="Title" required error={errors.title}>
            {(p) => <Input {...p} value={f.title} onChange={set("title")} />}
          </FormField>
          <FormField
            label="Instructions"
            required
            error={errors.instructions_md}
          >
            {(p) => (
              <textarea
                {...p}
                rows={4}
                className="w-full rounded-md border border-line-control bg-surface p-2 text-sm text-fg focus-visible:shadow-focus focus-visible:outline-none"
                value={f.instructions}
                onChange={set("instructions")}
              />
            )}
          </FormField>
          <div className="grid gap-3 sm:grid-cols-2">
            <FormField label="Due" required error={errors.due_at}>
              {(p) => (
                <Input
                  {...p}
                  type="datetime-local"
                  value={f.due}
                  onChange={set("due")}
                />
              )}
            </FormField>
            <FormField label="Points" required error={errors.max_score}>
              {(p) => (
                <Input
                  {...p}
                  type="number"
                  min={1}
                  inputMode="numeric"
                  value={f.max_points}
                  onChange={set("max_points")}
                />
              )}
            </FormField>
          </div>
          <FormField label="Students submit" error={errors.submission_type}>
            {(p) => (
              <Select
                {...p}
                value={f.submission_type}
                onChange={set("submission_type")}
                options={SUBMISSION_TYPES}
              />
            )}
          </FormField>
          <fieldset className="space-y-2 rounded-lg border border-line p-3">
            <legend className="px-1 text-sm font-semibold text-fg">Rubric (optional)</legend>
            <p className="text-xs text-fg-muted">Grade against named criteria. Their points must add up to no more than the assignment&apos;s points.</p>
            {criteria.map((c, i) => (
              <div key={i} className="flex flex-wrap items-end gap-2">
                <div className="min-w-40 flex-1">
                  <FormField label={`Criterion ${i + 1}`}>
                    {(p) => <Input {...p} value={c.label} maxLength={200} onChange={(e) => setCriteria((xs) => xs.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)))} />}
                  </FormField>
                </div>
                <div className="w-28">
                  <FormField label={`Criterion ${i + 1} points`}>
                    {(p) => <Input {...p} type="number" min={0} inputMode="decimal" value={c.max_points} onChange={(e) => setCriteria((xs) => xs.map((x, j) => (j === i ? { ...x, max_points: e.target.value } : x)))} />}
                  </FormField>
                </div>
                <Button size="sm" variant="ghost" onClick={() => setCriteria((xs) => xs.filter((_, j) => j !== i))} aria-label={`Remove criterion ${i + 1}`}>
                  Remove
                </Button>
              </div>
            ))}
            {rubricMessage(errors) ? (
              <p role="alert" className="text-sm text-danger-fg">
                {rubricMessage(errors)}
              </p>
            ) : null}
            <Button size="sm" variant="secondary" disabled={criteria.length >= 30} onClick={() => setCriteria((xs) => [...xs, { label: "", max_points: "" }])}>
              Add criterion
            </Button>
          </fieldset>
        </div>
      </Dialog>
    </div>
  );
}

/** TRN-010 lives in ./Integrity (ASM-19/20); re-exported for existing imports. */
export { IntegrityReview } from "./Integrity";

/**
 * TRN-009 grade one submission: loaded by id (LRN-16a `GET /assignment-submissions/{id}`);
 * the assignment (max points, release state, batch) comes from the trainer's assignment list.
 * `?assignment=` is optional. Grading uses LRN-17/19.
 */
export function GradeSubmission({
  submissionId,
  assignmentId,
}: {
  submissionId: string;
  assignmentId: string | null;
}) {
  const router = useRouter();
  const submission = useApi<Submission>(`assignment-submissions/${seg(submissionId)}`);
  const aid = assignmentId ?? submission.data?.assignment_id ?? null;
  const assignments = useApi<Page<AssignmentSummary>>(
    aid ? "assignments" : null,
    { scope: "mine", limit: 100 },
  );
  const current = assignments.data?.data.find((a) => a.assignment_id === aid);
  const nameOf = useMemberNames([current?.batch_id]);
  const { gradingHome: backHref } = useGradingBase();
  const back = () => router.push(backHref);

  if (submission.error && isApiError(submission.error) && submission.error.status === 404)
    return (
      <EmptyState
        title="Submission not found"
        description="It may have been removed, or it belongs to a batch you don't teach."
        action={<Button onClick={back}>Go to grading queue</Button>}
      />
    );
  const err = submission.error ?? assignments.error;
  if (err)
    return <ErrorState error={err} onRetry={() => void submission.reload()} />;
  if (!submission.data || !assignments.data) return <LoadingBlock />;
  const sub = submission.data;
  return (
    <GradeDialog
      submission={sub}
      studentName={nameOf(sub.user_id)}
      maxPoints={current?.max_points}
      rubric={current?.rubric ?? null}
      released={current?.grades_released ?? false}
      onClose={back}
      onDone={back}
    />
  );
}
