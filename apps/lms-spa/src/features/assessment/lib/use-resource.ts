"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export interface Resource<T> {
  data: T | undefined;
  error: unknown;
  loading: boolean;
  reload: () => Promise<void>;
  setData: (d: T | undefined) => void;
}

/**
 * Load data with L/X states (PRD §6) and a reload function. `key` changes trigger a reload;
 * `null` disables loading. Late responses from superseded requests are ignored.
 */
export function useLoader<T>(key: string | null, load: () => Promise<T>): Resource<T> {
  const [data, setData] = useState<T | undefined>();
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(key !== null);
  const loader = useRef(load);
  loader.current = load;
  const seq = useRef(0);

  const reload = useCallback(async () => {
    if (key === null) return;
    const id = ++seq.current;
    setLoading(true);
    setError(null);
    try {
      const res = await loader.current();
      if (id === seq.current) setData(res);
    } catch (err) {
      if (id === seq.current) setError(err);
    } finally {
      if (id === seq.current) setLoading(false);
    }
  }, [key]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { data, error, loading, reload, setData };
}
