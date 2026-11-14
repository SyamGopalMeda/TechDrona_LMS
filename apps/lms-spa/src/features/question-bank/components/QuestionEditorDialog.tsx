"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { Button, Checkbox, Dialog, FormField, Input, Select, useToast } from "@/components/ui";
import { api } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { RefSelect } from "@/features/studio/components/Pickers";
import { fieldErrorsOf, StatusBadge, TextArea, useFailToast } from "@/features/trainer/shared/ui";
import { seg, useApi } from "@/features/trainer/shared/use-api";
import { likertLabels } from "../lib/labels";
import type { ImportKind, QuestionFull, QuestionType, QuestionVersionDetail } from "../lib/types";
import { ImageField, KindTiles, TagInput, type ImageValue } from "./parts";

export type EditorKind = "mcq" | "coding" | "essay" | "poll" | "survey" | "word_cloud" | "numeric" | "fill_blank";

export interface EditorOption {
  html: string;
  is_correct: boolean;
  image: ImageValue | null;
  feedback_html?: string | null;
}

export interface EditorState {
  kind: EditorKind;
  stem: string;
  stemImages: ImageValue[];
  options: EditorOption[];
  explanation: string;
  difficulty: number;
  tags: string[];
  codingProblemId: string;
  referenceAnswer: string;
  rubric: { criterion: string; marks: string }[];
  essayMaxWords: string;
  allowMultiple: boolean;
  scale: "likert" | "open";
  points: number;
  likert: string[];
  wcMaxWords: string;
  wcMaxChars: string;
  /** Fields carried over unchanged from the loaded version (marks, timing). */
  carry: Record<string, unknown>;
}

const opt = (is_correct = false): EditorOption => ({ html: "", is_correct, image: null });

export function emptyEditor(kind: EditorKind = "mcq"): EditorState {
  return {
    kind,
    stem: "",
    stemImages: [],
    options: kind === "mcq" ? [opt(true), opt(), opt(), opt()] : kind === "poll" ? [opt(), opt()] : [],
    explanation: "",
    difficulty: 3,
    tags: [],
    codingProblemId: "",
    referenceAnswer: "",
    rubric: [],
    essayMaxWords: "",
    allowMultiple: false,
    scale: "likert",
    points: 5,
    likert: likertLabels(5),
    wcMaxWords: "3",
    wcMaxChars: "20",
    carry: {},
  };
}

const KIND_OF_TILE: Record<ImportKind, EditorKind> = { mcq: "mcq", code: "coding", essay: "essay", poll: "poll", survey: "survey", word_cloud: "word_cloud" };
const TILE_OF_KIND: Partial<Record<EditorKind, ImportKind>> = { mcq: "mcq", coding: "code", essay: "essay", poll: "poll", survey: "survey", word_cloud: "word_cloud" };

export function editorKindOf(type: string): EditorKind {
  if (type === "mcq_single" || type === "mcq_multi") return "mcq";
  return (["coding", "essay", "poll", "survey", "word_cloud", "numeric", "fill_blank"].includes(type) ? type : "mcq") as EditorKind;
}

const num = (v: unknown, d: number) => (typeof v === "number" && Number.isFinite(v) ? v : typeof v === "string" && v.trim() && Number.isFinite(Number(v)) ? Number(v) : d);

