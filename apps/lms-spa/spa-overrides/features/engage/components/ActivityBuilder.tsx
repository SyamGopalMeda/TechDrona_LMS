"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Badge, Button, Card, ErrorState, FormField, Input, PageHeader, Select, useToast, type Crumb } from "@/components/ui";
import { SectionNav, StickyActionBar } from "@/features/studio/components/EditorChrome";
import { api } from "@/lib/api/client";
import { isApiError } from "@/lib/api/errors";
import { cn } from "@/lib/ui/cn";
import { QuestionBankPicker, type PickedQuestion } from "@/features/question-bank";
import { useTrainerBatches } from "@/features/trainer/lib/batches";
import { hasPlatformGrant, useMyGrants } from "@/features/trainer/shared/grants";
import { seg, useApi } from "@/features/trainer/shared/use-api";
import {
  appendQuestions,
  blankOption,
  blankQuestion,
  fromActivity,
  fromDrafts,
  initialState,
  isChoice,
  move,
  toActivityIn,
  toggleCorrect,
  validateBuilder,
  withKind,
  type BuilderErrors,
  type BuilderState,
  type DraftQuestion,
} from "../lib/builder";
import { KIND_LABEL, KINDS_BY_TYPE, TYPE_LABEL } from "../lib/labels";
import type { Activity, ActivityType, BankImportResult, QuestionKind } from "../lib/types";
import { errorText, Loading, Segmented } from "./parts";
import { useEngageScope } from "../lib/scope";

/** Select value for "no batch" (platform activity). Not a uuid, so it can never be a batch id. */
const PLATFORM_WIDE = "__platform__";

const SKIP_REASON: Record<string, string> = {
  not_found: "not found",
  unsupported_type: "not a multiple-choice question",
  no_version: "no published version",
  forbidden: "you can't use it",
};

