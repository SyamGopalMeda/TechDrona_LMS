/**
 * Activity builder state ↔ ActivityIn body (verified: apps/api/app/modules/engage/schemas.py
 * ActivityIn, service.py validate_activity). Client-side checks mirror the server so that most
 * mistakes are caught before saving; the server remains authoritative.
 */
import { KINDS_BY_TYPE } from "./labels";
import type {
  Activity,
  ActivityIn,
  ActivityType,
  Audience,
  IdentityMode,
  Pacing,
  QuestionDraft,
  QuestionKind,
  ResultsMode,
  RunMode,
  WinnerRule,
} from "./types";

export interface DraftOption {
  key: string;
  id?: string;
  text: string;
  is_correct: boolean;
}

export interface DraftQuestion {
  key: string;
  kind: QuestionKind;
  prompt: string;
  options: DraftOption[];
  max_words: number | null;
  source_question_id?: string | null;
  source_version_id?: string | null;
  /** From a bank import without access to the answer key. */
  key_missing?: boolean;
}

export interface BuilderState {
  activity_type: ActivityType;
  title: string;
  description: string;
  batch_id: string | null;
  /** No batch: a platform activity (Admin / Content manager only; the api enforces it). */
  platform_wide: boolean;
  run_mode: RunMode;
  audience: Audience;
  identity_mode: IdentityMode;
  results_mode: ResultsMode;
  pacing: Pacing;
  winner_rule: WinnerRule;
  /** Raw input; empty = unlimited. */
  participant_limit: string;
  /** `datetime-local` values (local time). */
  opens_at: string;
  closes_at: string;
  questions: DraftQuestion[];
}

let counter = 0;
export const newKey = () => `k${Date.now().toString(36)}${(counter++).toString(36)}`;

export const CHOICE: QuestionKind[] = ["single_choice", "multi_choice"];
export const isChoice = (k: QuestionKind) => CHOICE.includes(k);

export function blankOption(): DraftOption {
  return { key: newKey(), text: "", is_correct: false };
}

export function blankQuestion(type: ActivityType, kind: QuestionKind = KINDS_BY_TYPE[type][0]!): DraftQuestion {
  return {
    key: newKey(),
    kind,
    prompt: "",
    options: isChoice(kind) ? [blankOption(), blankOption()] : [],
    max_words: kind === "word" ? 1 : null,
  };
}

export function initialState(type: ActivityType): BuilderState {
  return {
    activity_type: type,
    title: "",
    description: "",
    batch_id: null,
    platform_wide: false,
    run_mode: "instant",
    audience: "members",
    identity_mode: "named",
    results_mode: type === "quiz" ? "on_publish" : "live",
    pacing: type === "quiz" ? "one_by_one" : "all_at_once",
    winner_rule: "fastest_first",
    participant_limit: "",
    opens_at: "",
    closes_at: "",
    questions: [blankQuestion(type)],
  };
}

/** Change a question's kind, keeping what still applies. */
export function withKind(q: DraftQuestion, kind: QuestionKind): DraftQuestion {
  let options = q.options;
  if (isChoice(kind)) {
    if (options.length < 2) options = [...options, ...Array.from({ length: 2 - options.length }, blankOption)];
    if (kind === "single_choice") {
      let seen = false;
      options = options.map((o) => {
        const keep = o.is_correct && !seen;
        if (o.is_correct) seen = true;
        return { ...o, is_correct: keep };
      });
    }
  } else options = [];
  return { ...q, kind, options, max_words: kind === "word" ? (q.max_words ?? 1) : null };
}

/** Tick an option as correct (single choice: exclusive). */
export function toggleCorrect(q: DraftQuestion, optionKey: string): DraftQuestion {
  return {
    ...q,
    options: q.options.map((o) =>
      q.kind === "single_choice"
        ? { ...o, is_correct: o.key === optionKey }
        : o.key === optionKey
          ? { ...o, is_correct: !o.is_correct }
          : o,
    ),
  };
}

export function move<T>(list: T[], index: number, delta: number): T[] {
  const j = index + delta;
  if (j < 0 || j >= list.length) return list;
  const next = [...list];
  [next[index], next[j]] = [next[j]!, next[index]!];
  return next;
}

/* ------------------------------------------------------------------ dates */

