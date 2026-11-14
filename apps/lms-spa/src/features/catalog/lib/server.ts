import "server-only";
import { ApiError } from "@/lib/api/errors";
import { serverApiGet } from "@/lib/api/server";

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
