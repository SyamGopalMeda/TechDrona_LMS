import { api, type RequestOptions } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { BookingStatus, ScoreKey, SessionKind } from "./types";

type SendOpts = Omit<RequestOptions, "method" | "body">;

/** POST/PUT/PATCH/DELETE that returns the body (mentoring has no dual-control actions). */
export async function send<T>(method: "post" | "put" | "patch" | "delete", path: string, body?: unknown, opts: SendOpts = {}): Promise<T> {
  const res = method === "delete" ? await api.delete<T>(path, opts) : await api[method]<T>(path, body ?? {}, opts);
  if (res.kind !== "ok") throw new Error("Unexpected approval response");
  return res.data;
}

export const isCode = (err: unknown, code: string): err is ApiError => err instanceof ApiError && err.code === code;

/** `409 slot_overlap` → conflicting ranges. */
export function overlapConflicts(err: unknown): { starts_at: string; ends_at: string }[] {
  if (!isCode(err, "slot_overlap")) return [];
  const c = err.problem?.conflicts;
  return Array.isArray(c) ? (c as { starts_at: string; ends_at: string }[]) : [];
}

export const KIND_LABEL: Record<SessionKind, string> = {
  mock_interview: "Mock interview",
  resume_review: "Résumé review",
  career_guidance: "Career guidance",
};

export const SCORE_LABEL: Record<ScoreKey, string> = {
  communication: "Communication",
  problem_solving: "Problem solving",
  technical_depth: "Technical depth",
  confidence: "Confidence",
  overall: "Overall",
};

export const BOOKING_STATUS: Record<BookingStatus, { label: string; tone: "info" | "success" | "warning" | "neutral" | "danger" }> = {
  booked: { label: "Booked", tone: "info" },
  rescheduled: { label: "Rescheduled", tone: "info" },
  cancelled_by_student: { label: "Cancelled", tone: "neutral" },
  cancelled_by_mentor: { label: "Cancelled by mentor", tone: "warning" },
  completed: { label: "Completed", tone: "success" },
  student_no_show: { label: "Student no-show", tone: "warning" },
  mentor_no_show: { label: "Mentor no-show", tone: "warning" },
};

export const LIVE_STATUSES: BookingStatus[] = ["booked", "rescheduled"];

/** https-only meeting links (the api enforces the same). */
export function isHttpsUrl(v: string): boolean {
  try {
    return new URL(v).protocol === "https:";
  } catch {
    return false;
  }
}