function QuestionEditor({
  index,
  count,
  question: q,
  type,
  errors,
  onChange,
  onMove,
  onRemove,
}: {
  index: number;
  count: number;
  question: DraftQuestion;
  type: ActivityType;
  errors: BuilderErrors;
  onChange: (q: DraftQuestion) => void;
  onMove: (delta: number) => void;
  onRemove: () => void;
}) {
  const f = `questions[${index}]`;
  const kinds = KINDS_BY_TYPE[type];
  const quiz = type === "quiz";
  const n = index + 1;
  const optError = errors[`${f}.options`];
  return (
    <li className="rounded-xl border border-line bg-surface p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-display text-sm font-semibold text-fg">Question {n}</h3>
        <div className="flex flex-wrap gap-1">
          <Button size="sm" variant="ghost" onClick={() => onMove(-1)} disabled={index === 0} aria-label={`Move question ${n} up`}>
            <span aria-hidden="true">↑</span> Up
          </Button>
          <Button size="sm" variant="ghost" onClick={() => onMove(1)} disabled={index === count - 1} aria-label={`Move question ${n} down`}>
            <span aria-hidden="true">↓</span> Down
          </Button>
          <Button size="sm" variant="ghost" onClick={onRemove} disabled={count === 1} aria-label={`Remove question ${n}`} className="text-danger-fg hover:bg-danger-subtle">
            Remove
          </Button>
        </div>
      </div>
      <div className="space-y-3">
        {kinds.length > 1 ? (
          <FormField label={`Question ${n} type`} error={errors[`${f}.kind`]}>
            {(p) => (
              <Select
                {...p}
                value={q.kind}
                onChange={(e) => onChange(withKind(q, e.target.value as QuestionKind))}
                options={kinds.map((k) => ({ value: k, label: KIND_LABEL[k] }))}
                className="sm:w-56"
              />
            )}
          </FormField>
        ) : null}
        <FormField label={`Question ${n}`} error={errors[`${f}.prompt`]} required>
          {(p) => (
            <textarea
              {...p}
              rows={2}
              maxLength={2000}
              value={q.prompt}
              onChange={(e) => onChange({ ...q, prompt: e.target.value })}
              className={cn(
                "block w-full rounded-md border bg-surface px-3 py-2 text-sm text-fg focus-visible:outline-none focus-visible:shadow-focus",
                errors[`${f}.prompt`] ? "border-danger-border" : "border-line-control",
              )}
            />
          )}
        </FormField>
        {q.kind === "word" ? (
          <FormField label="Words per answer" hint="Participants can send up to this many words." error={errors[`${f}.max_words`]}>
            {(p) => (
              <Select
                {...p}
                value={String(q.max_words ?? 1)}
                onChange={(e) => onChange({ ...q, max_words: Number(e.target.value) })}
                options={[1, 2, 3, 4, 5].map((v) => ({ value: String(v), label: String(v) }))}
                className="sm:w-32"
              />
            )}
          </FormField>
        ) : null}
        {q.kind === "rating" ? <p className="text-sm text-fg-muted">Participants choose a rating from 1 to 5.</p> : null}
        {q.kind === "text" ? <p className="text-sm text-fg-muted">Participants type a short answer (up to 500 characters).</p> : null}
        {isChoice(q.kind) ? (
          <fieldset className="space-y-2" aria-describedby={optError ? `${q.key}-opt-err` : undefined}>
            <legend className="text-sm font-medium text-fg">Options</legend>
            {quiz ? <p className="text-xs text-fg-muted">Tick the correct answer{q.kind === "multi_choice" ? "s" : ""}.</p> : null}
            {q.key_missing ? (
              <p className="text-xs text-warning-fg">The answer key wasn&apos;t shared with you — tick the correct answer.</p>
            ) : null}
            <ul className="space-y-2">
              {q.options.map((o, oi) => (
                <li key={o.key} className="flex items-center gap-2">
                  {quiz ? (
                    // The whole 44 px box is the hit target, not just the 20 px control.
                    <label className="grid min-h-touch min-w-touch shrink-0 cursor-pointer place-items-center rounded-md focus-within:shadow-focus hover:bg-surface-hover">
                      <input
                        type={q.kind === "single_choice" ? "radio" : "checkbox"}
                        name={`correct-${q.key}`}
                        checked={o.is_correct}
                        onChange={() => onChange({ ...toggleCorrect(q, o.key), key_missing: false })}
                        aria-label={`Option ${oi + 1} is correct`}
                        className="h-5 w-5 [@media(pointer:coarse)]:h-6 [@media(pointer:coarse)]:w-6 accent-[var(--td-brand)] focus-visible:outline-none"
                      />
                    </label>
                  ) : null}
                  <Input
                    aria-label={`Question ${n} option ${oi + 1}`}
                    placeholder={`Option ${oi + 1}`}
                    maxLength={500}
                    value={o.text}
                    onChange={(e) => onChange({ ...q, options: q.options.map((x) => (x.key === o.key ? { ...x, text: e.target.value } : x)) })}
                  />
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={q.options.length <= 2}
                    onClick={() => onChange({ ...q, options: q.options.filter((x) => x.key !== o.key) })}
                    aria-label={`Remove option ${oi + 1}`}
                    className="shrink-0"
                  >
                    <span aria-hidden="true">✕</span>
                  </Button>
                </li>
              ))}
            </ul>
            {optError ? (
              <p id={`${q.key}-opt-err`} role="alert" className="text-xs font-medium text-danger-fg">
                {optError}
              </p>
            ) : null}
            <Button size="sm" variant="ghost" disabled={q.options.length >= 10} onClick={() => onChange({ ...q, options: [...q.options, blankOption()] })}>
              + Add option
            </Button>
          </fieldset>
        ) : null}
      </div>
    </li>
  );
}

