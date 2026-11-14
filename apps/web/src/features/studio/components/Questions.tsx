"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Button, Card, Checkbox, Dialog, FormField, Input, Select, Table, useToast } from "@/components/ui";
import { api, type Page } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { Body } from "@/lib/api-types";
import { useApi, seg, type SendBody } from "@/features/trainer/shared/use-api";
import { Boundary, StatusBadge, TextArea, fieldErrorsOf, formatDate, useFailToast } from "@/features/trainer/shared/ui";
import type { CourseSummary, QuestionDetail, QuestionSummary, QuestionType, QuestionVersion } from "../lib/types";
import { courseStatus } from "./Courses";
import { TopicSelect, useTopics } from "./Pickers";

/** PLC-04 `status` filters the question (not the version): draft | active | retired. */
const STATUS_OPTIONS = [
  { value: "", label: "Any status" },
  { value: "draft", label: "Draft" },
  { value: "active", label: "Active" },
  { value: "retired", label: "Retired" },
];

const PAGE = 25;

/** Plain-text preview of sanitised question HTML. */
export function textOf(html: string | null | undefined): string {
  return (html ?? "")
    .replace(/<[^>]*>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/\s+/g, " ")
    .trim();
}

/** CMS-004 question bank search (PLC-04: `{items, limit, offset}`, offset paging; stem text `q` and tag filters). */
export function QuestionBank() {
  const [q, setQ] = useState("");
  const [text, setText] = useState("");
  const [tagInput, setTagInput] = useState("");
  const [tag, setTag] = useState("");
  const [status, setStatus] = useState("");
  const [difficulty, setDifficulty] = useState("");
  const [offset, setOffset] = useState(0);
  const list = useApi<{ items: QuestionSummary[]; limit: number; offset: number }>("studio/questions", {
    q: text || undefined,
    tag: tag || undefined,
    status: status || undefined,
    difficulty: difficulty || undefined,
    offset,
    limit: PAGE,
  });
  const items = list.data?.items;

  return (
    <div className="space-y-4">
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          setOffset(0);
          // PLC-04 `q` needs 2+ characters; a single character is ignored rather than sent.
          setText(q.trim().length >= 2 ? q.trim() : "");
          setTag(tagInput.trim());
        }}
      >
        <div className="min-w-56 flex-1">
          <FormField label="Search question text">{(p) => <Input {...p} type="search" value={q} maxLength={200} onChange={(e) => setQ(e.target.value)} />}</FormField>
        </div>
        <div className="w-44">
          <FormField label="Tag">{(p) => <Input {...p} value={tagInput} onChange={(e) => setTagInput(e.target.value)} />}</FormField>
        </div>
        <div className="w-44">
          <FormField label="Status">
            {(p) => (
              <Select
                {...p}
                value={status}
                onChange={(e) => {
                  setOffset(0);
                  setStatus(e.target.value);
                }}
                options={STATUS_OPTIONS}
              />
            )}
          </FormField>
        </div>
        <div className="w-36">
          <FormField label="Difficulty">
            {(p) => (
              <Select
                {...p}
                value={difficulty}
                onChange={(e) => {
                  setOffset(0);
                  setDifficulty(e.target.value);
                }}
                options={[{ value: "", label: "Any" }, ...[1, 2, 3, 4, 5].map((d) => ({ value: String(d), label: String(d) }))]}
              />
            )}
          </FormField>
        </div>
        <Button type="submit" variant="secondary">
          Search
        </Button>
      </form>
      <Table
        caption="Questions"
        columns={[
          {
            key: "s",
            header: "Question",
            cell: (x: QuestionSummary) => (
              <Link className="text-fg-link underline" href={`/studio/questions/${seg(x.question_id)}`}>
                {textOf(x.latest_version?.stem_html).slice(0, 140) || "Untitled"}
              </Link>
            ),
          },
          { key: "t", header: "Type", cell: (x) => questionTypeLabel(x.question_type) },
          { key: "d", header: "Difficulty", cell: (x) => x.latest_version?.difficulty ?? "—" },
          {
            key: "st",
            header: "Status",
            cell: (x) => (
              <span className="inline-flex flex-col gap-0.5">
                <StatusBadge status={x.status} />
                {x.status === "retired" && x.retired_reason ? <span className="text-xs text-fg-muted">Retired: {x.retired_reason}</span> : null}
              </span>
            ),
          },
          { key: "v", header: "Latest version", cell: (x) => (x.latest_version ? <StatusBadge status={x.latest_version.status} /> : "—") },
        ]}
        rows={items}
        rowKey={(x) => x.question_id}
        loading={list.loading}
        error={list.error}
        onRetry={() => void list.reload()}
        empty={{ title: "No questions match", description: "Try a different filter or create a question." }}
      />
      {offset > 0 || (items?.length ?? 0) === PAGE ? (
        <div className="flex gap-2">
          <Button variant="secondary" size="sm" disabled={offset === 0} onClick={() => setOffset(0)}>
            First page
          </Button>
          <Button variant="secondary" size="sm" disabled={(items?.length ?? 0) < PAGE} onClick={() => setOffset((o) => o + PAGE)}>
            Next page
          </Button>
        </div>
      ) : null}
    </div>
  );
}

