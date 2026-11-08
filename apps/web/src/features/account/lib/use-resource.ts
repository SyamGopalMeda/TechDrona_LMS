"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, type RequestOptions } from "@/lib/api/client";

export interface Resource<T> {
  data: T | undefined;
  error: unknown;
  loading: boolean;
  reload: () => Promise<void>;
}

/** GET a resource through the BFF with L/X states and a reload function. */
export function useResource<T>(path: string | null, options?: Omit<RequestOptions, "method" | "body" | "signal">): Resource<T> {
  const [data, setData] = useState<T | undefined>();
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(path !== null);
  const opts = useRef(options);
  const seq = useRef(0);

  const reload = useCallback(async () => {
    if (path === null) return;
    const id = ++seq.current;
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<T>(path, opts.current);
      if (id === seq.current) setData(res);
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
