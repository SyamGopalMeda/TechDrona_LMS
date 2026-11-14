"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { Button, Card, Checkbox, ConfirmDialog, Dialog, FormField, Input, PageHeader, Pagination, Select, Table, nextCursorStack, previousCursorStack, useToast, type Crumb } from "@/components/ui";
import { api } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { Body, Schema } from "@/lib/api-types";
import { useApi, seg } from "@/features/trainer/shared/use-api";
import { Boundary, StatusBadge, fieldErrorsOf, localInputToIso, useFailToast } from "@/features/trainer/shared/ui";
import type { TestSummary } from "@/features/trainer/lib/types";
import { ExamProtocolSettings, validateProtocol } from "@/features/assessment/components/ExamProtocolSettings";
import { QuestionBankPicker } from "@/features/question-bank/QuestionBankPicker";
import { EntityHeader, SectionNav, StickyActionBar } from "./EditorChrome";
import type { PublishedCodingProblem, QuestionSummary, TestDefinition, TestSectionOut, ValidationResult } from "../lib/types";

type TestKind = Schema<"TestCreate">["test_kind"];
type Phase = Schema<"PhaseVisibility">;

const KINDS: { value: TestKind; label: string }[] = [
  { value: "mock", label: "Mock test" },
  { value: "practice_set", label: "Practice set" },
  { value: "company_mock", label: "Company mock" },
  { value: "diagnostic", label: "Diagnostic" },
  { value: "course_quiz", label: "Course quiz" },
  { value: "drive", label: "Placement drive (proctored)" },
];

export interface BatchOption {
  value: string;
  label: string;
}

/**
 * ASM-04 "New test" dialog. With `batches` (trainer portal), a batch is required and sent as
 * `batch_id` — the api's scope hint for batch-scoped trainers (ADM-43); without it the test is
 * created at the caller's own scope (content studio).
 */
