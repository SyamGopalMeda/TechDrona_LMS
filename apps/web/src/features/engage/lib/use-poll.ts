"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api/client";
import type { Unchanged } from "./types";

export const POLL_MS = 2000;

export interface PollState<T> {
  data: T | undefined;
  error: unknown;
  loading: boolean;
  /** Fetch now (e.g. after an action); keeps the `since` version. */
  refresh: () => Promise<void>;
}

function isUnchanged(v: unknown): v is Unchanged {
  return typeof v === "object" && v !== null && (v as { unchanged?: unknown }).unchanged === true;
}

/**
 * Polls a live engage endpoint (`…/presenter`, `…/live`) every `intervalMs` with
 * `?since=<last version>`; an `{unchanged:true}` reply keeps the previous state. Polling pauses
 * while the tab is hidden and stops once `done(data)` is true (e.g. the run is finalised).
 */
export function usePoll<T extends { version: string }>(
  path: string | null,
  opts: { intervalMs?: number; done?: (data: T) => boolean; onError?: (err: unknown) => void } = {},
): PollState<T> {
  const { intervalMs = POLL_MS } = opts;
  const [data, setData] = useState<T | undefined>();
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(path !== null);
  const version = useRef<string | undefined>(undefined);
  const latest = useRef<T | undefined>(undefined);
  const doneRef = useRef(opts.done);
  const errRef = useRef(opts.onError);
  doneRef.current = opts.done;
  errRef.current = opts.onError;
  const inflight = useRef(false);

  useEffect(() => {
    version.current = undefined;
    latest.current = undefined;
    setData(undefined);
    setError(null);
    setLoading(path !== null);
  }, [path]);

  const fetchOnce = useCallback(async (force = false) => {
    if (path === null || (inflight.current && !force)) return;
    inflight.current = true;
    try {
      const res = await api.get<T | Unchanged>(path, { query: { since: version.current } });
      if (!isUnchanged(res)) {
        latest.current = res;
        setData(res);
      }
      version.current = res.version;
      setError(null);
    } catch (err) {
      setError(err);
      errRef.current?.(err);
    } finally {
      inflight.current = false;
      setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    if (path === null) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let alive = true;
    const finished = () => latest.current !== undefined && !!doneRef.current?.(latest.current);
    const hidden = () => typeof document !== "undefined" && document.visibilityState === "hidden";
    let looping = false;
    const tick = async () => {
      timer = undefined;
      if (!alive || hidden()) {
        looping = false;
        return;
      }
      looping = true;
      await fetchOnce(false);
      if (alive && !finished() && !hidden()) timer = setTimeout(tick, intervalMs);
      else looping = false;
    };
    const onVisible = () => {
      if (!hidden() && !looping && !finished()) void tick();
      else if (hidden() && timer !== undefined) {
        clearTimeout(timer);
        timer = undefined;
        looping = false;
      }
    };
    void tick();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      alive = false;
      if (timer !== undefined) clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [path, intervalMs, fetchOnce]);

  const refresh = useCallback(() => fetchOnce(true), [fetchOnce]);
  return { data, error, loading, refresh };
}
