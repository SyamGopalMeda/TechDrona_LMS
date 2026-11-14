import { api, type ApiResult } from "@/lib/api/client";
import type {
  AIGradingQueued,
  AllocationIn,
  AllocationOut,
  AllocationPatchIn,
  AssignmentCreateIn,
  AssignmentOut,
  AssignmentPatchIn,
  EvaluationOut,
  FinalizeIn,
  ItemResponse,
  ItemType,
  LearnerSubmissionOut,
  RegradeOut,
  ResultOut,
  ReviewOut,
  StructureIn,
  StructureOut,
  TutorIn,
  TutorOut, TutorTurn,
  WorkspaceOut,
  GradingEngine,
} from "./types";

const enc = encodeURIComponent;

/** Unwrap a write result; structured-assignment endpoints never answer 202 approval_pending. */
export function data<T>(r: ApiResult<T>): T {
  if (r.kind !== "ok") throw new Error("This change needs an approval before it takes effect.");
  return r.data;
}

/** Staff endpoints (assignment manager, allocations, evaluation). */
export const staffApi = {
  create: async (body: AssignmentCreateIn) => data(await api.post<AssignmentOut>("assignments", body, { idempotencyKey: true })),
  patch: async (id: string, body: AssignmentPatchIn) => data(await api.patch<AssignmentOut>(`assignments/${enc(id)}`, body)),
  clone: async (id: string) => data(await api.post<AssignmentOut>(`assignments/${enc(id)}/clone`, undefined, { idempotencyKey: true })),
  structure: (id: string) => api.get<StructureOut>(`assignments/${enc(id)}/structure`),
  saveStructure: async (id: string, body: StructureIn) => data(await api.put<StructureOut>(`assignments/${enc(id)}/structure`, body)),
  allocate: async (id: string, body: AllocationIn) =>
    data(await api.post<AllocationOut>(`assignments/${enc(id)}/allocations`, body, { idempotencyKey: true })),
  allocations: (id: string) => api.get<{ data: AllocationOut[] }>(`assignments/${enc(id)}/allocations`),
  patchAllocation: async (id: string, body: AllocationPatchIn) => data(await api.patch<AllocationOut>(`assignment-allocations/${enc(id)}`, body)),
  extend: async (id: string, body: { user_id: string; until: string; reason: string }) =>
    data(await api.post<AllocationOut>(`assignment-allocations/${enc(id)}/extensions`, body, { idempotencyKey: true })),
  evaluation: (id: string) => api.get<EvaluationOut>(`assignments/${enc(id)}/evaluation`),
  runAIGrading: async (id: string, submissionIds?: string[]) =>
    data(await api.post<AIGradingQueued>(`assignments/${enc(id)}/ai-grading`, submissionIds ? { submission_ids: submissionIds } : {})),
  releaseGrades: async (id: string) =>
    data(await api.post<AssignmentOut & { unfinalized_count: number }>(`assignments/${enc(id)}/release-grades`, undefined, { idempotencyKey: true })),
  review: (submissionId: string) => api.get<ReviewOut>(`assignment-submissions/${enc(submissionId)}/review`),
  runSubmissionAIGrading: async (submissionId: string) =>
    data(await api.post<AIGradingQueued>(`assignment-submissions/${enc(submissionId)}/ai-grading`)),
  finalize: async (submissionId: string, body: FinalizeIn) => data(await api.post<ReviewOut>(`assignment-submissions/${enc(submissionId)}/finalize`, body)),
  fileUrl: (submissionId: string, index: number) =>
    api.get<{ url: string; filename?: string }>(`assignment-submissions/${enc(submissionId)}/files/${index}`),
  regrades: (id: string, status: "open" | "resolved" | "rejected" = "open") =>
    api.get<{ data: RegradeOut[] }>(`assignments/${enc(id)}/regrade-requests`, { query: { status } }),
  resolveRegrade: async (id: string, body: { action: "resolve" | "reject"; note: string; reopen?: boolean }) =>
    data(await api.post<RegradeOut>(`assignment-regrade-requests/${enc(id)}/resolve`, body)),
};

