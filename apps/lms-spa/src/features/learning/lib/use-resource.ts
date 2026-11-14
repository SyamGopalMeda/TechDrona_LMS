"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, type RequestOptions } from "@/lib/api/client";

export interface Resource<T> {
  data: T | undefined;
  error: unknown;
  loading: boolean;
  reload: () => Promise<void>;
}

/**
 * GET through the BFF with L/X states. `path === null` waits (dependent requests).
 * Stale responses from an earlier path are dropped.
 */
export function useResource<T>(path: string | null, query?: RequestOptions["query"]): Resource<T> {
  const [data, setData] = useState<T | undefined>();
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(path !== null);
  const seq = useRef(0);
  const queryKey = JSON.stringify(query ?? {});

  const reload = useCallback(async () => {
    if (path === null) return;
    const id = ++seq.current;
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<T>(path, { query: JSON.parse(queryKey) as RequestOptions["query"] });
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

interface CursorPaged<R> {
  data: R[];
  page?: { next_cursor: string | null; has_more?: boolean; limit?: number };
}

/** Safety cap on pages followed (100 rows each): stops a looping cursor from hanging the view. */
const MAX_PAGES = 50;

/**
 * GET every page of a §1.10 cursor list (LRN-02, LRN-11 now paginate with a default of 100,
 * learn R5) and return the rows merged into one `{data}` envelope.
 */
export function useAllPages<R>(path: string | null): Resource<CursorPaged<R>> {
  const [data, setData] = useState<CursorPaged<R> | undefined>();
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(path !== null);
  const seq = useRef(0);

  const reload = useCallback(async () => {
    if (path === null) return;
    const id = ++seq.current;
    setLoading(true);
    setError(null);
    try {
      const rows: R[] = [];
      let cursor: string | null = null;
      for (let i = 0; i < MAX_PAGES; i++) {
        const res: CursorPaged<R> = await api.get<CursorPaged<R>>(path, { query: cursor ? { cursor, limit: 100 } : { limit: 100 } });
        rows.push(...(res.data ?? []));
        cursor = res.page?.next_cursor ?? null;
        if (!cursor) break;
      }
      if (id === seq.current) setData({ data: rows });
    } catch (err) {
      if (id === seq.current) setError(err);
    } finally {
      if (id === seq.current) setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { data, error, loading, reload };
}