/** ISO → `datetime-local` value in the browser's time zone. */
export function toLocalInput(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

/** `datetime-local` → ISO (UTC) or null. */
export function fromLocalInput(v: string): string | null {
  if (!v) return null;
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

/* ------------------------------------------------------------------ validation */

export type BuilderErrors = Record<string, string>;

export function validateBuilder(s: BuilderState, now: Date = new Date()): BuilderErrors {
  const e: BuilderErrors = {};
  if (!s.title.trim()) e.title = "Give the activity a title.";
  else if (s.title.trim().length > 200) e.title = "Keep the title under 200 characters.";
  if (s.description.length > 500) e.description = "Keep the description under 500 characters.";
  if (!s.batch_id && !s.platform_wide) e.batch_id = "Choose the batch this activity belongs to.";
  if (s.participant_limit.trim()) {
    const n = Number(s.participant_limit);
    if (!Number.isInteger(n) || n < 1 || n > 10000) e.participant_limit = "Enter a whole number from 1 to 10,000, or leave it empty.";
  }
  if (s.run_mode === "scheduled") {
    const o = fromLocalInput(s.opens_at);
    const c = fromLocalInput(s.closes_at);
    if (!o) e.opens_at = "Choose when it opens.";
    if (!c) e.closes_at = "Choose when it closes.";
    if (o && c && new Date(c) <= new Date(o)) e.closes_at = "Closing time must be after the opening time.";
    else if (c && new Date(c) <= now) e.closes_at = "Closing time must be in the future.";
  }
  if (s.questions.length === 0) e.questions = "Add at least one question.";
  if (s.questions.length > 50) e.questions = "An activity can have at most 50 questions.";
  const allowed = KINDS_BY_TYPE[s.activity_type];
  s.questions.forEach((q, i) => {
    const f = `questions[${i}]`;
    if (!q.prompt.trim()) e[`${f}.prompt`] = "Write the question.";
    if (!allowed.includes(q.kind)) e[`${f}.kind`] = "This kind isn't allowed here.";
    if (isChoice(q.kind)) {
      const filled = q.options.filter((o) => o.text.trim());
      if (q.options.length < 2) e[`${f}.options`] = "Add at least 2 options.";
      else if (filled.length !== q.options.length) e[`${f}.options`] = "Fill in every option or remove the empty ones.";
      else if (q.options.length > 10) e[`${f}.options`] = "A question can have at most 10 options.";
      else if (s.activity_type === "quiz") {
        const n = q.options.filter((o) => o.is_correct).length;
        if (n === 0) e[`${f}.options`] = "Tick the correct answer.";
        else if (q.kind === "single_choice" && n > 1) e[`${f}.options`] = "Tick only one correct answer.";
      }
    }
    if (q.kind === "word" && (q.max_words == null || q.max_words < 1 || q.max_words > 5)) {
      e[`${f}.max_words`] = "Choose 1 to 5 words.";
    }
  });
  return e;
}

/* ------------------------------------------------------------------ serialization */

export function toActivityIn(s: BuilderState): ActivityIn {
  const quiz = s.activity_type === "quiz";
  const scheduled = s.run_mode === "scheduled";
  const limit = s.participant_limit.trim();
  return {
    activity_type: s.activity_type,
    title: s.title.trim(),
    description: s.description.trim() || null,
    batch_id: s.platform_wide ? null : s.batch_id,
    run_mode: s.run_mode,
    audience: s.audience,
    identity_mode: s.identity_mode,
    results_mode: s.results_mode,
    pacing: s.pacing,
    winner_rule: quiz ? s.winner_rule : null,
    participant_limit: limit ? Number(limit) : null,
    opens_at: scheduled ? fromLocalInput(s.opens_at) : null,
    closes_at: scheduled ? fromLocalInput(s.closes_at) : null,
    questions: s.questions.map((q) => ({
      kind: q.kind,
      prompt: q.prompt.trim(),
      options: isChoice(q.kind)
        ? q.options.map((o) => ({
            ...(o.id ? { id: o.id } : {}),
            text: o.text.trim(),
            is_correct: quiz ? o.is_correct : false,
          }))
        : [],
      max_words: q.kind === "word" ? q.max_words : null,
      source_question_id: q.source_question_id ?? null,
      source_version_id: q.source_version_id ?? null,
    })),
  };
}

export function fromActivity(a: Activity): BuilderState {
  return {
    activity_type: a.activity_type,
    title: a.title,
    description: a.description ?? "",
    batch_id: a.batch_id,
    platform_wide: !a.batch_id,
    run_mode: a.run_mode,
    audience: a.audience,
    identity_mode: a.identity_mode,
    results_mode: a.results_mode,
    pacing: a.pacing,
    winner_rule: a.winner_rule ?? "fastest_first",
    participant_limit: a.participant_limit != null ? String(a.participant_limit) : "",
    opens_at: toLocalInput(a.opens_at),
    closes_at: toLocalInput(a.closes_at),
    questions: [...a.questions]
      .sort((x, y) => x.position - y.position)
      .map((q) => ({
        key: newKey(),
        kind: q.kind,
        prompt: q.prompt,
        options: q.options.map((o) => ({ key: newKey(), id: o.id, text: o.text, is_correct: o.is_correct })),
        max_words: q.max_words,
        source_question_id: q.source_question_id,
      })),
  };
}

/** Bank-import drafts → builder questions (polls/surveys drop the correct flags). */
export function fromDrafts(drafts: QuestionDraft[], type: ActivityType): DraftQuestion[] {
  return drafts.map((d) => ({
    key: newKey(),
    kind: d.kind,
    prompt: d.prompt,
    options: d.options.map((o) => ({ key: newKey(), text: o.text, is_correct: type === "quiz" && o.is_correct })),
    max_words: d.max_words,
    source_question_id: d.source_question_id,
    source_version_id: d.source_version_id,
    key_missing: type === "quiz" && !d.key_copied,
  }));
}

/** Replace a blank starter question instead of leaving it above imported ones. */
export function appendQuestions(list: DraftQuestion[], add: DraftQuestion[]): DraftQuestion[] {
  const isBlank = (q: DraftQuestion) => !q.prompt.trim() && q.options.every((o) => !o.text.trim());
  const base = list.length === 1 && isBlank(list[0]!) ? [] : list;
  return [...base, ...add].slice(0, 50);
}