/** TRN-020 Engage builder: new (`type`) or edit (`activityId`). */
export function ActivityBuilder({ type, activityId }: { type?: ActivityType; activityId?: string }) {
  const { base } = useEngageScope();
  const existing = useApi<Activity>(activityId ? `engage/activities/${seg(activityId)}` : null);
  if (activityId) {
    const title = existing.data?.title?.trim() || "Edit activity";
    const crumbs: Crumb[] = [{ label: "Engage", href: base }];
    if (existing.data) crumbs.push({ label: title, href: `${base}/${seg(activityId)}` });
    crumbs.push({ label: "Edit" });
    const header = (
      <PageHeader
        breadcrumbs={crumbs}
        title={title}
        meta={existing.data ? <Badge tone="brand">{TYPE_LABEL[existing.data.activity_type]}</Badge> : null}
        description="Change the questions and settings. Finished runs keep their results."
      />
    );
    if (existing.loading && !existing.data)
      return (
        <>
          {header}
          <Loading label="Loading activity" />
        </>
      );
    if (existing.error || !existing.data)
      return (
        <>
          {header}
          <ErrorState error={existing.error} onRetry={() => void existing.reload()} />
        </>
      );
    return (
      <>
        {header}
        <BuilderForm key={existing.data.id} initial={fromActivity(existing.data)} activityId={activityId} />
      </>
    );
  }
  const t = type ?? "poll";
  return (
    <>
      <PageHeader
        breadcrumbs={[{ label: "Engage", href: base }, { label: "New activity" }]}
        title="New activity"
        meta={<Badge tone="brand">{TYPE_LABEL[t]}</Badge>}
        description={`Set up a ${TYPE_LABEL[t].toLowerCase()}, then launch it live from its control room.`}
      />
      <BuilderForm initial={initialState(t)} />
    </>
  );
}

