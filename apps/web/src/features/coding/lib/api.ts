import { api, buildUrl, readCsrfToken, refreshCsrfToken } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { isProblemDetails, type ProblemDetails } from "@/lib/api/problem";
import { uuid7 } from "@/lib/ids/uuid7";
import type { CodingDraft, CursorPage, Language, ProblemDetail, ProblemListItem, RunBody, SubmitBody, Submission, SubmissionAccepted } from "./types";

const enc = encodeURIComponent;

/** 429 rate_limited / 409 judge_queue_full carrying the server's Retry-After (seconds). */
export class RetryAfterError extends ApiError {
  readonly retryAfterSeconds: number;
  constructor(status: number, problem: ProblemDetails | null, requestId: string | null, retryAfterSeconds: number) {
    super(status, problem, requestId);
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

/** Parse `Retry-After` (delta-seconds or HTTP-date); then a problem member; then `fallback`. */
export function parseRetryAfter(header: string | null, problem: ProblemDetails | null, nowMs: number = Date.now(), fallback = 30): number {
  if (header) {
    const n = Number(header.trim());
    if (header.trim() !== "" && Number.isFinite(n) && n >= 0) return Math.ceil(n);
    const at = Date.parse(header);
    if (Number.isFinite(at)) return Math.max(0, Math.ceil((at - nowMs) / 1000));
  }
  const fromBody = problem?.retry_after ?? problem?.retry_after_seconds;
  if (typeof fromBody === "number" && fromBody >= 0) return Math.ceil(fromBody);
  return fallback;
}

/**
 * POST for Run/Submit. The shared client does not expose response headers on errors, and
 * the judge endpoints need `Retry-After` (FR-COD-005), so these two calls use a thin fetch
 * with the same CSRF double-submit and Idempotency-Key conventions as `@/lib/api/client`.
 */
async function judgePost<T>(path: string, body: unknown, idempotencyKey: string, fetchImpl?: typeof fetch): Promise<T> {
  const doFetch = fetchImpl ?? globalThis.fetch;
  let csrfRetried = false;
  for (;;) {
    const token = readCsrfToken() ?? (await refreshCsrfToken());
    let res: Response;
    try {
      res = await doFetch(buildUrl(path), {
        method: "POST",
        headers: {
          accept: "application/json",
          "content-type": "application/json",
          "idempotency-key": idempotencyKey,
          ...(token ? { "x-csrf-token": token } : {}),
        },
        body: JSON.stringify(body),
        credentials: "same-origin",
        cache: "no-store",
      });
    } catch {
      throw new ApiError(0, null, null);
    }
    const requestId = res.headers.get("x-request-id");
    if (res.ok) return (await res.json()) as T;
    let problem: ProblemDetails | null = null;
    try {
      const j: unknown = await res.json();
      problem = isProblemDetails(j) ? j : null;
    } catch {
      problem = null;
    }
    if (problem?.code === "csrf_failed" && !csrfRetried) {
      csrfRetried = true;
      await refreshCsrfToken();
      continue;
    }
    if (res.status === 429 || problem?.code === "judge_queue_full" || problem?.code === "rate_limited") {
      throw new RetryAfterError(res.status, problem, requestId, parseRetryAfter(res.headers.get("retry-after"), problem));
    }
    if (problem?.code === "account_restricted" && typeof window !== "undefined") {
      const qs = new URLSearchParams();
      if (problem.case_ref) qs.set("case_ref", problem.case_ref);
      if (problem.level !== undefined) qs.set("level", String(problem.level));
      window.location.assign(`/account/restricted${qs.size ? `?${qs.toString()}` : ""}`);
    }
    throw new ApiError(res.status, problem, requestId);
  }
}

export const codingApi = {
  /** COD-01 → {data} */
  languages: () => api.get<{ data: Language[] }>("coding/languages").then((r) => r.data),
  /** COD-02: only `difficulty` (1..5) filters server-side; `{data, meta}` envelope. */
  problems: (q: { difficulty?: number; cursor?: string }) =>
    api.get<CursorPage<ProblemListItem>>("coding/problems", { query: { ...q, limit: 25 } }),
  /**
   * COD-03 by slug or problem id (w2a: the route accepts both). With `attemptId` the learner's
   * in-progress attempt that contains the problem grants access instead of an entitlement.
   */
  problem: (slugOrId: string, attemptId?: string | null) =>
    api.get<ProblemDetail>(`coding/problems/${enc(slugOrId)}`, { query: attemptId ? { attempt_id: attemptId } : undefined }),
  /** COD-05: the caller's own draft for a language; `null` when none was saved (404). */
  getDraft: async (problemId: string, languageKey: string, attemptId?: string | null): Promise<CodingDraft | null> => {
    try {
      return await api.get<CodingDraft>(`coding/problems/${enc(problemId)}/drafts/${enc(languageKey)}`, {
        query: attemptId ? { attempt_id: attemptId } : undefined,
      });
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) return null;
      throw e;
    }
  },
  /** COD-04: autosave (owner-only, ≤ 64 KiB, 20/min server-side). */
  saveDraft: async (problemId: string, languageKey: string, sourceCode: string, attemptId?: string | null): Promise<CodingDraft> => {
    const qs = attemptId ? `?attempt_id=${enc(attemptId)}` : "";
    const r = await api.put<CodingDraft>(`coding/problems/${enc(problemId)}/drafts/${enc(languageKey)}${qs}`, { source_code: sourceCode });
    if (r.kind !== "ok") throw new Error("Unexpected approval_pending response for a draft save");
    return r.data;
  },
  run: (problemId: string, body: RunBody, key: string = uuid7(), fetchImpl?: typeof fetch) =>
    judgePost<SubmissionAccepted>(`coding/problems/${enc(problemId)}/run`, body, key, fetchImpl),
  submit: (problemId: string, body: SubmitBody, key: string = uuid7(), fetchImpl?: typeof fetch) =>
    judgePost<SubmissionAccepted>(`coding/problems/${enc(problemId)}/submit`, body, key, fetchImpl),
  submission: (id: string) => api.get<Submission>(`coding/submissions/${enc(id)}`),
  history: (problemId: string, cursor?: string) =>
    api.get<CursorPage<Submission>>("me/coding/submissions", { query: { problem_id: problemId, cursor, limit: 25 } }),
};

export function isTerminal(s: Pick<Submission, "status">): boolean {
  // verified: coding/worker.py + service.py statuses queued → running → completed | rejected
  return s.status === "completed" || s.status === "rejected" || s.status === "failed" || s.status === "error";
}

/** Poll COD-08 until terminal: 1 s, backing off to 3 s (60/min limit). */
export async function pollSubmission(
  id: string,
  onUpdate: (s: Submission) => void,
  opts: { signal?: AbortSignal; get?: (id: string) => Promise<Submission>; sleep?: (ms: number) => Promise<void>; maxMs?: number } = {},
): Promise<Submission> {
  const get = opts.get ?? codingApi.submission;
  const sleep = opts.sleep ?? ((ms: number) => new Promise<void>((r) => setTimeout(r, ms)));
  const started = Date.now();
  let delay = 1000;
  for (;;) {
    if (opts.signal?.aborted) throw new DOMException("Aborted", "AbortError");
    const s = await get(id);
    onUpdate(s);
    if (isTerminal(s)) return s;
    if (opts.maxMs && Date.now() - started > opts.maxMs) return s;
    await sleep(delay);
    delay = Math.min(3000, Math.round(delay * 1.5));
  }
}

/** Monaco language id from a judge language key (e.g. cpp17 → cpp, python3 → python). */
export function monacoLanguage(key: string): string {
  const k = key.toLowerCase();
  if (k.startsWith("py")) return "python";
  if (k.startsWith("cpp") || k.startsWith("c++")) return "cpp";
  if (k === "c" || k.startsWith("c1") || k.startsWith("c9")) return "c";
  if (k.startsWith("java") && !k.startsWith("javascript")) return "java";
  if (k.startsWith("js") || k.startsWith("javascript") || k.startsWith("node")) return "javascript";
  if (k.startsWith("ts") || k.startsWith("typescript")) return "typescript";
  if (k.startsWith("go")) return "go";
  if (k.startsWith("rust")) return "rust";
  if (k.startsWith("csharp") || k.startsWith("cs")) return "csharp";
  if (k.startsWith("kotlin")) return "kotlin";
  return "plaintext";
}

/** Problem difficulty (1..5) as a label. */
export function difficultyLabel(d: number): string {
  if (d <= 2) return "Easy";
  if (d === 3) return "Medium";
  return "Hard";
}
