import type { ActivityType, QuestionKind, RunSettings, RunStatus } from "./types";

export const TYPE_LABEL: Record<ActivityType, string> = {
  quiz: "Quiz",
  poll: "Poll",
  word_cloud: "Word cloud",
  survey: "Survey",
};

export const ACTIVITY_TYPES: ActivityType[] = ["quiz", "poll", "word_cloud", "survey"];

export function isActivityType(v: unknown): v is ActivityType {
  return typeof v === "string" && (ACTIVITY_TYPES as string[]).includes(v);
}

/** Question kinds each activity type allows. verified: schemas.py KINDS_BY_TYPE */
export const KINDS_BY_TYPE: Record<ActivityType, QuestionKind[]> = {
  quiz: ["single_choice", "multi_choice"],
  poll: ["single_choice", "multi_choice"],
  word_cloud: ["word"],
  survey: ["single_choice", "multi_choice", "text", "rating"],
};

export const KIND_LABEL: Record<QuestionKind, string> = {
  single_choice: "Single choice",
  multi_choice: "Multiple choice",
  word: "Word",
  text: "Short answer",
  rating: "Rating 1–5",
};

export const STATUS_LABEL: Record<RunStatus, string> = {
  scheduled: "Waiting to start",
  open: "Live",
  closed: "Closed",
  finalised: "Finalised",
};

export function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

/** "Public · Named · Fastest first" */
export function settingsSummary(s: Pick<RunSettings, "audience" | "identity_mode" | "winner_rule" | "run_mode">): string {
  const parts = [
    s.audience === "public" ? "Public" : "Members only",
    s.identity_mode === "anonymous" ? "Anonymous" : "Named",
  ];
  if (s.run_mode === "scheduled") parts.push("Scheduled");
  if (s.winner_rule === "fastest_first") parts.push("Fastest first");
  if (s.winner_rule === "all_correct") parts.push("All correct");
  return parts.join(" · ");
}

export function formatMs(ms: number): string {
  const s = ms / 1000;
  return s < 60 ? `${s.toFixed(1)}s` : `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
}

export function formatWhen(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}
