import { api, type ApiResult } from "@/lib/api/client";
import { uuid7 } from "@/lib/ids/uuid7";
import type {
  Difficulty,
  MasteryResponse,
  PracticeAnswerBody,
  PracticeFeedback,
  PracticeSession,
  PracticeStartBody,
  PracticeSummary,
  QuestionReportBody,
  QuestionReportOut,
  RecommendationsResponse,
  ReviewQuestion,
  RevealResponse,
  SubjectsResponse,
  TaxonomyNode,
} from "./types";

const enc = encodeURIComponent;

function ok<T>(r: ApiResult<T>): T {
  if (r.kind !== "ok") throw new Error("Unexpected approval_pending response");
  return r.data;
}

/** UI difficulty → PracticeStart difficulty range (backend difficulty is 1..5). */
export function difficultyRange(d: Difficulty | null | undefined): Pick<PracticeStartBody, "difficulty_min" | "difficulty_max"> {
  if (d === "easy") return { difficulty_min: 1, difficulty_max: 2 };
  if (d === "medium") return { difficulty_min: 3, difficulty_max: 3 };
  if (d === "hard") return { difficulty_min: 4, difficulty_max: 5 };
  return {};
}

/** Flatten the subject tree into topic id → node (for naming topic ids from other endpoints). */
export function indexTopics(nodes: TaxonomyNode[], out = new Map<string, TaxonomyNode>()): Map<string, TaxonomyNode> {
  for (const n of nodes) {
    out.set(n.id, n);
    indexTopics(n.children ?? [], out);
  }
  return out;
}

export const practiceApi = {
  subjects: () => api.get<SubjectsResponse>("placement/subjects").then((r) => r.items),
  /** PLC-19: returns the full session state (201). */
  startSession: async (body: PracticeStartBody, key: string = uuid7()) =>
    ok(await api.post<PracticeSession>("practice/sessions", body, { idempotencyKey: key })),
  session: (id: string) => api.get<PracticeSession>(`practice/sessions/${enc(id)}`),
  answer: async (sessionId: string, body: PracticeAnswerBody, key: string = uuid7()) =>
    ok(await api.post<PracticeFeedback>(`practice/sessions/${enc(sessionId)}/answers`, body, { idempotencyKey: key })),
  reveal: async (sessionId: string, qvid: string, kind: "hint" | "solution") =>
    ok(await api.post<RevealResponse>(`practice/sessions/${enc(sessionId)}/questions/${enc(qvid)}/reveal`, { kind })),
  complete: async (sessionId: string) => ok(await api.post<PracticeSummary>(`practice/sessions/${enc(sessionId)}/complete`, {})),
  /** PLC-24: not paginated (latest 50). */
  review: () => api.get<{ items: ReviewQuestion[] }>("me/practice/review").then((r) => r.items),
  mastery: () => api.get<MasteryResponse>("me/mastery"),
  recommendations: () => api.get<RecommendationsResponse>("me/recommendations"),
  dismissRecommendation: async (id: string) => ok(await api.post<unknown>(`me/recommendations/${enc(id)}/dismiss`, {})),
  /** PLC-33: the path id may be the question_version_id served in a practice session. */
  reportQuestion: async (questionId: string, body: QuestionReportBody, key: string = uuid7()) =>
    ok(await api.post<QuestionReportOut>(`questions/${enc(questionId)}/reports`, body, { idempotencyKey: key })),
};