/** Learner endpoints (workspace, tutor, result, regrade). */
export const learnerApi = {
  workspace: (id: string) => api.get<WorkspaceOut>(`me/assignments/${enc(id)}/workspace`),
  start: async (id: string) => data(await api.post<WorkspaceOut>(`me/assignments/${enc(id)}/workspace/start`, undefined, { idempotencyKey: true })),
  saveItem: async (id: string, itemId: string, response: ItemResponse) =>
    data(await api.put<{ item_id: string; saved_at: string }>(`me/assignments/${enc(id)}/workspace/items/${enc(itemId)}`, { response })),
  submit: async (id: string) =>
    data(await api.post<LearnerSubmissionOut>(`me/assignments/${enc(id)}/workspace/submit`, undefined, { idempotencyKey: true })),
  tutor: async (id: string, body: TutorIn) => data(await api.post<TutorOut>(`me/assignments/${enc(id)}/tutor`, body)),
  /** Server-side tutor history for one question (WS4; the learner's own turns, oldest first). */
  tutorHistory: async (id: string, itemId: string) =>
    (await api.get<{ data: TutorTurn[] }>(`me/assignments/${enc(id)}/tutor/history`, { query: { item_id: itemId } })).data ?? [],
  result: (id: string) => api.get<ResultOut>(`me/assignments/${enc(id)}/result`),
  requestRegrade: async (submissionId: string, body: { reason: string; item_id?: string }) =>
    data(await api.post<RegradeOut>(`me/assignment-submissions/${enc(submissionId)}/regrade-requests`, body, { idempotencyKey: true })),
};

/* ------------------------------------------------------------------- helpers */

export function isStructured(a: { submission_type?: string | null; structured?: boolean | null } | null | undefined): boolean {
  return !!a && (a.structured === true || a.submission_type === "structured");
}

export const ITEM_TYPE_LABEL: Record<ItemType, string> = {
  mcq_single: "Single choice",
  mcq_multi: "Multiple choice",
  numeric: "Numeric",
  fill_blank: "Fill in the blank",
  coding: "Code",
  essay: "Essay",
  short_text: "Short answer",
  file: "File upload",
};

export function itemTypeLabel(t: string): string {
  return ITEM_TYPE_LABEL[t as ItemType] ?? t.replace(/_/g, " ");
}

export const ENGINES: { value: GradingEngine; label: string; description: string }[] = [
  { value: "pure_ai", label: "AI only", description: "AI suggests marks for every question; staff finalize." },
  { value: "ai_human", label: "AI + evaluator", description: "AI suggests, an evaluator reviews each answer." },
  { value: "pure_objective", label: "Rules only", description: "Auto-scores choice/numeric/code by rules; written answers are graded by hand." },
  { value: "adaptive", label: "Adaptive", description: "Rules for objective items, AI for the rest; low-confidence AI marks are flagged." },
  { value: "pure_manual", label: "Manual", description: "Evaluators grade everything." },
];

export function engineLabel(e: string | null | undefined): string {
  return ENGINES.find((x) => x.value === e)?.label ?? (e ? e.replace(/_/g, " ") : "—");
}

/** Plain text from bank stem HTML for compact rows (rendered as text, never as markup). */
export function stripHtml(html: string | null | undefined): string {
  return (html ?? "").replace(/<[^>]*>/g, " ").replace(/&nbsp;/g, " ").replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/\s+/g, " ").trim();
}

export function truncate(s: string, n = 120): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

/** RFC 3339 → `<input type="datetime-local">` value in the browser's local time. */
export function isoToLocalInput(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

/** `<input type="datetime-local">` value → RFC 3339 UTC, or null when empty/invalid. */
export function localInputToIso(v: string): string | null {
  if (!v) return null;
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

/** Compact countdown ("2d 4h", "23h 54m", "5m 12s"); "Time's up" at 0. */
export function formatCountdown(seconds: number): string {
  if (seconds <= 0) return "Time's up";
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m ${s}s`;
}

/** Marks as shown in the UI (no trailing ".0"). */
export function fmtMarks(n: number | null | undefined): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return "—";
  return String(Math.round(n * 100) / 100);
}