const TYPES: { value: QuestionType; label: string }[] = [
  { value: "mcq_single", label: "Multiple choice — one answer" },
  { value: "mcq_multi", label: "Multiple choice — several answers" },
  { value: "numeric", label: "Numeric answer" },
];

/** Every question type the api can return, in words (list views show legacy/imported types too). */
const TYPE_LABELS: Record<string, string> = {
  mcq_single: "Multiple choice — one answer",
  mcq_multi: "Multiple choice — several answers",
  numeric: "Numeric answer",
  fill_blank: "Fill in the blank",
  coding: "Coding",
  essay: "Essay",
  short_text: "Short answer",
  file: "File upload",
  true_false: "True or false",
};

/** "fill_blank" → "Fill in the blank"; unknown types become sentence case, never a raw enum. */
export function questionTypeLabel(t: string | null | undefined): string {
  if (!t) return "—";
  const known = TYPE_LABELS[t];
  if (known) return known;
  const words = t.replace(/_/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

interface DraftOption {
  text: string;
  is_correct?: boolean;
}

interface Draft {
  type: QuestionType | string;
  stem: string;
  options: DraftOption[];
  explanation: string;
  difficulty: string;
  topic_id: string;
  tags: string;
  numeric_value?: string;
  numeric_tolerance?: string;
}

const EMPTY: Draft = {
  type: "mcq_single",
  stem: "",
  options: [
    { text: "", is_correct: true },
    { text: "", is_correct: false },
  ],
  explanation: "",
  difficulty: "3",
  topic_id: "",
  tags: "",
  numeric_value: "",
  numeric_tolerance: "0",
};

function toDraft(q: QuestionDetail, v: QuestionVersion): Draft {
  const key = (v.answer_key ?? {}) as { value?: unknown; tolerance?: unknown };
  return {
    type: q.question_type,
    stem: v.stem_html,
    options: v.options.map((o) => ({ text: o.html, is_correct: o.is_correct })),
    explanation: v.explanation_html ?? "",
    difficulty: String(v.difficulty),
    topic_id: q.primary_topic_id,
    tags: q.tags
      .map((t) => t.value)
      .filter(Boolean)
      .join(", "),
    numeric_value: key.value !== undefined ? String(key.value) : "",
    numeric_tolerance: key.tolerance !== undefined ? String(key.tolerance) : "0",
  };
}

/** Pure validation used before save / submit (explanation is mandatory for review, PLC-08). */
export function validateQuestion(d: Draft, forReview: boolean, isNew = false): Record<string, string> {
  const e: Record<string, string> = {};
  if (d.stem.trim().length < 5) e.stem_html = "Write the question (at least 5 characters).";
  if (d.type.startsWith("mcq")) {
    if (d.options.length < 2) e.options = "Add at least two options.";
    else if (d.options.some((o) => !o.text.trim())) e.options = "Fill in every option or remove empty ones.";
    else {
      const correct = d.options.filter((o) => o.is_correct).length;
      if (correct === 0) e.options = "Mark the correct answer.";
      if (d.type === "mcq_single" && correct > 1) e.options = "Single-answer questions have exactly one correct option.";
    }
  }
  const numeric = (d.numeric_value ?? "").trim();
  if (d.type === "numeric" && (numeric === "" || !Number.isFinite(Number(numeric)))) e["answer_key.value"] = "Enter the correct numeric answer.";
  if (isNew && !d.topic_id.trim()) e.primary_topic_id = "Choose a topic.";
  if (forReview && !d.explanation.trim()) e.explanation_html = "An explanation is required before review.";
  return e;
}

function contentBody(d: Draft): SendBody<"studio/questions/{question_id}/versions", "post"> {
  return {
    stem_html: d.stem.trim(),
    options: d.type.startsWith("mcq") ? d.options.map((o) => ({ html: o.text.trim(), is_correct: !!o.is_correct })) : [],
    answer_key: d.type === "numeric" ? { value: (d.numeric_value ?? "").trim(), tolerance: (d.numeric_tolerance ?? "0").trim() || "0" } : null,
    explanation_html: d.explanation.trim() || null,
    difficulty: Number(d.difficulty),
  };
}

/**
 * CMS-005 question editor: PLC-05 create, PLC-06 read (keys only for authorised authors),
 * PLC-07 new version (a draft is edited in place), PLC-08 submit review, PLC-10 publish, PLC-11 retire.
 */
export function QuestionEditor({ questionId }: { questionId: string }) {
  const isNew = questionId === "new";
  const router = useRouter();
  const toast = useToast();
  const fail = useFailToast();
  const detail = useApi<QuestionDetail>(isNew ? null : `studio/questions/${seg(questionId)}`);
  const [d, setD] = useState<Draft>(EMPTY);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [retireOpen, setRetireOpen] = useState(false);
  const [retireReason, setRetireReason] = useState("");
  const topics = useTopics();
  // Publisher must not be the author (matrix question.publish "P (≠ author)", audit ADM-48).
  const me = useApi<{ user: { id: string } }>(isNew ? null : "me");

  const q = detail.data;
  const current = q?.versions[0];
  useEffect(() => {
    if (q && q.versions[0]) {
      setD(toDraft(q, q.versions[0]));
      setDirty(false);
    }
  }, [q]);

  const status = isNew ? "draft" : (current?.status ?? "draft");
  const approved = status === "in_review" && !!current?.reviewed_by;
  const isAuthor = !!me.data?.user?.id && me.data.user.id === current?.authored_by;
  const keyHidden = !isNew && q !== undefined && !q.keys_visible;
  const editable = isNew || (!keyHidden && status !== "in_review");
  const upd = (patch: Partial<Draft>) => {
    setD((x) => ({ ...x, ...patch }));
    setDirty(true);
  };

  const handle = (err: unknown) => {
    if (err instanceof ApiError && err.code === "sod_violation") toast.show({ tone: "warning", title: "Another person must review or publish this question", requestId: err.requestId });
    else {
      const fe = fieldErrorsOf(err);
      if (Object.keys(fe).length) setErrors(fe);
      else fail(err);
    }
  };

  const save = async () => {
    const e = validateQuestion(d, false, isNew);
    setErrors(e);
    if (Object.keys(e).length) return;
    setBusy("save");
    try {
      if (isNew) {
        const tags = d.tags
          .split(",")
          .map((t) => t.trim())
          .filter(Boolean)
          .map((value) => ({ tag_type: "custom" as const, value }));
        const res = await api.post<QuestionDetail>("studio/questions", {
          ...contentBody(d),
          question_type: d.type as QuestionType,
          primary_topic_id: d.topic_id.trim(),
          tags,
        } satisfies SendBody<"studio/questions", "post">);
        if (res.kind === "ok") {
          toast.show({ tone: "success", title: "Draft created" });
          router.replace(`/studio/questions/${seg(res.data.question_id)}`);
        }
      } else {
        await api.post(`studio/questions/${seg(questionId)}/versions`, contentBody(d));
        toast.show({ tone: "success", title: status === "draft" ? "Draft saved" : "New draft version created" });
        await detail.reload();
      }
    } catch (err) {
      handle(err);
    } finally {
      setBusy(null);
    }
  };

  const action = async (key: "submit-review" | "publish" | "retire", ok: string, body: Record<string, unknown> = {}) => {
    if (key === "submit-review") {
      const e = validateQuestion(d, true);
      setErrors(e);
      if (Object.keys(e).length) return;
      if (dirty) {
        toast.show({ tone: "warning", title: "Save your changes before submitting" });
        return;
      }
    }
    setBusy(key);
    try {
      await api.post(`studio/questions/${seg(questionId)}/${key}`, body);
      toast.show({ tone: "success", title: ok });
      if (key === "retire") {
        setRetireOpen(false);
        setRetireReason("");
      }
      await detail.reload();
    } catch (err) {
      handle(err);
    } finally {
      setBusy(null);
    }
  };

  const form = (
    <div className="space-y-6">
      {!isNew ? (
        <div className="flex flex-wrap items-center gap-3">
          <StatusBadge status={approved ? "approved" : status} />
          {status === "in_review" && !approved ? <span className="text-sm text-fg-muted">Locked while in review.</span> : null}
          {status === "published" ? <span className="text-sm text-fg-muted">Published versions can&apos;t change; saving creates a new draft version.</span> : null}
        </div>
      ) : null}
      {q?.status === "retired" ? (
        <p role="status" className="rounded-lg border border-line bg-surface-sunken p-3 text-sm">
          <span className="font-medium">This question is retired.</span> {q.retired_reason ? `Reason: ${q.retired_reason}` : "No reason was recorded."}
        </p>
      ) : null}
      {current?.review_comment ? (
        <p role="status" className="rounded-lg border border-warning-border bg-warning-subtle p-3 text-sm text-warning-fg">
          <span className="font-medium">Reviewer comment:</span> {current.review_comment}
        </p>
      ) : null}
      {keyHidden ? (
        <p role="status" className="rounded-lg border border-info-border bg-info-subtle p-3 text-sm text-info-fg">
          The answer key and explanation are only shown to the author and reviewers.
        </p>
      ) : null}
      <Card title="Question">
        <div className="space-y-4">
          <FormField label="Type">
            {(p) => <Select {...p} value={d.type} disabled={!isNew} onChange={(e) => upd({ type: e.target.value })} options={TYPES} />}
          </FormField>
          <FormField label="Question text" required error={errors.stem_html}>
            {(p) => <TextArea {...p} rows={5} value={d.stem} disabled={!editable} onChange={(e) => upd({ stem: e.target.value })} />}
          </FormField>
          {d.type.startsWith("mcq") && !keyHidden ? (
            <fieldset className="space-y-2">
              <legend className="text-sm font-medium text-fg">Options (mark the correct answer{d.type === "mcq_multi" ? "s" : ""})</legend>
              {d.options.map((o, i) => (
                <div key={i} className="flex flex-wrap items-center gap-2">
                  <label className="inline-flex min-h-touch min-w-touch shrink-0 cursor-pointer items-center justify-center rounded-md hover:bg-surface-hover">
                  <input
                    type={d.type === "mcq_single" ? "radio" : "checkbox"}
                    name="correct"
                    aria-label={`Option ${i + 1} is correct`}
                    checked={!!o.is_correct}
                    disabled={!editable}
                    onChange={(e) =>
                      upd({ options: d.options.map((x, j) => (d.type === "mcq_single" ? { ...x, is_correct: j === i } : j === i ? { ...x, is_correct: e.target.checked } : x)) })
                    }
                    className="h-5 w-5 accent-[var(--td-brand)]"
                  />
                  </label>
                  <Input
                    aria-label={`Option ${i + 1}`}
                    className="min-w-48 flex-1"
                    value={o.text}
                    disabled={!editable}
                    onChange={(e) => upd({ options: d.options.map((x, j) => (j === i ? { ...x, text: e.target.value } : x)) })}
                  />
                  {editable && d.options.length > 2 ? (
                    <Button size="sm" variant="ghost" onClick={() => upd({ options: d.options.filter((_, j) => j !== i) })} aria-label={`Remove option ${i + 1}`}>
                      Remove
                    </Button>
                  ) : null}
                </div>
              ))}
              {errors.options ? (
                <p role="alert" className="text-xs font-medium text-danger-fg">
                  {errors.options}
                </p>
              ) : null}
              {editable && d.options.length < 10 ? (
                <Button size="sm" variant="secondary" onClick={() => upd({ options: [...d.options, { text: "", is_correct: false }] })}>
                  Add option
                </Button>
              ) : null}
            </fieldset>
          ) : null}
          {d.type === "numeric" && !keyHidden ? (
            <div className="grid gap-4 md:grid-cols-2">
              <FormField label="Correct answer" required error={errors["answer_key.value"]}>
                {(p) => <Input {...p} inputMode="decimal" value={d.numeric_value ?? ""} disabled={!editable} onChange={(e) => upd({ numeric_value: e.target.value })} />}
              </FormField>
              <FormField label="Tolerance (±)" error={errors["answer_key.tolerance"]}>
                {(p) => <Input {...p} inputMode="decimal" value={d.numeric_tolerance ?? "0"} disabled={!editable} onChange={(e) => upd({ numeric_tolerance: e.target.value })} />}
              </FormField>
            </div>
          ) : null}
          {!keyHidden ? (
            <FormField label="Explanation" required hint="Shown to students after they answer. Required before review." error={errors.explanation_html}>
              {(p) => <TextArea {...p} rows={4} value={d.explanation} disabled={!editable} onChange={(e) => upd({ explanation: e.target.value })} />}
            </FormField>
          ) : null}
          <div className="grid gap-4 md:grid-cols-3">
            <FormField label="Difficulty (1–5)" error={errors.difficulty}>
              {(p) => (
                <Select {...p} value={d.difficulty} disabled={!editable} onChange={(e) => upd({ difficulty: e.target.value })} options={[1, 2, 3, 4, 5].map((n) => ({ value: String(n), label: String(n) }))} />
              )}
            </FormField>
            <FormField label="Topic" required={isNew} error={errors.primary_topic_id}>
              {(p) => <TopicSelect {...p} topics={topics} value={d.topic_id} disabled={!isNew} onChange={(e) => upd({ topic_id: e.target.value })} />}
            </FormField>
            <FormField label="Tags" hint={isNew ? "Comma separated" : "Set when the question is created"}>
              {(p) => <Input {...p} value={d.tags} disabled={!isNew} onChange={(e) => upd({ tags: e.target.value })} />}
            </FormField>
          </div>
        </div>
      </Card>
      <div className="flex flex-wrap gap-2">
        {editable ? (
          <Button onClick={() => void save()} loading={busy === "save"}>
            {isNew ? "Create draft" : status === "draft" ? "Save draft" : "Save as new version"}
          </Button>
        ) : null}
        {!isNew && status === "draft" ? (
          <Button variant="secondary" onClick={() => void action("submit-review", "Submitted for review")} loading={busy === "submit-review"} disabled={!d.explanation.trim()}>
            Submit for review
          </Button>
        ) : null}
        {!isNew && approved && !isAuthor ? (
          <Button onClick={() => void action("publish", "Question published")} loading={busy === "publish"}>
            Publish
          </Button>
        ) : null}
        {!isNew && approved && isAuthor ? <span className="self-center text-sm text-fg-muted">Approved. Another content manager must publish a question you wrote.</span> : null}
        {!isNew && q?.status === "active" ? (
          <Button variant="danger-secondary" onClick={() => setRetireOpen(true)}>
            Retire
          </Button>
        ) : null}
      </div>
      <Dialog
        open={retireOpen}
        onClose={() => setRetireOpen(false)}
        dismissible={busy !== "retire"}
        title="Retire this question?"
        description="Retired questions are no longer drawn into new tests or practice. Past attempts keep their scores."
        footer={
          <>
            <Button variant="secondary" onClick={() => setRetireOpen(false)} disabled={busy === "retire"}>
              Cancel
            </Button>
            <Button variant="danger" loading={busy === "retire"} onClick={() => void action("retire", "Question retired", { reason: retireReason.trim() || null })}>
              Retire
            </Button>
          </>
        }
      >
        <FormField label="Reason" hint="Kept with the question for the audit trail.">
          {(p) => <TextArea {...p} rows={3} maxLength={500} value={retireReason} onChange={(e) => setRetireReason(e.target.value)} />}
        </FormField>
      </Dialog>
      {q ? (
        <Table
          caption="Versions"
          showCaption
          columns={[
            { key: "v", header: "Version", cell: (v: QuestionVersion) => v.version_no },
            { key: "s", header: "Status", cell: (v) => <StatusBadge status={v.status} /> },
            { key: "c", header: "Published", cell: (v) => formatDate(v.published_at) },
          ]}
          rows={q.versions}
          rowKey={(v) => v.question_version_id}
        />
      ) : null}
    </div>
  );

  if (isNew) return form;
  return <Boundary state={detail}>{() => form}</Boundary>;
}

/* ---------------------------------------------------------------- review queue */

/**
 * CMS-007 review queue. PLC-04 `version_status=awaiting_review` returns questions whose latest
 * version is in review and not yet reviewed (audit ADM-54); approved ones never show "Review".
 * Courses come from CAT-08 (editable draft in review). Reviewer ≠ author is enforced by the api.
 */
export function ReviewQueue({ mode = "studio" }: { mode?: "studio" | "admin" }) {
  const toast = useToast();
  const fail = useFailToast();
  // Admin reviews and may publish questions (question.review + question.publish; no authoring or course review).
  const admin = mode === "admin";
  const questions = useApi<{ items: QuestionSummary[] }>("studio/questions", { version_status: "awaiting_review", limit: 200 });
  const courses = useApi<Page<CourseSummary>>(!admin ? "studio/courses" : null, { limit: 100 });
  const [reviewing, setReviewing] = useState<QuestionSummary | null>(null);
  const [decision, setDecision] = useState<"approve" | "request_changes">("approve");
  const [comment, setComment] = useState("");
  const [publishNow, setPublishNow] = useState(false);
  const [busy, setBusy] = useState(false);

  const waitingQuestions = questions.data?.items.filter((x) => x.latest_version?.status === "in_review" && !x.latest_version.reviewed);
  const waitingCourses = courses.data?.data.filter((c) => courseStatus(c) === "in_review");

  const submit = async () => {
    if (!reviewing) return;
    if (decision === "request_changes" && comment.trim().length < 5) return;
    setBusy(true);
    try {
      await api.post(`studio/questions/${seg(reviewing.question_id)}/review`, { decision, comment: comment.trim() || null } satisfies Body<"studio/questions/{question_id}/review", "post">);
      if (decision === "approve" && publishNow) await api.post(`studio/questions/${seg(reviewing.question_id)}/publish`, {});
      toast.show({ tone: "success", title: decision === "approve" ? (publishNow ? "Approved and published" : "Approved") : "Changes requested" });
      setReviewing(null);
      setComment("");
      await questions.reload();
    } catch (err) {
      if (err instanceof ApiError && err.code === "sod_violation") toast.show({ tone: "warning", title: "You can't review your own question", requestId: err.requestId });
      else fail(err, "Couldn't save the review");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6">
      <Table
        caption="Questions waiting for review"
        showCaption
        columns={[
          {
            key: "s",
            header: "Question",
            cell: (x: QuestionSummary) =>
              admin ? (
                textOf(x.latest_version?.stem_html).slice(0, 140) || "Untitled"
              ) : (
                <Link className="text-fg-link underline" href={`/studio/questions/${seg(x.question_id)}`}>
                  {textOf(x.latest_version?.stem_html).slice(0, 140) || "Untitled"}
                </Link>
              ),
          },
          { key: "v", header: "Version", cell: (x) => x.latest_version?.version_no ?? "—" },
          {
            key: "r",
            header: <span className="sr-only">Actions</span>,
            align: "right",
            cell: (x) => (
              <Button size="sm" variant="secondary" onClick={() => setReviewing(x)}>
                Review
              </Button>
            ),
          },
        ]}
        rows={waitingQuestions}
        rowKey={(x) => x.question_id}
        loading={questions.loading}
        error={questions.error}
        onRetry={() => void questions.reload()}
        empty={{ title: "No questions waiting" }}
      />
      {admin ? null : (
      <Table
        caption="Courses waiting for review"
        showCaption
        columns={[
          {
            key: "t",
            header: "Course",
            cell: (c: CourseSummary) => (
              <Link className="text-fg-link underline" href={`/studio/courses/${seg(c.id)}`}>
                {c.title}
              </Link>
            ),
          },
          { key: "s", header: "Status", cell: () => <StatusBadge status="in_review" /> },
        ]}
        rows={waitingCourses}
        rowKey={(c) => c.id}
        loading={courses.loading}
        error={courses.error}
        onRetry={() => void courses.reload()}
        empty={{ title: "No courses waiting" }}
      />
      )}
      <Dialog
        open={reviewing !== null}
        onClose={() => setReviewing(null)}
        dismissible={!busy}
        title="Review question"
        description={textOf(reviewing?.latest_version?.stem_html).slice(0, 200)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setReviewing(null)} disabled={busy}>
              Cancel
            </Button>
            <Button onClick={() => void submit()} loading={busy} disabled={decision === "request_changes" && comment.trim().length < 5}>
              Save review
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          {admin && reviewing ? <QuestionPreview questionId={reviewing.question_id} /> : null}
          <FormField label="Decision">
            {(p) => (
              <Select
                {...p}
                value={decision}
                onChange={(e) => setDecision(e.target.value as typeof decision)}
                options={[
                  { value: "approve", label: "Approve" },
                  { value: "request_changes", label: "Request changes" },
                ]}
              />
            )}
          </FormField>
          <FormField label="Comment for the author" required={decision === "request_changes"} hint="Shown to the author in the question editor.">
            {(p) => <TextArea {...p} rows={3} value={comment} onChange={(e) => setComment(e.target.value)} />}
          </FormField>
          {decision === "approve" ? <Checkbox label="Publish right away" checked={publishNow} onChange={(e) => setPublishNow(e.target.checked)} /> : null}
        </div>
      </Dialog>
    </div>
  );
}

/** Read-only question (stem, options with the key, explanation) for reviewers who don't author (Admin). */
function QuestionPreview({ questionId }: { questionId: string }) {
  const detail = useApi<QuestionDetail>(`studio/questions/${seg(questionId)}`);
  return (
    <Boundary state={detail} rows={3}>
      {(q) => {
        const v = q.versions[0];
        if (!v) return null;
        return (
          <div className="space-y-2 rounded-lg border border-line p-3 text-sm">
            <p className="whitespace-pre-wrap text-fg">{textOf(v.stem_html)}</p>
            {v.options.length ? (
              <ul className="space-y-1" aria-label="Options">
                {v.options.map((o) => {
                  const correct = o.is_correct ?? v.correct_option_ids?.includes(o.option_id) ?? false;
                  return (
                    <li key={o.option_id} className={correct ? "font-semibold text-success-fg" : "text-fg-secondary"}>
                      {correct ? "✓ " : "• "}
                      {textOf(o.html)}
                      {correct ? <span className="sr-only"> (correct)</span> : null}
                    </li>
                  );
                })}
              </ul>
            ) : v.answer_key ? (
              <p className="text-fg-secondary">Answer key: {JSON.stringify(v.answer_key)}</p>
            ) : null}
            {v.explanation_html ? <p className="text-fg-muted">Explanation: {textOf(v.explanation_html)}</p> : null}
          </div>
        );
      }}
    </Boundary>
  );
}