/** Editor state from a loaded question version. */
export function fromVersion(q: QuestionFull, v: QuestionVersionDetail): EditorState {
  const kind = editorKindOf(q.question_type);
  const s = (v.settings ?? {}) as Record<string, unknown>;
  const key = (v.answer_key ?? {}) as { reference_answer_html?: unknown; rubric?: unknown };
  const base = emptyEditor(kind);
  const scale = s.scale === "open" ? "open" : "likert";
  const points = Math.min(7, Math.max(3, num(s.points, v.options.length >= 3 ? v.options.length : 5)));
  return {
    ...base,
    stem: v.stem_html,
    stemImages: (v.stem_images ?? []).map((i) => ({ media_id: i.media_id, url: i.url, phase: "ready" as const })),
    options: kind === "survey" ? [] : v.options.map((o) => ({ html: o.html, is_correct: !!o.is_correct, image: o.image ? { media_id: o.image.media_id, url: o.image.url, phase: "ready" as const } : null, feedback_html: o.feedback_html ?? null })),
    explanation: v.explanation_html ?? "",
    difficulty: v.difficulty,
    tags: q.tags.map((t) => t.value).filter((t): t is string => !!t),
    codingProblemId: v.coding_problem_id ?? "",
    referenceAnswer: typeof key.reference_answer_html === "string" ? key.reference_answer_html : "",
    rubric: Array.isArray(key.rubric) ? (key.rubric as { criterion?: unknown; marks?: unknown }[]).map((r) => ({ criterion: String(r.criterion ?? ""), marks: String(r.marks ?? "") })) : [],
    essayMaxWords: s.max_words !== undefined && kind === "essay" ? String(s.max_words) : "",
    allowMultiple: !!s.allow_multiple,
    scale,
    points,
    likert: kind === "survey" && scale === "likert" && v.options.length ? v.options.map((o) => o.html) : likertLabels(points),
    wcMaxWords: kind === "word_cloud" ? String(num(s.max_words, 3)) : base.wcMaxWords,
    wcMaxChars: kind === "word_cloud" ? String(num(s.max_chars, 20)) : base.wcMaxChars,
    carry: Object.fromEntries(
      (["default_marks", "default_negative", "expected_seconds"] as const).filter((k) => v[k] !== undefined && v[k] !== null).map((k) => [k, v[k]]),
    ),
  };
}

export const isGraded = (k: EditorKind) => k === "mcq" || k === "coding" || k === "essay" || k === "numeric" || k === "fill_blank";

/** Server question_type; MCQ is single or multi by the number of ticked options (create only). */
export function serverType(s: EditorState, fixedType?: string): QuestionType {
  if (fixedType) return fixedType as QuestionType;
  if (s.kind === "mcq") return s.options.filter((o) => o.is_correct).length > 1 ? "mcq_multi" : "mcq_single";
  return s.kind as QuestionType;
}

const intIn = (v: string, lo: number, hi: number) => /^\d+$/.test(v.trim()) && Number(v) >= lo && Number(v) <= hi;

/** Client-side checks mirroring the api rules (the api stays authoritative). */
export function validateEditor(s: EditorState, opts: { forReview?: boolean; fixedType?: string } = {}): Record<string, string> {
  const e: Record<string, string> = {};
  if (s.stem.trim().length < 5) e.stem_html = "Write the question (at least 5 characters).";
  const images = [...s.stemImages, ...s.options.map((o) => o.image).filter((x): x is ImageValue => !!x)];
  if (images.some((i) => i.phase !== "ready")) e.images = "Wait for images to finish uploading and scanning, or remove the ones that failed.";
  if (s.kind === "mcq" || s.kind === "poll") {
    if (s.options.length < 2 || s.options.length > 10) e.options = "Use between 2 and 10 options.";
    else if (s.options.some((o) => !o.html.trim() && !o.image)) e.options = "Fill in every option or remove empty ones.";
    else if (s.kind === "mcq") {
      const correct = s.options.filter((o) => o.is_correct).length;
      if (correct === 0) e.options = "Tick the correct answer.";
      else if (opts.fixedType === "mcq_single" && correct > 1) e.options = "This question has exactly one correct answer. Create a new question to allow several.";
    }
  }
  if (s.kind === "survey" && s.scale === "likert" && s.likert.some((l) => !l.trim())) e.options = "Give every scale point a label.";
  if (s.kind === "word_cloud") {
    if (!intIn(s.wcMaxWords, 1, 5)) e["settings.max_words"] = "Allow 1 to 5 words per answer.";
    if (!intIn(s.wcMaxChars, 1, 40)) e["settings.max_chars"] = "Allow 1 to 40 characters per word.";
  }
  if (s.kind === "essay") {
    if (s.essayMaxWords.trim() && !intIn(s.essayMaxWords, 1, 100000)) e["settings.max_words"] = "Enter a whole number of words.";
    if (s.rubric.some((r) => !r.criterion.trim() || !/^\d+(\.\d+)?$/.test(r.marks.trim()))) e.rubric = "Each rubric row needs a criterion and marks.";
  }
  if (s.kind === "coding" && !s.codingProblemId) e.coding_problem_id = "Choose a coding problem.";
  if (opts.forReview && isGraded(s.kind) && !s.explanation.trim()) e.explanation_html = "An explanation is required before review.";
  return e;
}