function BuilderForm({ initial, activityId }: { initial: BuilderState; activityId?: string }) {
  const { base } = useEngageScope();
  const router = useRouter();
  const toast = useToast();
  const [s, setS] = useState<BuilderState>(initial);
  const [errors, setErrors] = useState<BuilderErrors>({});
  const [saving, setSaving] = useState(false);
  const [picker, setPicker] = useState(false);
  const trainer = useTrainerBatches();
  const batches = trainer.batches;
  const batchesLoading = trainer.loading;
  const batchesError = trainer.error;
  const type = s.activity_type;
  const quiz = type === "quiz";
  const set = <K extends keyof BuilderState>(k: K, v: BuilderState[K]) => setS((x) => ({ ...x, [k]: v }));

  // Platform-scope staff (Admin / Content manager) may create a platform activity with no batch.
  const grants = useMyGrants();
  const canPlatform = hasPlatformGrant(grants.data?.data);

  // Trainers default to the only batch they hold.
  useEffect(() => {
    if (!s.batch_id && !s.platform_wide && !canPlatform && batches?.length === 1) {
      const b = batches[0]!;
      setS((x) => ({ ...x, batch_id: b.id }));
    }
  }, [batches, s.batch_id, s.platform_wide, canPlatform]);

  const batchOptions = useMemo(() => {
    const opts = (batches ?? []).map((b) => ({ value: b.id, label: `${b.name} (${b.code})` }));
    if (s.batch_id && !opts.some((o) => o.value === s.batch_id)) opts.unshift({ value: s.batch_id, label: "Current batch" });
    if (canPlatform || s.platform_wide) opts.unshift({ value: PLATFORM_WIDE, label: "No batch: platform-wide (Admin / Content manager)" });
    return opts;
  }, [batches, s.batch_id, s.platform_wide, canPlatform]);

  const updateQ = (i: number, q: DraftQuestion) => setS((x) => ({ ...x, questions: x.questions.map((y, j) => (j === i ? q : y)) }));

  const importPicked = async (picked: PickedQuestion[]) => {
    if (picked.length === 0) return;
    try {
      const res = await api.post<BankImportResult>("engage/bank-import", { question_ids: picked.map((p) => p.question_id) });
      if (res.kind !== "ok") return;
      const drafts = res.data.data.filter((d) => KINDS_BY_TYPE[type].includes(d.kind));
      setS((x) => ({ ...x, questions: appendQuestions(x.questions, fromDrafts(drafts, type)) }));
      const skipped = res.data.skipped;
      toast.show({
        title: `Added ${drafts.length} question${drafts.length === 1 ? "" : "s"}`,
        description: skipped.length
          ? `Skipped ${skipped.length}: ${skipped.map((k) => SKIP_REASON[k.reason] ?? k.reason).join(", ")}.`
          : undefined,
        tone: skipped.length ? "warning" : "success",
      });
      setPicker(false);
    } catch (err) {
      toast.show({ ...errorText(err, "Couldn't import questions"), tone: "danger" });
    }
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const found = validateBuilder(s);
    setErrors(found);
    if (Object.keys(found).length) {
      toast.show({ title: "Check the highlighted fields", tone: "warning" });
      return;
    }
    setSaving(true);
    try {
      const body = toActivityIn(s);
      const res = activityId
        ? await api.put<Activity>(`engage/activities/${seg(activityId)}`, body)
        : await api.post<Activity>("engage/activities", body, { idempotencyKey: true });
      if (res.kind === "ok") {
        toast.show({ title: activityId ? "Activity saved" : "Activity created", tone: "success" });
        router.push(`${base}/${seg(res.data.id)}`);
      }
    } catch (err) {
      if (isApiError(err) && err.problem?.errors?.length) {
        const map: BuilderErrors = {};
        for (const x of err.problem.errors) if (!(x.field in map)) map[x.field] = x.message;
        setErrors(map);
      }
      toast.show({ ...errorText(err, "Couldn't save"), tone: "danger" });
    } finally {
      setSaving(false);
    }
  };

  const errorCount = Object.keys(errors).length;

  return (
    <form onSubmit={(e) => void submit(e)} noValidate className="space-y-6">
      <SectionNav
        sections={[
          { id: "activity-details", label: "Details" },
          { id: "activity-settings", label: "Settings" },
          { id: "activity-questions", label: `Questions (${s.questions.length})` },
        ]}
      />
      {errorCount ? (
        <p role="alert" className="rounded-md border border-danger-border bg-danger-subtle px-3 py-2 text-sm text-danger-fg">
          {errorCount === 1 ? "1 field needs attention." : `${errorCount} fields need attention.`}
          {errors.questions ? ` ${errors.questions}` : ""}
        </p>
      ) : null}

      <Card id="activity-details" title="Details" className="scroll-mt-20">
        <div className="grid gap-4 md:grid-cols-2">
          <FormField label="Title" error={errors.title} required>
            {(p) => <Input {...p} maxLength={200} value={s.title} onChange={(e) => set("title", e.target.value)} />}
          </FormField>
          <FormField label="Batch" error={errors.batch_id} hint={batchesError ? "Couldn't load your batches." : undefined} required>
            {(p) => (
              <Select
                {...p}
                value={s.platform_wide ? PLATFORM_WIDE : (s.batch_id ?? "")}
                disabled={batchesLoading && !batches}
                placeholder={batchesLoading ? "Loading batches…" : "Choose a batch"}
                options={batchOptions}
                onChange={(e) => {
                  const v = e.target.value;
                  setS((x) => (v === PLATFORM_WIDE ? { ...x, batch_id: null, platform_wide: true } : v ? { ...x, batch_id: v, platform_wide: false } : x));
                }}
              />
            )}
          </FormField>
          <div className="md:col-span-2">
            <FormField label="Description (optional)" hint="A short line participants will see" error={errors.description}>
              {(p) => <Input {...p} maxLength={500} value={s.description} onChange={(e) => set("description", e.target.value)} />}
            </FormField>
          </div>
        </div>
      </Card>

      <Card id="activity-settings" title="Settings" className="scroll-mt-20">
        <div className="grid gap-5 lg:grid-cols-2">
          <Segmented
            legend="How it runs"
            name="run_mode"
            value={s.run_mode}
            onChange={(v) => set("run_mode", v)}
            options={[
              { value: "instant", label: "Instant / live", hint: "You start and control it live" },
              { value: "scheduled", label: "Scheduled", hint: "Opens and closes at set times" },
            ]}
          />
          <Segmented
            legend="Who can join"
            name="audience"
            value={s.audience}
            onChange={(v) => set("audience", v)}
            options={[
              { value: "members", label: "Members only", hint: "Members of the batch" },
              { value: "public", label: "Anyone with a Tech Drona account", hint: "Join by link or QR code" },
            ]}
          />
          {s.run_mode === "scheduled" ? (
            <div className="grid gap-3 sm:grid-cols-2 lg:col-span-2">
              <FormField label="Opens at" error={errors.opens_at} required>
                {(p) => <Input {...p} type="datetime-local" value={s.opens_at} onChange={(e) => set("opens_at", e.target.value)} />}
              </FormField>
              <FormField label="Closes at" error={errors.closes_at} required>
                {(p) => <Input {...p} type="datetime-local" value={s.closes_at} onChange={(e) => set("closes_at", e.target.value)} />}
              </FormField>
            </div>
          ) : null}
          <Segmented
            legend="Identity"
            name="identity"
            value={s.identity_mode}
            onChange={(v) => set("identity_mode", v)}
            options={[
              { value: "named", label: "Named", hint: "Names appear in results" },
              { value: "anonymous", label: "Anonymous", hint: "Responses show no names" },
            ]}
          />
          <Segmented
            legend="Results"
            name="results"
            value={s.results_mode}
            onChange={(v) => set("results_mode", v)}
            options={[
              { value: "live", label: "Live", hint: "Shown as answers arrive" },
              { value: "on_publish", label: "On publish", hint: "Hidden until you publish" },
            ]}
          />
          <Segmented
            legend="Questions"
            name="pacing"
            value={s.pacing}
            onChange={(v) => set("pacing", v)}
            options={[
              { value: "all_at_once", label: "All at once", hint: "Every question is shown together" },
              { value: "one_by_one", label: "One by one", hint: "You move through them live" },
            ]}
          />
          {quiz ? (
            <Segmented
              legend="Winner rule"
              name="winner"
              value={s.winner_rule}
              onChange={(v) => set("winner_rule", v)}
              options={[
                { value: "fastest_first", label: "Fastest first", hint: "First correct answer wins each question" },
                { value: "all_correct", label: "All correct", hint: "Most correct answers wins" },
              ]}
            />
          ) : null}
          <FormField label="Participant limit (optional)" error={errors.participant_limit}>
            {(p) => (
              <Input
                {...p}
                type="number"
                inputMode="numeric"
                min={1}
                max={10000}
                placeholder="Unlimited"
                value={s.participant_limit}
                onChange={(e) => set("participant_limit", e.target.value)}
                className="sm:w-48"
              />
            )}
          </FormField>
        </div>
      </Card>

      <Card
        id="activity-questions"
        className="scroll-mt-20"
        title="Questions"
        actions={
          type === "quiz" || type === "poll" || type === "survey" ? (
            <Button size="sm" variant="secondary" onClick={() => setPicker(true)}>
              Add from question bank
            </Button>
          ) : undefined
        }
      >
        <ol className="space-y-4">
          {s.questions.map((q, i) => (
            <QuestionEditor
              key={q.key}
              index={i}
              count={s.questions.length}
              question={q}
              type={type}
              errors={errors}
              onChange={(nq) => updateQ(i, nq)}
              onMove={(d) => setS((x) => ({ ...x, questions: move(x.questions, i, d) }))}
              onRemove={() => setS((x) => ({ ...x, questions: x.questions.filter((_, j) => j !== i) }))}
            />
          ))}
        </ol>
        <Button className="mt-4" variant="secondary" disabled={s.questions.length >= 50} onClick={() => set("questions", [...s.questions, blankQuestion(type)])}>
          + Add question
        </Button>
      </Card>

      <StickyActionBar
        status={
          errorCount ? (
            <span className="font-medium text-danger-fg">{errorCount === 1 ? "1 field needs attention." : `${errorCount} fields need attention.`}</span>
          ) : (
            <span className="text-fg-muted">
              {TYPE_LABEL[type]} · {s.questions.length} {s.questions.length === 1 ? "question" : "questions"}
            </span>
          )
        }
      >
        <Button variant="secondary" onClick={() => router.push(activityId ? `${base}/${seg(activityId)}` : base)}>
          Cancel
        </Button>
        <Button type="submit" loading={saving}>
          Save {TYPE_LABEL[type].toLowerCase()}
        </Button>
      </StickyActionBar>

      <QuestionBankPicker
        open={picker}
        onClose={() => setPicker(false)}
        onPick={importPicked}
        allowedTypes={["mcq_single", "mcq_multi"]}
        title="Add from question bank"
        confirmLabel="Add questions"
        max={Math.max(1, 50 - s.questions.length)}
        excludeQuestionIds={s.questions.map((q) => q.source_question_id).filter((x): x is string => !!x)}
        description="Multiple-choice questions are copied into this activity."
      />
    </form>
  );
}
