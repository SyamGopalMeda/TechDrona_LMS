"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api/client";
import type { ApiPath, Body } from "@/lib/api-types";

/**
 * Shared data hook for the staff portals (trainer, evaluator, studio, admin).
 * GET through the BFF with loading / error / reload. Refetches when the path or the
 * query values change (query is compared by value). `null` path = idle.
 */
export type Query = Record<
  string,
  string | number | boolean | null | undefined
>;

export interface ApiState<T> {
  data: T | undefined;
  error: unknown;
  loading: boolean;
  reload: () => Promise<void>;
}

export function useApi<T>(path: string | null, query?: Query): ApiState<T> {
  const [data, setData] = useState<T | undefined>();
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(path !== null);
  const seq = useRef(0);
  const queryKey = query ? JSON.stringify(query) : "";

  const reload = useCallback(async () => {
    if (path === null) {
      setLoading(false);
      return;
    }
    const id = ++seq.current;
    setLoading(true);
    setError(null);
    try {
      const q = queryKey ? (JSON.parse(queryKey) as Query) : undefined;
      const res = await api.get<T>(path, q ? { query: q } : {});
      if (id === seq.current) setData(res);
    } catch (err) {
      if (id === seq.current) setError(err);
    } finally {
      if (id === seq.current) setLoading(false);
    }
  }, [path, queryKey]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { data, error, loading, reload };
}

/** `encodeURIComponent` for path segments. */
export const seg = (v: string) => encodeURIComponent(v);

/**
 * A request body as sent. The generated OpenAPI types mark Pydantic fields that have defaults
 * as required, but the api accepts them omitted — so callers that rely on defaults check their
 * field names/types against `Partial<Body<…>>` instead.
 */
export type SendBody<
  P extends ApiPath,
  M extends "get" | "post" | "put" | "patch" | "delete",
> = Partial<Body<P, M>>;

/**
 * Like `useApi`, for pickers that need the whole list of a cursor-paged endpoint
 * (`{items|data: T[], page: {next_cursor}}`, api-spec §1.10): follows `page.next_cursor` up to
 * `maxPages` pages and returns the rows concatenated under the same key.
 */
export function useApiAll<T, K extends "items" | "data" = "items">(
  path: string | null,
  query?: Query,
  opts: { key?: K; maxPages?: number } = {},
): ApiState<{ [P in K]: T[] } & { truncated: boolean }> {
  const key = (opts.key ?? "items") as K;
  const maxPages = opts.maxPages ?? 10;
  const [data, setData] = useState<({ [P in K]: T[] } & { truncated: boolean }) | undefined>();
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(path !== null);
  const seq = useRef(0);
  const queryKey = query ? JSON.stringify(query) : "";

  const reload = useCallback(async () => {
    if (path === null) {
      setLoading(false);
      return;
    }
    const id = ++seq.current;
    setLoading(true);
    setError(null);
    try {
      const base = queryKey ? (JSON.parse(queryKey) as Query) : {};
      const rows: T[] = [];
      let cursor: string | null | undefined;
      let pages = 0;
      do {
        const res = await api.get<Record<string, unknown> & { page?: { next_cursor?: string | null } }>(path, { query: { ...base, ...(cursor ? { cursor } : {}) } });
        rows.push(...(((res[key] as T[] | undefined) ?? []) as T[]));
        cursor = res.page?.next_cursor ?? null;
        pages += 1;
      } while (cursor && pages < maxPages);
      if (id === seq.current) setData({ [key]: rows, truncated: !!cursor } as { [P in K]: T[] } & { truncated: boolean });
    } catch (err) {
      if (id === seq.current) setError(err);
    } finally {
      if (id === seq.current) setLoading(false);
    }
  }, [path, queryKey, key, maxPages]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { data, error, loading, reload };
}