export function NewTestDialog({
  open,
  onClose,
  onCreated,
  batches,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (test: TestSummary) => void;
  batches?: BatchOption[];
}) {
  const fail = useFailToast();
  const [f, setF] = useState({ title: "", kind: "mock" as TestKind, duration_minutes: "60", batch_id: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const batchId = f.batch_id || (batches?.length === 1 ? batches[0]!.value : "");

  const create = async () => {
    const errs: Record<string, string> = {};
    if (f.title.trim().length < 3) errs.title = "Enter a title.";
    const mins = Number(f.duration_minutes);
    if (!Number.isInteger(mins) || mins < 5 || mins > 360) errs.duration_seconds = "Between 5 and 360 minutes.";
    if (batches && !batchId) errs.batch_id = "Choose the batch this test is for.";
    setErrors(errs);
    if (Object.keys(errs).length) return;
    setBusy(true);
    try {
      const res = await api.post<TestSummary>("studio/tests", {
        title: f.title.trim(),
        test_kind: f.kind,
        duration_seconds: mins * 60,
        navigation_mode: "free",
        attempts_allowed: 1,
        ...(batches ? { batch_id: batchId } : {}),
      } satisfies Partial<Body<"studio/tests", "post">>);
      if (res.kind === "ok") onCreated(res.data);
    } catch (err) {
      const fe = fieldErrorsOf(err);
      if (Object.keys(fe).length) setErrors(fe);
      else fail(err, "Couldn't create the test");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      dismissible={!busy}
      title="New test"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void create()} loading={busy}>
            Create draft
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <FormField label="Title" required error={errors.title}>
          {(p) => <Input {...p} value={f.title} onChange={(e) => setF((x) => ({ ...x, title: e.target.value }))} />}
        </FormField>
        <FormField label="Kind">{(p) => <Select {...p} value={f.kind} onChange={(e) => setF((x) => ({ ...x, kind: e.target.value as TestKind }))} options={KINDS} />}</FormField>
        <FormField label="Duration (minutes)" required error={errors.duration_seconds}>
          {(p) => <Input {...p} type="number" min={5} inputMode="numeric" value={f.duration_minutes} onChange={(e) => setF((x) => ({ ...x, duration_minutes: e.target.value }))} />}
        </FormField>
        {batches ? (
          <FormField label="Batch" required error={errors.batch_id} hint="The test is created for this batch.">
            {(p) => <Select {...p} value={batchId} onChange={(e) => setF((x) => ({ ...x, batch_id: e.target.value }))} placeholder="Choose a batch" options={batches} />}
          </FormField>
        ) : null}
      </div>
    </Dialog>
  );
}

/** ADM-49: a test created for a batch (`tests.batch_id`) is editable by every trainer of that batch. */
export function BatchOwned({ batchId }: { batchId: string }) {
  return (
    <span className="inline-flex items-center rounded-full border border-line-subtle px-2 py-0.5 text-xs text-fg-secondary" title={`Batch ${batchId}`}>
      Batch-owned
    </span>
  );
}

/**
 * CMS-011 test blueprints / template mocks (ASM-03, ASM-04). With `header`, the page header is
 * rendered here so "New test" sits in its actions slot (one primary per view).
 */
export function TestBlueprints({ hrefPattern, header }: { hrefPattern: string; header?: { title: string; description?: string } }) {
  const editHref = (id: string) => hrefPattern.replace(":id", encodeURIComponent(id));
  const router = useRouter();
  // verified: app/modules/assessments/router.py asm_03_list_tests → {items: test_out[], page} (BE-21 cursor)
  const [cursors, setCursors] = useState<(string | undefined)[]>([undefined]);
  const tests = useApi<{ items: TestSummary[]; page?: { next_cursor: string | null; has_more: boolean } }>("studio/tests", {
    cursor: cursors[cursors.length - 1],
  });
  const page = tests.data?.page;
  const [open, setOpen] = useState(false);

  return (
    <div className="space-y-4">
      {header ? (
        <PageHeader title={header.title} description={header.description} actions={<Button onClick={() => setOpen(true)}>New test</Button>} />
      ) : (
        <div className="flex justify-end">
          <Button onClick={() => setOpen(true)}>New test</Button>
        </div>
      )}
      <Table
        caption="Tests"
        columns={[
          {
            key: "t",
            header: "Test",
            cell: (t: TestSummary) => (
              <Link className="text-fg-link underline" href={editHref(t.id)}>
                {t.title}
              </Link>
            ),
          },
          { key: "k", header: "Kind", cell: (t) => testKindLabel(t.test_kind) },
          { key: "d", header: "Duration", cell: (t) => (t.duration_seconds ? `${Math.round(t.duration_seconds / 60)} min` : "—") },
          { key: "o", header: "Owner", cell: (t) => (t.batch_id ? <BatchOwned batchId={t.batch_id} /> : <span className="text-fg-muted">—</span>) },
          { key: "s", header: "Status", cell: (t) => <StatusBadge status={t.status} /> },
        ]}
        rows={tests.data?.items}
        rowKey={(t) => t.id}
        loading={tests.loading}
        error={tests.error}
        onRetry={() => void tests.reload()}
        empty={{ title: "No tests yet", description: "Create a template mock, add sections and draw rules, then publish it for trainers to assign." }}
      />
      {page?.has_more || cursors.length > 1 ? (
        <Pagination
          label="Tests pages"
          hasMore={!!page?.has_more}
          hasPrevious={cursors.length > 1}
          loading={tests.loading}
          onNext={() => setCursors((c) => nextCursorStack(c, page?.next_cursor ?? null))}
          onPrevious={() => setCursors((c) => previousCursorStack(c))}
        />
      ) : null}
      {open ? <NewTestDialog open onClose={() => setOpen(false)} onCreated={(t) => router.push(editHref(t.id))} /> : null}
    </div>
  );
}

/* ------------------------------------------------------------------ builder model */

export interface RuleDraft {
  rule_id?: string;
  rule_type: "fixed" | "random";
  question_id?: string | null;
  question_version_id?: string | null;
  /** Fixed coding item by problem (RuleIn.coding_problem_id); the api resolves it to the
   * published bank coding question and stores that as `question_id`. */
  coding_problem_id?: string | null;
  /** Random rules: RuleIn.question_types; `["coding"]` draws coding questions (coding section). */
  question_types?: string[] | null;
  /** Display text for fixed rules picked in this session. */
  label?: string;
  topic_id: string;
  difficulty_min: number;
  difficulty_max: number;
  draw_count: number;
  marks_each: number;
  negative_marks_each: number;
}

export interface SectionDraft {
  section_id?: string;
  title: string;
  duration_minutes: number | null;
  rules: RuleDraft[];
}

export interface SettingsDraft {
  title: string;
  duration_minutes: string;
  grace_seconds: string;
  navigation_mode: string;
  attempts_allowed: string;
  grading_method: string;
  shuffle_questions: boolean;
  shuffle_options: boolean;
  pass_percentage: string;
  available_from: string;
  available_until: string;
  release_at: string;
  during: Phase;
  after_submit: Phase;
  after_close: Phase;
  /** `integrity_settings`: legacy booleans plus the exam protocol (schemas.IntegritySettings). */
  integrity: Record<string, unknown>;
}

const PHASE_KEYS: { key: keyof Phase; label: string }[] = [
  { key: "score", label: "Score" },
  { key: "correctness", label: "Right / wrong per question" },
  { key: "answer_key", label: "Answer key" },
  { key: "explanation", label: "Explanations" },
  { key: "section_analytics", label: "Section analytics" },
  { key: "rank", label: "Rank" },
];

/** Integrity keys the attempt engine reads (assessments/attempts.py, studio.py create defaults). */
const INTEGRITY_KEYS: { key: string; label: string; description: string }[] = [
  { key: "fullscreen", label: "Ask for full screen", description: "Leaving full screen is logged as an advisory signal." },
  { key: "log_focus", label: "Log tab switches", description: "Advisory only; never auto-penalised." },
  { key: "log_paste", label: "Log paste events", description: "Advisory only; never auto-penalised." },
  { key: "consent_mandatory", label: "Require integrity consent", description: "Students must accept the integrity notice before starting." },
  { key: "single_device_binding", label: "Bind the attempt to one device", description: "Moving to another device needs a trainer-approved rebind." },
];

const PHASE_OFF: Phase = { score: false, correctness: false, answer_key: false, explanation: false, section_analytics: false, rank: false };

const asPhase = (v: unknown, fallback: Phase): Phase => {
  const o = (v && typeof v === "object" ? v : {}) as Partial<Record<keyof Phase, unknown>>;
  const out = { ...fallback };
  for (const { key } of PHASE_KEYS) if (typeof o[key] === "boolean") out[key] = o[key] as boolean;
  return out;
};

/** RFC 3339 → `<input type="datetime-local">` value in browser local time. */
export function isoToLocalInput(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

function toSettings(t: TestDefinition): SettingsDraft {
  const rp = (t.review_policy ?? {}) as Record<string, unknown>;
  return {
    title: t.title,
    duration_minutes: t.duration_seconds ? String(Math.round(t.duration_seconds / 60)) : "",
    grace_seconds: t.grace_seconds != null ? String(t.grace_seconds) : "",
    navigation_mode: t.navigation_mode,
    attempts_allowed: t.attempts_allowed ? String(t.attempts_allowed) : "",
    grading_method: t.grading_method || "highest",
    shuffle_questions: t.shuffle_questions,
    shuffle_options: t.shuffle_options ?? true,
    pass_percentage: t.pass_percentage ?? "",
    available_from: isoToLocalInput(t.available_from),
    available_until: isoToLocalInput(t.available_until),
    release_at: isoToLocalInput(typeof rp.release_at === "string" ? rp.release_at : null),
    during: asPhase(rp.during, PHASE_OFF),
    after_submit: asPhase(rp.after_submit, { ...PHASE_OFF, score: true, section_analytics: true }),
    after_close: asPhase(rp.after_close, { score: true, correctness: true, answer_key: true, explanation: true, section_analytics: true, rank: true }),
    integrity: { ...((t.integrity_settings ?? {}) as Record<string, unknown>) },
  };
}

function toDraft(sec: TestSectionOut): SectionDraft {
  return {
    section_id: sec.section_id,
    title: sec.title,
    duration_minutes: sec.duration_seconds ? Math.round(sec.duration_seconds / 60) : null,
    rules: sec.rules.map((r) => ({
      rule_id: r.rule_id,
      rule_type: r.rule_type,
      question_id: r.question_id,
      question_version_id: r.question_version_id,
      question_types: r.question_types,
      topic_id: r.topic_id ?? "",
      difficulty_min: r.difficulty_min ?? 1,
      difficulty_max: r.difficulty_max ?? 5,
      draw_count: r.draw_count,
      marks_each: r.marks_each !== null ? Number(r.marks_each) : 1,
      negative_marks_each: r.negative_marks_each !== null ? Number(r.negative_marks_each) : 0,
    })),
  };
}

export function toSectionsBody(sections: SectionDraft[]): Body<"studio/tests/{test_id}/sections", "put"> {
  return {
    sections: sections.map((s) => ({
      title: s.title.trim(),
      duration_seconds: s.duration_minutes ? s.duration_minutes * 60 : null,
      rules: s.rules.map((r) =>
        r.rule_type === "fixed"
          ? r.coding_problem_id && !r.question_id
            ? { rule_type: "fixed" as const, coding_problem_id: r.coding_problem_id, draw_count: 1, marks_each: String(r.marks_each), negative_marks_each: String(r.negative_marks_each) }
            : { rule_type: "fixed" as const, question_id: r.question_id ?? null, question_version_id: r.question_version_id ?? null, draw_count: 1, marks_each: String(r.marks_each), negative_marks_each: String(r.negative_marks_each) }
          : {
              rule_type: "random" as const,
              topic_id: r.topic_id.trim() || null,
              ...(r.question_types?.length ? { question_types: r.question_types } : {}),
              difficulty_min: r.difficulty_min,
              difficulty_max: r.difficulty_max,
              draw_count: r.draw_count,
              marks_each: String(r.marks_each),
              negative_marks_each: String(r.negative_marks_each),
            },
      ),
    })),
  } as Body<"studio/tests/{test_id}/sections", "put">;
}

export function toSettingsBody(s: SettingsDraft): Body<"studio/tests/{test_id}", "patch"> {
  return {
    title: s.title.trim(),
    duration_seconds: s.duration_minutes ? Number(s.duration_minutes) * 60 : null,
    grace_seconds: s.grace_seconds !== "" ? Number(s.grace_seconds) : null,
    navigation_mode: s.navigation_mode as "free" | "sequential" | "section_locked",
    attempts_allowed: s.attempts_allowed ? Number(s.attempts_allowed) : null,
    grading_method: s.grading_method as "highest" | "latest" | "first" | "average",
    shuffle_questions: s.shuffle_questions,
    shuffle_options: s.shuffle_options,
    pass_percentage: s.pass_percentage ? s.pass_percentage : null,
    available_from: localInputToIso(s.available_from),
    available_until: localInputToIso(s.available_until),
    review_policy: { during: s.during, after_submit: s.after_submit, after_close: s.after_close, release_at: localInputToIso(s.release_at) },
    // The draft is loose for the editor; the server fills omitted IntegritySettings defaults.
    integrity_settings: s.integrity as Schema<"IntegritySettings">,
  };
}

const ruleKey = (si: number, ri: number) => `sections.${si}.rules.${ri}`;

/**
 * Client-side checks mirroring assessments/schemas.py (TestSettings, SectionsPut, RuleIn), so a
 * draft never reaches the api in a shape that 422s. Keys use the api's `errors[].field` paths.
 */
export function validateBuilder(s: SettingsDraft, sections: SectionDraft[]): Record<string, string> {
  const e: Record<string, string> = {};
  if (!s.title.trim()) e.title = "Enter a title.";
  if (s.duration_minutes !== "") {
    const m = Number(s.duration_minutes);
    if (!Number.isInteger(m) || m < 1 || m > 360) e.duration_seconds = "Between 1 and 360 minutes.";
  }
  if (s.grace_seconds !== "") {
    const g = Number(s.grace_seconds);
    if (!Number.isInteger(g) || g < 0 || g > 300) e.grace_seconds = "Between 0 and 300 seconds.";
  }
  if (s.attempts_allowed !== "") {
    const a = Number(s.attempts_allowed);
    if (!Number.isInteger(a) || a < 1 || a > 100) e.attempts_allowed = "Between 1 and 100.";
  }
  if (s.pass_percentage !== "") {
    const p = Number(s.pass_percentage);
    if (!Number.isFinite(p) || p < 0 || p > 100) e.pass_percentage = "Between 0 and 100.";
  }
  const from = localInputToIso(s.available_from);
  const until = localInputToIso(s.available_until);
  if (from && until && from >= until) e.available_until = "The window must close after it opens.";
  Object.assign(e, validateProtocol(s.integrity));
  if (!sections.length) e.sections = "Add at least one section.";
  sections.forEach((sec, si) => {
    if (!sec.title.trim()) e[`sections.${si}.title`] = "Enter a section title.";
    if (sec.duration_minutes !== null && (!Number.isInteger(sec.duration_minutes) || sec.duration_minutes < 1 || sec.duration_minutes > 360))
      e[`sections.${si}.duration_seconds`] = "Between 1 and 360 minutes.";
    if (!sec.rules.length) e[`sections.${si}.rules`] = "Add a draw rule or pick questions for this section.";
    sec.rules.forEach((r, ri) => {
      const k = ruleKey(si, ri);
      if (r.rule_type === "fixed") {
        if (!r.question_id && !r.coding_problem_id) e[`${k}.question_id`] = "Pick a question.";
      } else {
        if (!r.topic_id.trim()) e[`${k}.topic_id`] = "Enter the topic to draw from.";
        if (!(r.difficulty_min >= 1 && r.difficulty_max <= 5 && r.difficulty_min <= r.difficulty_max)) e[`${k}.difficulty_min`] = "Use 1–5, lowest first.";
        if (!Number.isInteger(r.draw_count) || r.draw_count < 1 || r.draw_count > 200) e[`${k}.draw_count`] = "Between 1 and 200.";
      }
      if (!(r.marks_each > 0 && r.marks_each <= 100)) e[`${k}.marks_each`] = "More than 0, at most 100.";
      if (!(r.negative_marks_each >= 0 && r.negative_marks_each <= 100)) e[`${k}.negative_marks_each`] = "Between 0 and 100.";
    });
  });
  return e;
}

/** 422 `…rules.N.coding_problem_id` (no published coding question wraps the problem) in plain words. */
export function codingRuleErrors(fe: Record<string, string>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, m] of Object.entries(fe))
    out[k] = k.endsWith(".coding_problem_id")
      ? "No published coding question uses this problem yet. Publish a coding question for it in the question bank, then try again."
      : m;
  return out;
}

/* ------------------------------------------------------------------ coding problem picker */

/**
 * Published coding problems for test authors: COD-24 `GET /studio/coding/problems/published`
 * (`test.create` at platform, org or batch scope, so batch trainers can pick too; server `q` search).
 */
function CodingProblemPicker({ onClose, onPick, taken }: { onClose: () => void; onPick: (p: PublishedCodingProblem) => void; taken: Set<string> }) {
  const [term, setTerm] = useState("");
  const q = term.trim();
  // verified: app/modules/coding/router.py studio_published_problems (q 1..100, cursor, limit) → {data, page}
  const list = useApi<{ data: PublishedCodingProblem[] }>("studio/coding/problems/published", { q: q || undefined, limit: 100 });
  return (
    <Dialog open onClose={onClose} title="Add coding problems" footer={<Button onClick={onClose}>Done</Button>}>
      <div className="space-y-3">
        <FormField label="Search coding problems">{(p) => <Input {...p} type="search" value={term} onChange={(e) => setTerm(e.target.value)} />}</FormField>
        <Table
          caption="Published coding problems"
          columns={[
            { key: "t", header: "Problem", cell: (p: PublishedCodingProblem) => p.title },
            { key: "d", header: "Difficulty", cell: (p) => p.difficulty },
            {
              key: "a",
              header: <span className="sr-only">Actions</span>,
              align: "right",
              cell: (p) => (
                <Button size="sm" variant="secondary" disabled={taken.has(p.problem_id)} onClick={() => onPick(p)} aria-label={`Add ${p.title}`}>
                  {taken.has(p.problem_id) ? "Added" : "Add"}
                </Button>
              ),
            },
          ]}
          rows={list.data?.data}
          rowKey={(p) => p.problem_id}
          loading={list.loading}
          error={list.error}
          onRetry={() => void list.reload()}
          empty={{ title: "No published coding problems match", description: "Only published coding problems can be added to a test." }}
        />
      </div>
    </Dialog>
  );
}

/* ------------------------------------------------------------------ question picker */

/** PLC-04 published questions; the api has no text search, so stems are filtered in the browser. */
function QuestionPicker({ onClose, onPick, taken }: { onClose: () => void; onPick: (q: QuestionSummary) => void; taken: Set<string> }) {
  const [topic, setTopic] = useState("");
  const [term, setTerm] = useState("");
  // verified: app/modules/placement/router.py list_questions (version_status, topic_id, limit ≤ 200)
  const list = useApi<{ items: QuestionSummary[] }>("studio/questions", { version_status: "published", topic_id: topic.trim() || undefined, limit: 200 });
  const rows = useMemo(() => {
    const t = term.trim().toLowerCase();
    return (list.data?.items ?? []).filter((q) => !t || stripHtml(q.latest_version?.stem_html ?? "").toLowerCase().includes(t));
  }, [list.data, term]);
  return (
    <Dialog open onClose={onClose} title="Add questions" footer={<Button onClick={onClose}>Done</Button>}>
      <div className="space-y-3">
        <div className="grid gap-3 md:grid-cols-2">
          <FormField label="Search question text">{(p) => <Input {...p} type="search" value={term} onChange={(e) => setTerm(e.target.value)} />}</FormField>
          <FormField label="Topic id" hint="Optional filter">
            {(p) => <Input {...p} className="font-mono" value={topic} onChange={(e) => setTopic(e.target.value)} />}
          </FormField>
        </div>
        <Table
          caption="Published questions"
          columns={[
            { key: "q", header: "Question", cell: (q: QuestionSummary) => <span className="line-clamp-2">{stripHtml(q.latest_version?.stem_html ?? "") || "Untitled question"}</span> },
            { key: "d", header: "Difficulty", cell: (q) => q.latest_version?.difficulty ?? "—" },
            {
              key: "a",
              header: <span className="sr-only">Actions</span>,
              align: "right",
              cell: (q) => (
                <Button size="sm" variant="secondary" disabled={taken.has(q.question_id)} onClick={() => onPick(q)} aria-label={`Add ${stripHtml(q.latest_version?.stem_html ?? "question").slice(0, 60)}`}>
                  {taken.has(q.question_id) ? "Added" : "Add"}
                </Button>
              ),
            },
          ]}
          rows={rows}
          rowKey={(q) => q.question_id}
          loading={list.loading}
          error={list.error}
          onRetry={() => void list.reload()}
          empty={{ title: "No published questions match", description: "Only published questions can be added to a test." }}
        />
      </div>
    </Dialog>
  );
}

function stripHtml(html: string): string {
  return html.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
}

/* ------------------------------------------------------------------ builder */

/**
 * TRN-006 / CMS-011 test builder: settings incl. window, grace, review policy and integrity
 * (ASM-06), sections + fixed/random rules (ASM-07), feasibility check (ASM-08), publish (ASM-09).
 * Settings lock after the first attempt (409 test_settings_locked). Coding sections: fixed
 * coding items by `coding_problem_id`, and random rules restricted to `question_types: ["coding"]`.
 */
const BUILDER_SECTIONS = [
  { id: "test-settings", label: "Settings" },
  { id: "test-review-policy", label: "Review policy" },
  { id: "test-integrity", label: "Integrity" },
  { id: "test-protocol", label: "Exam protocol" },
  { id: "test-sections", label: "Sections" },
];

/** "mock" → "Mock test": the label authors see in the studio, for every list that shows a kind. */
export function testKindLabel(kind: string | null | undefined): string {
  if (!kind) return "—";
  const known = KINDS.find((k) => k.value === kind)?.label;
  if (known) return known;
  const words = kind.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/**
 * CMS-011 / TRN-006 test builder. `crumbs` is the parent trail of the page (studio "Template
 * mocks" or trainer "Tests"); the test's title becomes the h1.
 */
export function TestBuilder({ testId, crumbs = [] }: { testId: string; crumbs?: Crumb[] }) {
  const toast = useToast();
  const fail = useFailToast();
  const test = useApi<TestDefinition>(`studio/tests/${seg(testId)}`);
  const [s, setS] = useState<SettingsDraft | null>(null);
  const [sections, setSections] = useState<SectionDraft[]>([]);
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [lockedByServer, setLockedByServer] = useState(false);
  const [picking, setPicking] = useState<number | null>(null);
  const [pickingCoding, setPickingCoding] = useState<number | null>(null);
  const [pickingBank, setPickingBank] = useState<number | null>(null);
  const [confirmArchive, setConfirmArchive] = useState(false);

  const t = test.data;
  const archived = t?.status === "archived";
  useEffect(() => {
    if (!t) return;
    setS(toSettings(t));
    setSections(t.sections.length ? t.sections.map(toDraft) : [{ title: "Section A", duration_minutes: null, rules: [] }]);
  }, [t]);

  const locked = lockedByServer || !!t?.settings_locked_at;
  const set = <K extends keyof SettingsDraft>(k: K, v: SettingsDraft[K]) => setS((x) => (x ? { ...x, [k]: v } : x));

  const call = async <R,>(key: string, fn: () => Promise<R>, ok?: string): Promise<R | undefined> => {
    setBusy(key);
    setErrors({});
    try {
      const r = await fn();
      if (ok) toast.show({ tone: "success", title: ok });
      return r;
    } catch (err) {
      if (err instanceof ApiError && err.code === "test_settings_locked") {
        setLockedByServer(true);
        toast.show({ tone: "warning", title: "Settings are locked", description: "Students have already started this test, so its settings can't change.", requestId: err.requestId });
      } else {
        const fe = codingRuleErrors(fieldErrorsOf(err));
        if (Object.keys(fe).length) {
          setErrors(fe);
          toast.show({ tone: "danger", title: "Fix the highlighted fields", requestId: err instanceof ApiError ? err.requestId : null });
        } else fail(err);
      }
      return undefined;
    } finally {
      setBusy(null);
    }
  };

  const saveAll = async () => {
    if (!s) return;
    const errs = validateBuilder(s, sections);
    setErrors(errs);
    if (Object.keys(errs).length) return;
    const ok1 = await call("save", () => api.patch(`studio/tests/${seg(testId)}`, toSettingsBody(s)));
    if (ok1 === undefined) return;
    const ok2 = await call("save", () => api.put(`studio/tests/${seg(testId)}/sections`, toSectionsBody(sections)), "Test saved");
    if (ok2 !== undefined) {
      setValidation(null);
      await test.reload();
    }
  };

  const validate = async () => {
    const res = await call("validate", () => api.post<ValidationResult>(`studio/tests/${seg(testId)}/validate`, {}));
    if (res && res.kind === "ok") setValidation(res.data);
  };

  const publish = async () => {
    const r = await call("publish", () => api.post(`studio/tests/${seg(testId)}/publish`, {}), "Test published");
    if (r !== undefined) await test.reload();
  };

  const updRule = (si: number, ri: number, patch: Partial<RuleDraft>) =>
    setSections((ss) => ss.map((sec, i) => (i !== si ? sec : { ...sec, rules: sec.rules.map((r, j) => (j === ri ? { ...r, ...patch } : r)) })));
  const addRule = (si: number, r: RuleDraft) => setSections((ss) => ss.map((x, i) => (i === si ? { ...x, rules: [...x.rules, r] } : x)));
  const removeRule = (si: number, ri: number) => setSections((ss) => ss.map((x, i) => (i === si ? { ...x, rules: x.rules.filter((_, j) => j !== ri) } : x)));

  const total = sections.reduce((n, sec) => n + sec.rules.reduce((m, r) => m + (Number(r.draw_count) || 0), 0), 0);
  const shortfall = (si: number, ri: number) => {
    const sid = sections[si]?.section_id;
    const rid = sections[si]?.rules[ri]?.rule_id;
    return validation?.rules.find((r) => r.section_id === sid && r.rule_id === rid && !r.ok);
  };
  /** Field error for a rule input, falling back to rule-level errors (pydantic model validators). */
  const ruleErr = (si: number, ri: number, field: string) => errors[`${ruleKey(si, ri)}.${field}`];
  const ruleLevelErr = (si: number, ri: number) => errors[ruleKey(si, ri)];
  const known = (k: string) =>
    ["title", "duration_seconds", "grace_seconds", "attempts_allowed", "pass_percentage", "available_from", "available_until", "sections"].includes(k) ||
    /^sections\.\d+\.(title|duration_seconds|rules)$/.test(k) ||
    /^sections\.\d+\.rules\.\d+(\.(question_id|coding_problem_id|topic_id|difficulty_min|draw_count|marks_each|negative_marks_each))?$/.test(k);
  const otherErrors = Object.entries(errors).filter(([k]) => !known(k));

  return (
    <>
    <EntityHeader
      title={t?.title}
      fallback="Test builder"
      crumbs={crumbs}
      meta={t ? <StatusBadge status={t.status} /> : null}
      description={t ? testKindLabel(t.test_kind) : undefined}
    />
    <Boundary state={test}>
      {(def) =>
        !s ? null : (
          <div className="space-y-6">
            <div className="flex flex-wrap items-center gap-3">
              {def.version ? <span className="text-sm text-fg-muted">Version {def.version}</span> : null}
              {def.batch_id ? <BatchOwned batchId={def.batch_id} /> : null}
              {locked ? (
                <p role="status" className="text-sm text-warning-fg">
                  Settings are read-only because students have started this test.
                </p>
              ) : null}
            </div>
            <SectionNav sections={BUILDER_SECTIONS} label="Test builder sections" />
            <Card id="test-settings" className="scroll-mt-20" title="Settings">
              <fieldset disabled={locked} className="grid gap-4 md:grid-cols-3">
                <legend className="sr-only">Test settings</legend>
                <div className="md:col-span-3">
                  <FormField label="Title" required error={errors.title}>
                    {(p) => <Input {...p} value={s.title} onChange={(e) => set("title", e.target.value)} />}
                  </FormField>
                </div>
                <FormField label="Duration (minutes)" error={errors.duration_seconds}>
                  {(p) => <Input {...p} type="number" min={1} inputMode="numeric" value={s.duration_minutes} onChange={(e) => set("duration_minutes", e.target.value)} />}
                </FormField>
                <FormField label="Grace period (seconds)" hint="0–300; time allowed for auto-submit after the clock ends" error={errors.grace_seconds}>
                  {(p) => <Input {...p} type="number" min={0} max={300} inputMode="numeric" value={s.grace_seconds} onChange={(e) => set("grace_seconds", e.target.value)} />}
                </FormField>
                <FormField label="Navigation">
                  {(p) => (
                    <Select
                      {...p}
                      value={s.navigation_mode}
                      onChange={(e) => set("navigation_mode", e.target.value)}
                      options={[
                        { value: "free", label: "Free — move between all questions" },
                        { value: "sequential", label: "Sequential — no going back" },
                        { value: "section_locked", label: "Section-locked" },
                      ]}
                    />
                  )}
                </FormField>
                <FormField label="Attempts" error={errors.attempts_allowed}>
                  {(p) => <Input {...p} type="number" min={1} inputMode="numeric" value={s.attempts_allowed} onChange={(e) => set("attempts_allowed", e.target.value)} />}
                </FormField>
                <FormField label="Score to keep">
                  {(p) => (
                    <Select
                      {...p}
                      value={s.grading_method}
                      onChange={(e) => set("grading_method", e.target.value)}
                      options={[
                        { value: "highest", label: "Highest attempt" },
                        { value: "latest", label: "Latest attempt" },
                        { value: "first", label: "First attempt" },
                        { value: "average", label: "Average of attempts" },
                      ]}
                    />
                  )}
                </FormField>
                <FormField label="Pass mark (%)" error={errors.pass_percentage}>
                  {(p) => <Input {...p} type="number" min={0} max={100} inputMode="numeric" value={s.pass_percentage} onChange={(e) => set("pass_percentage", e.target.value)} />}
                </FormField>
                <FormField label="Opens" hint="Optional; assignments set their own window" error={errors.available_from}>
                  {(p) => <Input {...p} type="datetime-local" value={s.available_from} onChange={(e) => set("available_from", e.target.value)} />}
                </FormField>
                <FormField label="Closes" error={errors.available_until}>
                  {(p) => <Input {...p} type="datetime-local" value={s.available_until} onChange={(e) => set("available_until", e.target.value)} />}
                </FormField>
                <div className="flex flex-col justify-end">
                  <Checkbox className="min-h-touch items-center" label="Shuffle question order" checked={s.shuffle_questions} onChange={(e) => set("shuffle_questions", e.target.checked)} />
                  <Checkbox className="min-h-touch items-center" label="Shuffle answer options" checked={s.shuffle_options} onChange={(e) => set("shuffle_options", e.target.checked)} />
                </div>
              </fieldset>
            </Card>
            <Card id="test-review-policy" className="scroll-mt-20" title="Review policy">
              <fieldset disabled={locked} className="space-y-4">
                <legend className="sr-only">What students see and when</legend>
                <div className="grid gap-4 md:grid-cols-3">
                  {(
                    [
                      ["during", "During the attempt"],
                      ["after_submit", "After they submit"],
                      ["after_close", "After the window closes"],
                    ] as const
                  ).map(([phase, label]) => (
                    <fieldset key={phase}>
                      <legend className="mb-1 text-sm font-semibold text-fg">{label}</legend>
                      {PHASE_KEYS.map(({ key, label: l }) => (
                        <Checkbox
                          key={key}
                          className="min-h-touch items-center"
                          label={l}
                          aria-label={`${label}: ${l}`}
                          checked={s[phase][key]}
                          onChange={(e) => set(phase, { ...s[phase], [key]: e.target.checked })}
                        />
                      ))}
                    </fieldset>
                  ))}
                </div>
                <div className="max-w-xs">
                  <FormField label="Release results at" hint="Optional; leave empty to follow the assignment's release mode" error={errors["review_policy.release_at"]}>
                    {(p) => <Input {...p} type="datetime-local" value={s.release_at} onChange={(e) => set("release_at", e.target.value)} />}
                  </FormField>
                </div>
              </fieldset>
            </Card>
            <Card id="test-integrity" className="scroll-mt-20" title="Integrity">
              <fieldset disabled={locked} className="grid gap-x-3 gap-y-4 md:grid-cols-2">
                <legend className="sr-only">Integrity settings</legend>
                {INTEGRITY_KEYS.map(({ key, label, description }) => (
                  <Checkbox
                    key={key}
                    label={label}
                    description={description}
                    checked={!!s.integrity[key]}
                    onChange={(e) => set("integrity", { ...s.integrity, [key]: e.target.checked })}
                  />
                ))}
              </fieldset>
            </Card>
            <div id="test-protocol" className="scroll-mt-20">
              <ExamProtocolSettings value={s.integrity} onChange={(v) => set("integrity", v)} disabled={locked} errors={errors} />
            </div>
            <Card id="test-sections" className="scroll-mt-20" title={`Sections (${total} questions)`}>
              <fieldset disabled={locked} className="space-y-6">
                <legend className="sr-only">Sections and draw rules</legend>
                {errors.sections ? <p className="text-sm text-danger-fg">{errors.sections}</p> : null}
                {sections.map((sec, si) => (
                  <div key={si} className="space-y-3 rounded-lg border border-line p-3">
                    <div className="grid gap-3 md:grid-cols-3">
                      <FormField label={`Section ${si + 1} title`} error={errors[`sections.${si}.title`]}>
                        {(p) => <Input {...p} value={sec.title} onChange={(e) => setSections((ss) => ss.map((x, i) => (i === si ? { ...x, title: e.target.value } : x)))} />}
                      </FormField>
                      <FormField label="Section time (minutes)" hint="Optional" error={errors[`sections.${si}.duration_seconds`]}>
                        {(p) => (
                          <Input
                            {...p}
                            type="number"
                            min={1}
                            inputMode="numeric"
                            value={sec.duration_minutes ?? ""}
                            onChange={(e) => setSections((ss) => ss.map((x, i) => (i === si ? { ...x, duration_minutes: e.target.value ? Number(e.target.value) : null } : x)))}
                          />
                        )}
                      </FormField>
                      <div className="flex items-end">
                        {sections.length > 1 ? (
                          <Button size="sm" variant="ghost" aria-label={`Remove section ${si + 1}${sec.title ? ` (${sec.title})` : ""}`} onClick={() => setSections((ss) => ss.filter((_, i) => i !== si))}>
                            Remove section
                          </Button>
                        ) : null}
                      </div>
                    </div>
                    {errors[`sections.${si}.rules`] ? <p className="text-sm text-danger-fg">{errors[`sections.${si}.rules`]}</p> : null}
                    {sec.rules.map((r, ri) => {
                      const short = shortfall(si, ri);
                      const lvl = ruleLevelErr(si, ri);
                      if (r.rule_type === "fixed")
                        return (
                          <div key={ri} className="grid gap-3 border-t border-line-subtle pt-3 md:grid-cols-6">
                            <div className="md:col-span-3 text-sm text-fg-secondary">
                              <p>
                                {r.coding_problem_id && !r.question_id ? "Coding problem" : "Fixed question"}:{" "}
                                {r.label ? r.label : <span className="font-mono">{r.question_id ?? r.question_version_id ?? r.coding_problem_id}</span>}
                                {short ? <span className="ml-2 text-danger-fg">Not published</span> : null}
                              </p>
                              {ruleErr(si, ri, "question_id") || ruleErr(si, ri, "coding_problem_id") || lvl ? (
                                <p className="text-danger-fg">{ruleErr(si, ri, "question_id") ?? ruleErr(si, ri, "coding_problem_id") ?? lvl}</p>
                              ) : null}
                            </div>
                            <FormField label="Marks" error={ruleErr(si, ri, "marks_each")}>
                              {(p) => <Input {...p} type="number" min={0} step="0.25" value={r.marks_each} onChange={(e) => updRule(si, ri, { marks_each: Number(e.target.value) })} />}
                            </FormField>
                            <FormField label="Negative" error={ruleErr(si, ri, "negative_marks_each")}>
                              {(p) => <Input {...p} type="number" min={0} step="0.25" value={r.negative_marks_each} onChange={(e) => updRule(si, ri, { negative_marks_each: Number(e.target.value) })} />}
                            </FormField>
                            <div className="flex items-end">
                              <Button size="sm" variant="ghost" aria-label={`Remove rule ${ri + 1} from section ${si + 1}`} onClick={() => removeRule(si, ri)}>
                                Remove
                              </Button>
                            </div>
                          </div>
                        );
                      return (
                        <div key={ri} className="space-y-1 border-t border-line-subtle pt-3">
                          <div className="grid gap-3 md:grid-cols-7">
                            <FormField label="Topic id" required error={ruleErr(si, ri, "topic_id")}>
                              {(p) => <Input {...p} className="font-mono" value={r.topic_id} onChange={(e) => updRule(si, ri, { topic_id: e.target.value })} />}
                            </FormField>
                            <FormField label="Difficulty from" error={ruleErr(si, ri, "difficulty_min")}>
                              {(p) => <Input {...p} type="number" min={1} max={5} value={r.difficulty_min} onChange={(e) => updRule(si, ri, { difficulty_min: Number(e.target.value) })} />}
                            </FormField>
                            <FormField label="to">{(p) => <Input {...p} type="number" min={1} max={5} value={r.difficulty_max} onChange={(e) => updRule(si, ri, { difficulty_max: Number(e.target.value) })} />}</FormField>
                            <FormField label="Questions" error={ruleErr(si, ri, "draw_count") ?? (short ? `Only ${short.pool_size} published questions match` : undefined)}>
                              {(p) => <Input {...p} type="number" min={1} value={r.draw_count} onChange={(e) => updRule(si, ri, { draw_count: Number(e.target.value) })} />}
                            </FormField>
                            <FormField label="Marks each" error={ruleErr(si, ri, "marks_each")}>
                              {(p) => <Input {...p} type="number" min={0} step="0.25" value={r.marks_each} onChange={(e) => updRule(si, ri, { marks_each: Number(e.target.value) })} />}
                            </FormField>
                            <FormField label="Negative" error={ruleErr(si, ri, "negative_marks_each")}>
                              {(p) => <Input {...p} type="number" min={0} step="0.25" value={r.negative_marks_each} onChange={(e) => updRule(si, ri, { negative_marks_each: Number(e.target.value) })} />}
                            </FormField>
                            <div className="flex items-end">
                              <Button size="sm" variant="ghost" aria-label={`Remove rule ${ri + 1} from section ${si + 1}`} onClick={() => removeRule(si, ri)}>
                                Remove
                              </Button>
                            </div>
                          </div>
                          <Checkbox
                            className="min-h-touch items-center"
                            label="Coding questions only (coding section)"
                            checked={!!r.question_types?.includes("coding")}
                            onChange={(e) => updRule(si, ri, { question_types: e.target.checked ? ["coding"] : null })}
                          />
                          {lvl ? <p className="text-sm text-danger-fg">{lvl}</p> : null}
                        </div>
                      );
                    })}
                    <div className="flex flex-wrap gap-2">
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => addRule(si, { rule_type: "random", topic_id: "", difficulty_min: 1, difficulty_max: 5, draw_count: 10, marks_each: 1, negative_marks_each: 0 })}
                      >
                        Add draw rule
                      </Button>
                      <Button size="sm" variant="secondary" onClick={() => setPicking(si)}>
                        Pick questions
                      </Button>
                      <Button size="sm" variant="secondary" onClick={() => setPickingBank(si)}>
                        Import from a bank
                      </Button>
                      <Button size="sm" variant="secondary" onClick={() => setPickingCoding(si)}>
                        Add coding problem
                      </Button>
                    </div>
                  </div>
                ))}
                <Button variant="secondary" onClick={() => setSections((ss) => [...ss, { title: `Section ${String.fromCharCode(65 + ss.length)}`, duration_minutes: null, rules: [] }])}>
                  Add section
                </Button>
              </fieldset>
            </Card>
            {otherErrors.length ? (
              <div role="alert" className="rounded-lg border border-danger-border p-3 text-sm text-danger-fg">
                <p className="font-semibold">The api rejected some values:</p>
                <ul className="list-disc pl-5">
                  {otherErrors.map(([k, m]) => (
                    <li key={k}>
                      <span className="font-mono">{k}</span>: {m}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            <StickyActionBar
              status={
                validation ? (
                  <span className={validation.feasible ? "text-success-fg" : "text-danger-fg"}>
                    {validation.feasible
                      ? "Every draw rule has enough published questions."
                      : !validation.has_sections
                        ? "Save at least one section before checking."
                        : "Some draw rules don't have enough published questions. Adjust the highlighted rules."}
                  </span>
                ) : (
                  <span className="text-fg-muted">
                    {archived
                      ? "Archived: learners can't start it; earlier attempts and results stay available."
                      : `${total} question${total === 1 ? "" : "s"} · check the question supply before publishing.`}
                  </span>
                )
              }
            >
              {!locked ? (
                <Button onClick={() => void saveAll()} loading={busy === "save"}>
                  Save
                </Button>
              ) : null}
              <Button variant="secondary" onClick={() => void validate()} loading={busy === "validate"}>
                Check question supply
              </Button>
              <Button variant="secondary" onClick={() => void publish()} loading={busy === "publish"} disabled={archived || !validation?.feasible}>
                Publish
              </Button>
              {t && !archived ? (
                <Button variant="danger-secondary" onClick={() => setConfirmArchive(true)}>
                  Archive
                </Button>
              ) : null}
            </StickyActionBar>
            <ConfirmDialog
              open={confirmArchive}
              onClose={() => setConfirmArchive(false)}
              title="Archive this test?"
              description="Learners can no longer start it and it leaves their test lists. Open assignment windows close now. Attempts already made and their results stay available. This can't be undone."
              confirmLabel="Archive test"
              danger
              onConfirm={async () => {
                await api.post(`studio/tests/${seg(testId)}/archive`, {}, { idempotencyKey: true });
                toast.show({ tone: "success", title: "Test archived" });
                await test.reload();
              }}
            />
            {picking !== null ? (
              <QuestionPicker
                onClose={() => setPicking(null)}
                taken={new Set(sections[picking]?.rules.filter((r) => r.rule_type === "fixed" && r.question_id).map((r) => r.question_id!) ?? [])}
                onPick={(q) =>
                  addRule(picking, {
                    rule_type: "fixed",
                    question_id: q.question_id,
                    question_version_id: null,
                    label: stripHtml(q.latest_version?.stem_html ?? "").slice(0, 120) || q.question_id,
                    topic_id: "",
                    difficulty_min: 1,
                    difficulty_max: 5,
                    draw_count: 1,
                    marks_each: 1,
                    negative_marks_each: 0,
                  })
                }
              />
            ) : null}
            {pickingBank !== null ? (
              <QuestionBankPicker
                open
                onClose={() => setPickingBank(null)}
                description="Picked questions are added to this section as fixed questions. Set marks and negative marks per question below."
                excludeQuestionIds={sections[pickingBank]?.rules.filter((r) => r.rule_type === "fixed" && r.question_id).map((r) => r.question_id!) ?? []}
                onPick={(picked) => {
                  const si = pickingBank;
                  for (const q of picked)
                    addRule(si, {
                      rule_type: "fixed",
                      question_id: q.question_id,
                      question_version_id: null,
                      label: stripHtml(q.stem_html).slice(0, 120) || q.question_id,
                      topic_id: "",
                      difficulty_min: 1,
                      difficulty_max: 5,
                      draw_count: 1,
                      marks_each: 1,
                      negative_marks_each: 0,
                    });
                  setPickingBank(null);
                }}
              />
            ) : null}
            {pickingCoding !== null ? (
              <CodingProblemPicker
                onClose={() => setPickingCoding(null)}
                taken={new Set(sections[pickingCoding]?.rules.filter((r) => r.rule_type === "fixed" && r.coding_problem_id).map((r) => r.coding_problem_id!) ?? [])}
                onPick={(p) =>
                  addRule(pickingCoding, {
                    rule_type: "fixed",
                    question_id: null,
                    question_version_id: null,
                    coding_problem_id: p.problem_id,
                    label: p.title,
                    topic_id: "",
                    difficulty_min: 1,
                    difficulty_max: 5,
                    draw_count: 1,
                    marks_each: 10,
                    negative_marks_each: 0,
                  })
                }
              />
            ) : null}
          </div>
        )
      }
    </Boundary>
    </>
  );
}
