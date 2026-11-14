import { api, type ApiResult } from "@/lib/api/client";
import type { Body } from "@/lib/api-types";
import { uuid7 } from "@/lib/ids/uuid7";
import type {
  AttemptPayload,
  AttemptResult,
  AutosaveRequest,
  AutosaveResponse,
  AutosaveItem,
  MyAttempt,
  MyTestsResponse,
  RebindOtpResponse,
  ReviewResponse,
  SubmitResponse,
  TestDetail,
  TestRowData,
  TimeResponse,
} from "./types";

/** Endpoint wrappers for ASM/ATT (app/modules/assessments/router.py). Paths are relative to /api/v1. */

function ok<T>(r: ApiResult<T>): T {
  if (r.kind !== "ok") throw new Error("Unexpected approval_pending response");
  return r.data;
}

const enc = encodeURIComponent;

/** Upper bound on ATT-13 pages fetched for one list (100 per page). */
const MAX_ATTEMPT_PAGES = 20;

/**
 * ATT-13 is cursor-paginated with the §1.10 envelope (`page.next_cursor`, BE-21). Follows the
 * cursor so a learner with more than one page of attempts still sees their latest results.
 */
async function allMyAttempts(): Promise<MyAttempt[]> {
  const out: MyAttempt[] = [];
  let cursor: string | undefined;
  for (let i = 0; i < MAX_ATTEMPT_PAGES; i += 1) {
    const res = await api.get<{ items: MyAttempt[]; page?: { next_cursor: string | null; has_more?: boolean } }>("me/attempts", {
      query: cursor ? { cursor, limit: 100 } : { limit: 100 },
    });
    out.push(...res.items);
    const next = res.page?.next_cursor;
    if (!next) break;
    cursor = next;
  }
  return out;
}
const FINISHED = new Set(["submitted", "auto_submitted", "grading", "awaiting_manual", "graded", "invalidated"]);

export const assessmentApi = {
  /** ASM-01 (not paginated, no server-side filter) joined with ATT-13 for each test's latest finished attempt. */
  listTests: async (): Promise<TestRowData[]> => {
    const [tests, attempts] = await Promise.all([api.get<MyTestsResponse>("me/tests"), allMyAttempts()]);
    const latest = new Map<string, MyAttempt>();
    for (const a of attempts) {
      // ATT-13 is ordered newest first.
      if (FINISHED.has(a.status) && !latest.has(a.test_id)) latest.set(a.test_id, a);
    }
    return tests.items.map((t) => ({ ...t, last_attempt: latest.get(t.test_id) ?? null }));
  },
  getTest: (testId: string) => api.get<TestDetail>(`tests/${enc(testId)}`),

  /** ATT-01. Pass a stable key per user intent so a retried click replays instead of duplicating. */
  start: async (
    body: Pick<Body<"attempts", "post">, "test_id" | "test_assignment_id" | "integrity_consent"> & Partial<Pick<Body<"attempts", "post">, "instructions_agreed">>,
    idempotencyKey: string = uuid7(),
  ) => {
    // instructions_agreed: exam protocol (server: AttemptStart); the timer starts at this call.
    const req: Body<"attempts", "post"> = {
      ...body,
      instructions_agreed: body.instructions_agreed ?? false,
      client_info: {
        fullscreen_supported: typeof document !== "undefined" && !!document.documentElement.requestFullscreen,
        tz_offset_min: -new Date().getTimezoneOffset(),
      },
    };
    return ok(await api.post<AttemptPayload>("attempts", req, { idempotencyKey }));
  },
  state: (attemptId: string) => api.get<AttemptPayload>(`attempts/${enc(attemptId)}/state`),
  resume: async (attemptId: string) => ok(await api.post<AttemptPayload>(`attempts/${enc(attemptId)}/resume`, {})),
  sendRebindOtp: async (attemptId: string) => ok(await api.post<RebindOtpResponse>(`attempts/${enc(attemptId)}/rebind/otp`, {})),
  rebind: async (attemptId: string, otpCode: string | null, idempotencyKey: string = uuid7()) => {
    const req: Body<"attempts/{attempt_id}/rebind", "post"> = { confirm: true, otp_code: otpCode };
    return ok(await api.post<AttemptPayload>(`attempts/${enc(attemptId)}/rebind`, req, { idempotencyKey }));
  },
  autosave: async (attemptId: string, body: AutosaveRequest) => ok(await api.post<AutosaveResponse>(`attempts/${enc(attemptId)}/autosave`, body)),
  time: (attemptId: string) => api.get<TimeResponse>(`attempts/${enc(attemptId)}/time`),
  /** ATT-09: returns the refreshed state payload. */
  submitSection: async (attemptId: string, sectionId: string) =>
    ok(await api.post<AttemptPayload>(`attempts/${enc(attemptId)}/sections/${enc(sectionId)}/submit`, {})),
  /** ATT-08: returns the refreshed state payload. */
  enterSection: async (attemptId: string, sectionId: string) =>
    ok(await api.post<AttemptPayload>(`attempts/${enc(attemptId)}/sections/${enc(sectionId)}/enter`, {})),
  submit: async (attemptId: string, finalItems: AutosaveItem[], confirmUnanswered: number, idempotencyKey: string = uuid7()) =>
    ok(
      await api.post<SubmitResponse>(
        `attempts/${enc(attemptId)}/submit`,
        { final_items: finalItems, confirm_unanswered: confirmUnanswered },
        { idempotencyKey },
      ),
    ),
  result: (attemptId: string) => api.get<AttemptResult>(`attempts/${enc(attemptId)}/result`),
  review: (attemptId: string) => api.get<ReviewResponse>(`attempts/${enc(attemptId)}/review`),
};
