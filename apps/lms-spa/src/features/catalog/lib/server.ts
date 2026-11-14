import "server-only";
import { cache } from "react";
import { ApiError } from "@/lib/api/errors";
import { serverApiGet } from "@/lib/api/server";
import type { CourseDetailDto } from "./types";

export type ServerResult<T> = { ok: true; data: T } | { ok: false; status: number; code: string; title: string; detail: string; requestId: string | null };

/**
 * serverApiGet wrapped for page rendering: never throws, returns the user-safe problem
 * fields (title/detail/request_id) for the X state. Network failures map to 503.
 */
export async function serverLoad<T>(path: string): Promise<ServerResult<T>> {
  try {
    return { ok: true, data: await serverApiGet<T>(path, { navigation: true }) };
  } catch (err) {
    const e = err instanceof ApiError ? err : new ApiError(503, null, null);
    return { ok: false, status: e.status, code: e.code, title: e.title, detail: e.detail, requestId: e.requestId };
  }
}

/** Build `path?query` from defined, non-empty values. */
export function withQuery(path: string, query: Record<string, string | undefined | null>): string {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) if (v) qs.set(k, v);
  const s = qs.toString();
  return s ? `${path}?${s}` : path;
}

/** CAT-02 loader memoised per request (metadata + page share one upstream call). */
export const loadCourseDetail = cache((slug: string) => serverLoad<CourseDetailDto>(`catalog/courses/${encodeURIComponent(slug)}`));
