"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { ItemResponse } from "../assignment-manager/types";

export type SaveState = "idle" | "saving" | "saved" | "error";

/**
 * Debounced per-item autosave. `queue` schedules a save after `delay` ms of quiet; `flush`
 * saves everything pending now (navigation, submit). Failed saves stay pending for the next try.
 */
export function useAutosave(save: (itemId: string, response: ItemResponse) => Promise<unknown>, delay = 1500) {
  const pending = useRef(new Map<string, ItemResponse>());
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const running = useRef<Promise<boolean> | null>(null);
  const saveRef = useRef(save);
  saveRef.current = save;
  const [state, setState] = useState<SaveState>("idle");

  const flush = useCallback(async (): Promise<boolean> => {
    if (timer.current) {
      clearTimeout(timer.current);
      timer.current = null;
    }
    if (running.current) await running.current;
    if (pending.current.size === 0) return true;
    const run = (async () => {
      setState("saving");
      const batch = [...pending.current.entries()];
      pending.current.clear();
      let ok = true;
      for (const [id, resp] of batch) {
        try {
          await saveRef.current(id, resp);
        } catch {
          ok = false;
          if (!pending.current.has(id)) pending.current.set(id, resp);
        }
      }
      setState(ok ? (pending.current.size ? "saving" : "saved") : "error");
      return ok;
    })();
    running.current = run;
    try {
      return await run;
    } finally {
      running.current = null;
    }
  }, []);

  const queue = useCallback(
    (itemId: string, response: ItemResponse) => {
      pending.current.set(itemId, response);
      setState((s) => (s === "error" ? "error" : "idle"));
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => void flush(), delay);
    },
    [delay, flush],
  );

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
      if (pending.current.size) void flush();
    },
    [flush],
  );

  return { state, queue, flush, hasPending: () => pending.current.size > 0 };
}