/** Version content fields (shared by create and `versions`). */
export function buildContent(s: EditorState): Record<string, unknown> {
  const body: Record<string, unknown> = {
    stem_html: s.stem.trim(),
    stem_image_ids: s.stemImages.map((i) => i.media_id),
    difficulty: s.difficulty,
    explanation_html: isGraded(s.kind) ? s.explanation.trim() || null : null,
    answer_key: null,
    options: [],
    settings: {},
    ...s.carry,
  };
  const withImage = (o: EditorOption, correct: boolean | undefined) => ({
    html: o.html.trim(),
    ...(correct !== undefined ? { is_correct: correct } : {}),
    ...(o.feedback_html ? { feedback_html: o.feedback_html } : {}),
    ...(o.image ? { image_id: o.image.media_id } : {}),
  });
  switch (s.kind) {
    case "mcq":
      body.options = s.options.map((o) => withImage(o, o.is_correct));
      break;
    case "poll":
      body.options = s.options.map((o) => withImage(o, undefined));
      body.settings = { allow_multiple: s.allowMultiple };
      break;
    case "survey":
      body.settings = s.scale === "likert" ? { scale: "likert", points: s.points } : { scale: "open" };
      body.options = s.scale === "likert" ? s.likert.map((l) => ({ html: l.trim() })) : [];
      break;
    case "word_cloud":
      body.settings = { max_words: Number(s.wcMaxWords), max_chars: Number(s.wcMaxChars) };
      break;
    case "essay":
      body.answer_key = {
        reference_answer_html: s.referenceAnswer.trim() || undefined,
        rubric: s.rubric.map((r) => ({ criterion: r.criterion.trim(), marks: Number(r.marks) })),
      };
      body.settings = s.essayMaxWords.trim() ? { max_words: Number(s.essayMaxWords) } : {};
      break;
    case "coding":
      body.coding_problem_id = s.codingProblemId;
      break;
    default:
      break;
  }
  return body;
}

export interface QuestionEditorDialogProps {
  open: boolean;
  onClose: () => void;
  /** Bank the new question is added to (create). */
  bankId?: string | null;
  /** Edit this question; omit/null to create. */
  questionId?: string | null;
  organizationId?: string | null;
  onSaved: () => void;
}

const DIFFS = [1, 2, 3, 4, 5].map((n) => ({ value: String(n), label: `${n}${n === 1 ? " (easiest)" : n === 5 ? " (hardest)" : ""}` }));

