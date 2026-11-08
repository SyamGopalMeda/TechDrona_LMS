"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api/client";
import type { EnabledAppsOut } from "../types";

export interface EnabledApps {
  /** app_key → enabled, as returned by the api (empty while loading or after an error). */
  apps: Record<string, boolean>;
  aiEnabled: boolean;
  loading: boolean;
  error: unknown;
  /**
   * Whether an app is enabled (platform-wide toggle, WS3).
   *  - while loading or after an error: true (fail open for navigation, so links don't flicker or
   *    vanish on a transient failure — the api still authorises every call);
   *  - an app_key the api didn't list: true (unknown keys are not gated here);
   *  - AI app keys (`ai_*`) additionally require `aiEnabled`, which is false on error (fail closed).
   */
  isEnabled: (appKey: string) => boolean;
  reload: () => Promise<void>;
}

/** GET me/enabled-apps (platform-wide). See `isEnabled` for the error policy. */
export function useEnabledApps(): EnabledApps {
  const [data, setData] = useState<EnabledAppsOut>();
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const seq = useRef(0);

  const reload = useCallback(async () => {
    const id = ++seq.current;
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<EnabledAppsOut>("me/enabled-apps");
      if (id === seq.current) setData(res);
    } catch (err) {
      if (id === seq.current) {
        setData(undefined);
        setError(err);
      }
    } finally {
      if (id === seq.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const apps = data?.apps ?? {};
  const aiEnabled = !error && data?.ai_enabled === true;
  const isEnabled = useCallback(
    (appKey: string) => {
      if (appKey.startsWith("ai_") && !aiEnabled) return false;
      if (!data) return true;
      return data.apps[appKey] ?? true;
    },
    [data, aiEnabled],
  );

  return { apps, aiEnabled, loading, error, isEnabled, reload };
}
