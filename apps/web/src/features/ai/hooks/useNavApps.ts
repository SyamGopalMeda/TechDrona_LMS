"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api/client";
import type { EnabledAppsOut } from "../types";

/**
 * Navigation gating by platform-wide app enablement (GET me/enabled-apps).
 *
 * Fails OPEN: while loading, on error, or when nothing on the page is gated, every item is shown,
 * so the nav never flickers away; the api enforces `app_disabled` on every request anyway.
 * One request per page load is shared by every nav instance (sidebar, mobile menu, tab bar).
 */
const TTL_MS = 60_000;
let cache: { at: number; promise: Promise<EnabledAppsOut | null> } | null = null;

function load(): Promise<EnabledAppsOut | null> {
  if (cache && Date.now() - cache.at < TTL_MS) return cache.promise;
  // A restricted/suspended learner gets 403 account_restricted here; that must not trigger the global
  // redirect to /account/restricted, or support/devices/privacy pages (still allowed) become unreachable.
  const promise = api.get<EnabledAppsOut>("me/enabled-apps", { handle: { stepUp: false, restriction: false, auth: false, sessionChoice: false } }).then(
    (res) => res,
    () => null,
  );
  cache = { at: Date.now(), promise };
  return promise;
}

/** Test hook: forget the shared response. */
export function resetNavAppsCache(): void {
  cache = null;
}

export function useNavApps<T extends { appKey?: string }>(items: T[]): T[] {
  const gated = items.some((i) => i.appKey);
  const [apps, setApps] = useState<Record<string, boolean> | null>(null);

  useEffect(() => {
    if (!gated) return;
    let alive = true;
    void load().then((res) => {
      if (alive && res && res.apps) setApps(res.apps);
    });
    return () => {
      alive = false;
    };
  }, [gated]);

  if (!gated || !apps) return items;
  return items.filter((i) => !i.appKey || apps[i.appKey] !== false);
}