/** Create / edit a bank question of any type (MCQ, Code, Essay, Poll, Survey, Words). */
export function QuestionEditorDialog({ open, onClose, bankId, questionId, organizationId, onSaved }: QuestionEditorDialogProps) {
  const toast = useToast();
  const fail = useFailToast();
  const isNew = !questionId;
  const detail = useApi<QuestionFull>(open && questionId ? `studio/questions/${seg(questionId)}` : null);
  const [s, setS] = useState<EditorState>(() => emptyEditor());
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<"save" | "review" | null>(null);
  const [dirty, setDirty] = useState(false);

  const q = detail.data;
  const current = q?.versions[0];
  useEffect(() => {
    if (!open) return;
    setErrors({});
    setDirty(false);
    if (isNew) setS(emptyEditor());
  }, [open, isNew]);
  useEffect(() => {
    if (open && q && q.versions[0]) {
      setS(fromVersion(q, q.versions[0]));
      setDirty(false);
    }
  }, [open, q]);

  const up = (patch: Partial<EditorState>) => {
    setS((x) => ({ ...x, ...patch }));
    setDirty(true);
  };
  const fixedType = isNew ? undefined : q?.question_type;
  const status = isNew ? "draft" : (current?.status ?? "draft");
  const keyHidden = !isNew && q !== undefined && !q.keys_visible;
  const legacy = s.kind === "numeric" || s.kind === "fill_blank";
  const locked = !isNew && (status === "in_review" || keyHidden || legacy || q?.status === "retired");
  const coding = useApi<{ data: { problem_id: string; title: string; status: string }[] }>(open && s.kind === "coding" ? "studio/coding/problems" : null, { limit: 100 });
  const codingOptions = useMemo(
    () => ({ ...coding, data: coding.data?.data.map((p) => ({ id: p.problem_id, label: p.status === "published" ? p.title : `${p.title} (${p.status.replace(/_/g, " ")})` })) }),
    [coding],
  );

  const handle = (err: unknown, title: string) => {
    if (err instanceof ApiError && err.code === "sod_violation") {
      toast.show({ tone: "warning", title: "Another person must review or publish this question", requestId: err.requestId });
      return;
    }
    const fe = fieldErrorsOf(err);
    if (Object.keys(fe).length) setErrors(fe);
    else fail(err, title);
  };

  const save = async () => {
    const e = validateEditor(s, { fixedType });
    setErrors(e);
    if (Object.keys(e).length) return;
    setBusy("save");
    try {
      if (isNew) {
        const res = await api.post("studio/questions", {
          ...buildContent(s),
          question_type: serverType(s),
          ...(bankId ? { bank_id: bankId } : {}),
          ...(organizationId ? { organization_id: organizationId } : {}),
          tags: s.tags.map((value) => ({ tag_type: "custom", value })),
        });
        if (res.kind === "ok") {
          toast.show({ tone: "success", title: "Question added as a draft", description: "Submit it for review before using it with learners." });
          onSaved();
          onClose();
        }
      } else {
        await api.post(`studio/questions/${seg(questionId!)}/versions`, buildContent(s));
        toast.show({ tone: "success", title: status === "draft" ? "Draft saved" : "New draft version created" });
        setDirty(false);
        await detail.reload();
        onSaved();
      }
    } catch (err) {
      handle(err, "Couldn't save the question");
    } finally {
      setBusy(null);
    }
  };

  const submitReview = async () => {
    const e = validateEditor(s, { fixedType, forReview: true });
    setErrors(e);
    if (Object.keys(e).length) return;
    if (dirty) {
      toast.show({ tone: "warning", title: "Save your changes before submitting" });
      return;
    }
    setBusy("review");
    try {
      await api.post(`studio/questions/${seg(questionId!)}/submit-review`, {});
      toast.show({ tone: "success", title: "Submitted for review" });
      await detail.reload();
      onSaved();
    } catch (err) {
      handle(err, "Couldn't submit for review");
    } finally {
      setBusy(null);
    }
  };

  const setOption = (i: number, patch: Partial<EditorOption>) => up({ options: s.options.map((o, j) => (j === i ? { ...o, ...patch } : o)) });

  const loadingEdit = !isNew && !q;
  const body = loadingEdit ? (
    detail.error ? (
      <div role="alert" className="space-y-2 text-sm text-danger-fg">
        <p>Couldn&apos;t load this question.</p>
        <Button size="sm" variant="secondary" onClick={() => void detail.reload()}>
          Try again
        </Button>
      </div>
    ) : (
      <p aria-busy="true" className="text-sm text-fg-muted">
        Loading question…
      </p>
    )
  ) : (
    <div className="max-h-[65vh] space-y-5 overflow-y-auto pr-1">
      {isNew ? (
        <KindTiles value={TILE_OF_KIND[s.kind] ?? "mcq"} onChange={(k) => setS({ ...emptyEditor(KIND_OF_TILE[k]), stem: s.stem, tags: s.tags, difficulty: s.difficulty })} />
      ) : (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <StatusBadge status={status} />
          {status === "in_review" ? <span className="text-fg-muted">Locked while in review.</span> : null}
          {status === "published" ? <span className="text-fg-muted">Published versions can&apos;t change; saving creates a new draft version.</span> : null}
          {q?.status === "retired" ? <span className="text-fg-muted">This question is retired.</span> : null}
        </div>
      )}
      {keyHidden ? (
        <p role="status" className="rounded-lg border border-info-border bg-info-subtle p-3 text-sm text-info-fg">
          The answer key is only shown to the author and reviewers, so this question can&apos;t be edited here.
        </p>
      ) : null}
      {legacy && !isNew ? (
        <p role="status" className="rounded-lg border border-info-border bg-info-subtle p-3 text-sm text-info-fg">
          Edit {s.kind === "numeric" ? "numeric" : "fill in the blank"} questions in the full question editor.
        </p>
      ) : null}
      {current?.review_comment ? (
        <p role="status" className="rounded-lg border border-warning-border bg-warning-subtle p-3 text-sm text-warning-fg">
          <span className="font-medium">Reviewer comment:</span> {current.review_comment}
        </p>
      ) : null}

      <FormField label="Question description" required error={errors.stem_html}>
        {(p) => <TextArea {...p} rows={4} value={s.stem} disabled={locked} placeholder="Write the question…" onChange={(e) => up({ stem: e.target.value })} />}
      </FormField>
      <div className="space-y-2">
        <p className="text-sm font-medium text-fg">
          Question image <span className="font-normal text-fg-muted">(optional)</span>
        </p>
        {s.stemImages.map((img, i) => (
          <ImageField
            key={img.media_id}
            label={`Question image ${i + 1}`}
            value={img}
            disabled={locked}
            organizationId={organizationId}
            onChange={(v) => up({ stemImages: v ? s.stemImages.map((x, j) => (j === i ? v : x)) : s.stemImages.filter((_, j) => j !== i) })}
          />
        ))}
        {s.stemImages.length < 4 && !locked ? (
          <ImageField label="Add question image" value={null} organizationId={organizationId} onChange={(v) => v && up({ stemImages: [...s.stemImages, v] })} />
        ) : null}
        {errors.images ? (
          <p role="alert" className="text-xs font-medium text-danger-fg">
            {errors.images}
          </p>
        ) : null}
      </div>

      {s.kind === "mcq" || s.kind === "poll" ? (
        <fieldset className="space-y-2">
          <legend className="text-sm font-medium text-fg">{s.kind === "mcq" ? "Options — tick the correct one(s)" : "Options"}</legend>
          {s.options.map((o, i) => (
            <div key={i} className="flex flex-wrap items-center gap-2 rounded-md border border-line p-2">
              {s.kind === "mcq" ? (
                <input
                  type="checkbox"
                  aria-label={`Option ${i + 1} is correct`}
                  checked={o.is_correct}
                  disabled={locked}
                  onChange={(e) => setOption(i, { is_correct: e.target.checked })}
                  className="h-5 w-5 [@media(pointer:coarse)]:h-6 [@media(pointer:coarse)]:w-6 accent-[var(--td-brand)]"
                />
              ) : null}
              <Input aria-label={`Option ${i + 1}`} className="min-w-40 flex-1" value={o.html} disabled={locked} placeholder={`Option ${i + 1}`} onChange={(e) => setOption(i, { html: e.target.value })} />
              <ImageField compact label={`Option ${i + 1} image`} value={o.image} disabled={locked} organizationId={organizationId} onChange={(v) => setOption(i, { image: v })} />
              {!locked && s.options.length > 2 ? (
                <Button size="sm" variant="ghost" aria-label={`Remove option ${i + 1}`} onClick={() => up({ options: s.options.filter((_, j) => j !== i) })}>
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
          {!locked && s.options.length < 10 ? (
            <Button size="sm" variant="secondary" onClick={() => up({ options: [...s.options, opt()] })}>
              Add option
            </Button>
          ) : null}
          {s.kind === "poll" ? <Checkbox label="Allow choosing more than one option" checked={s.allowMultiple} disabled={locked} onChange={(e) => up({ allowMultiple: e.target.checked })} /> : null}
        </fieldset>
      ) : null}

      {s.kind === "coding" ? (
        <div className="space-y-2">
          <FormField label="Coding problem" required error={errors.coding_problem_id} hint="Statement, languages and test cases come from the coding problem.">
            {(p) => <RefSelect {...p} state={codingOptions} noun="coding problem" value={s.codingProblemId} disabled={locked} onChange={(e) => up({ codingProblemId: e.target.value })} />}
          </FormField>
          <p className="text-xs text-fg-muted">
            Hidden test cases are managed in{" "}
            <Link href="/studio/coding" className="text-fg-link underline">
              Coding problems
            </Link>{" "}
            and are never shown here.
          </p>
        </div>
      ) : null}

      {s.kind === "essay" ? (
        <div className="space-y-4">
          <FormField label="Reference answer" hint="Seen by graders only.">
            {(p) => <TextArea {...p} rows={3} value={s.referenceAnswer} disabled={locked} onChange={(e) => up({ referenceAnswer: e.target.value })} />}
          </FormField>
          <fieldset className="space-y-2">
            <legend className="text-sm font-medium text-fg">Rubric</legend>
            {s.rubric.map((r, i) => (
              <div key={i} className="flex flex-wrap items-center gap-2">
                <Input aria-label={`Criterion ${i + 1}`} className="min-w-40 flex-1" value={r.criterion} disabled={locked} placeholder="Criterion" onChange={(e) => up({ rubric: s.rubric.map((x, j) => (j === i ? { ...x, criterion: e.target.value } : x)) })} />
                <Input aria-label={`Marks for criterion ${i + 1}`} className="w-24" inputMode="decimal" value={r.marks} disabled={locked} placeholder="Marks" onChange={(e) => up({ rubric: s.rubric.map((x, j) => (j === i ? { ...x, marks: e.target.value } : x)) })} />
                {!locked ? (
                  <Button size="sm" variant="ghost" aria-label={`Remove criterion ${i + 1}`} onClick={() => up({ rubric: s.rubric.filter((_, j) => j !== i) })}>
                    Remove
                  </Button>
                ) : null}
              </div>
            ))}
            {errors.rubric ? (
              <p role="alert" className="text-xs font-medium text-danger-fg">
                {errors.rubric}
              </p>
            ) : null}
            {!locked ? (
              <Button size="sm" variant="secondary" onClick={() => up({ rubric: [...s.rubric, { criterion: "", marks: "" }] })}>
                Add criterion
              </Button>
            ) : null}
          </fieldset>
          <FormField label="Maximum words (optional)" error={errors["settings.max_words"]}>
            {(p) => <Input {...p} className="w-40" inputMode="numeric" value={s.essayMaxWords} disabled={locked} onChange={(e) => up({ essayMaxWords: e.target.value })} />}
          </FormField>
        </div>
      ) : null}

      {s.kind === "survey" ? (
        <div className="space-y-3">
          <div role="radiogroup" aria-label="Answer format" className="flex flex-wrap gap-4 text-sm">
            {(["likert", "open"] as const).map((v) => (
              <label key={v} className="inline-flex items-center gap-2">
                <input type="radio" name="survey-scale" checked={s.scale === v} disabled={locked} onChange={() => up({ scale: v })} className="h-4 w-4 [@media(pointer:coarse)]:h-6 [@media(pointer:coarse)]:w-6 accent-[var(--td-brand)]" />
                {v === "likert" ? "Rating scale" : "Open answer"}
              </label>
            ))}
          </div>
          {s.scale === "likert" ? (
            <>
              <FormField label="Points on the scale">
                {(p) => (
                  <Select
                    {...p}
                    className="w-32"
                    value={String(s.points)}
                    disabled={locked}
                    onChange={(e) => up({ points: Number(e.target.value), likert: likertLabels(Number(e.target.value)) })}
                    options={[3, 4, 5, 6, 7].map((n) => ({ value: String(n), label: String(n) }))}
                  />
                )}
              </FormField>
              <fieldset className="grid gap-2 sm:grid-cols-2">
                <legend className="mb-1 text-sm font-medium text-fg">Scale labels</legend>
                {s.likert.map((l, i) => (
                  <Input key={i} aria-label={`Scale point ${i + 1} label`} value={l} disabled={locked} onChange={(e) => up({ likert: s.likert.map((x, j) => (j === i ? e.target.value : x)) })} />
                ))}
              </fieldset>
              {errors.options ? (
                <p role="alert" className="text-xs font-medium text-danger-fg">
                  {errors.options}
                </p>
              ) : null}
            </>
          ) : null}
        </div>
      ) : null}

      {s.kind === "word_cloud" ? (
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField label="Words per answer (1–5)" error={errors["settings.max_words"]}>
            {(p) => <Input {...p} type="number" min={1} max={5} value={s.wcMaxWords} disabled={locked} onChange={(e) => up({ wcMaxWords: e.target.value })} />}
          </FormField>
          <FormField label="Characters per word (1–40)" error={errors["settings.max_chars"]}>
            {(p) => <Input {...p} type="number" min={1} max={40} value={s.wcMaxChars} disabled={locked} onChange={(e) => up({ wcMaxChars: e.target.value })} />}
          </FormField>
        </div>
      ) : null}

      {isGraded(s.kind) ? (
        <FormField label="Explanation" hint="Shown to learners after they answer. Required before review." error={errors.explanation_html}>
          {(p) => <TextArea {...p} rows={3} value={s.explanation} disabled={locked} onChange={(e) => up({ explanation: e.target.value })} />}
        </FormField>
      ) : null}
      <div className="grid gap-4 sm:grid-cols-2">
        <FormField label="Difficulty (1–5)" error={errors.difficulty}>
          {(p) => <Select {...p} value={String(s.difficulty)} disabled={locked} onChange={(e) => up({ difficulty: Number(e.target.value) })} options={DIFFS} />}
        </FormField>
      </div>
      <TagInput value={s.tags} onChange={(tags) => up({ tags })} disabled={!isNew} hint={isNew ? undefined : "Tags are set when the question is created."} />
      {!isNew ? (
        <p className="text-sm">
          <Link href={`/studio/questions/${seg(questionId!)}`} className="text-fg-link underline">
            Open in the full question editor
          </Link>{" "}
          <span className="text-fg-muted">for review, publishing and version history.</span>
        </p>
      ) : null}
    </div>
  );

  return (
    <Dialog
      open={open}
      onClose={onClose}
      dismissible={busy === null}
      className="max-w-2xl"
      title={isNew ? "New question" : "Edit question"}
      description={isNew ? "New questions are saved as drafts. Submit them for review before use." : undefined}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy !== null}>
            Cancel
          </Button>
          {!isNew && status === "draft" && !locked ? (
            <Button variant="secondary" onClick={() => void submitReview()} loading={busy === "review"} disabled={busy === "save"}>
              Submit for review
            </Button>
          ) : null}
          {!locked && !loadingEdit ? (
            <Button onClick={() => void save()} loading={busy === "save"} disabled={busy === "review"}>
              {isNew ? "Add question" : "Save"}
            </Button>
          ) : null}
        </>
      }
    >
      {body}
    </Dialog>
  );
}
