"use client";

import { useEffect, useMemo, useRef } from "react";
import { uuid4 } from "@/lib/ids/uuid7";
import { loadAnalyticsConfig } from "./config";
import type { EntityRef } from "./envelope";
import type { Surface } from "./time-model";
import { ActivityTracker, type ClientEventType } from "./tracker";
import { createFetchTransport } from "./transport";
import type { VideoEvents } from "./video";

const TAB_KEY = "td.analytics.tab_id";
const APP_VERSION = process.env.NEXT_PUBLIC_APP_VERSION ?? "0.1.0";

/** tab_id: UUIDv4 in sessionStorage — survives refresh, new for a duplicated tab (§1.2). */
export function getTabId(): string {
  try {
    const existing = sessionStorage.getItem(TAB_KEY);
    if (existing) return existing;
    const id = uuid4();
    sessionStorage.setItem(TAB_KEY, id);
    return id;
  } catch {
    return uuid4();
  }
}

function navType(): "navigate" | "reload" | "back_forward" {
  const entry = performance.getEntriesByType?.("navigation")[0] as PerformanceNavigationTiming | undefined;
  if (entry?.type === "reload") return "reload";
  if (entry?.type === "back_forward") return "back_forward";
  return "navigate";
}

export interface UseActivityTrackerOptions {
  /** Route TEMPLATE, e.g. "/app/learn/[course_slug]/[lesson_id]" — never the raw URL. */
  route: string;
  surface: Surface;
  entity?: EntityRef;
  enabled?: boolean;
  /** Set true while a media player is playing (counts as ACTIVE when visible). */
  mediaPlaying?: boolean;
}

export interface ActivityTrackerHandle {
  /**
   * `video.*` events for the lesson player (analytics-event-schema §2.2). Stable across renders;
   * calls before the tracker is ready or after it closed are dropped.
   */
  video: VideoEvents;
  /** Client domain events (practice.question_viewed, assessment.question_viewed, …). */
  event(type: ClientEventType, payload: Record<string, unknown>): void;
  /** Code editor signals for coding surfaces (coding.editor_focus/blur + heartbeat.editor). */
  editor: EditorEvents;
  /** Reading progress 0–100 (heartbeat.reading.max_scroll_depth_pct). */
  scrollDepth(pct: number): void;
}

export interface EditorEvents {
  focus(language?: string): void;
  blur(language?: string): void;
  edit(n?: number): void;
}

const INPUT_EVENTS = ["keydown", "pointerdown", "wheel", "scroll", "touchstart"] as const;

/**
 * Mounts a page-instance tracker for the calling screen. Only learning-delivery (L-purpose)
 * page.* events are sent; identity is added by the server from the session.
 */
export function useActivityTracker({ route, surface, entity, enabled = true, mediaPlaying = false }: UseActivityTrackerOptions): ActivityTrackerHandle {
  const trackerRef = useRef<ActivityTracker | null>(null);
  // Domain events raised before the tracker is ready (config still loading) are replayed on start.
  const early = useRef<[ClientEventType, Record<string, unknown>][]>([]);
  const handle = useMemo<ActivityTrackerHandle>(
    () => ({
      video: forwardVideo(() => trackerRef.current?.video ?? null),
      event: (type, payload) => {
        const t = trackerRef.current;
        if (t) t.event(type, payload);
        else if (early.current.length < 20) early.current.push([type, payload]);
      },
      editor: {
        focus: (language) => trackerRef.current?.editorFocus(true, language),
        blur: (language) => trackerRef.current?.editorFocus(false, language),
        edit: (n) => trackerRef.current?.editOps(n),
      },
      scrollDepth: (pct) => trackerRef.current?.scrollDepth(pct),
    }),
    [],
  );
  const entityKey = JSON.stringify(entity ?? {});

  useEffect(() => {
    if (!enabled) return;
    let disposed = false;
    let tracker: ActivityTracker | null = null;
    let first = true;
    const transport = createFetchTransport();
    let lastMove = 0;

    const create = (nav: "navigate" | "reload" | "back_forward" | "spa") => {
      return loadAnalyticsConfig().then((params) => {
        if (disposed || !params) return; // analytics refused for this session (403): no tracker
        tracker = new ActivityTracker({
          route,
          surface,
          entity: JSON.parse(entityKey) as EntityRef,
          navType: nav,
          tabId: getTabId(),
          transport,
          appVersion: APP_VERSION,
          params,
          initial: { visible: document.visibilityState === "visible", focused: document.hasFocus() },
        });
        trackerRef.current = tracker;
        tracker.start();
        for (const [type, payload] of early.current.splice(0)) tracker.event(type, payload);
      });
    };

    void create(navType());

    const onInput = () => tracker?.input();
    const onMove = () => {
      const now = Date.now();
      if (now - lastMove >= 1000) {
        lastMove = now;
        tracker?.input();
      }
    };
    const onVisibility = () => tracker?.visibilityChange(document.visibilityState === "visible");
    const onFocus = () => tracker?.focusChange(true);
    const onBlur = () => tracker?.focusChange(false);
    const onPageHide = (e: PageTransitionEvent) => tracker?.close("pagehide", e.persisted);
    const onPageShow = (e: PageTransitionEvent) => {
      if (first) {
        first = false;
        return;
      }
      // bfcache restore → new page instance (§3.6)
      if (e.persisted) void create("back_forward");
    };
    const onFreeze = () => tracker?.close("freeze");

    for (const t of INPUT_EVENTS) window.addEventListener(t, onInput, { passive: true, capture: true });
    window.addEventListener("pointermove", onMove, { passive: true, capture: true });
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("focus", onFocus);
    window.addEventListener("blur", onBlur);
    window.addEventListener("pagehide", onPageHide);
    window.addEventListener("pageshow", onPageShow);
    document.addEventListener("freeze", onFreeze);

    return () => {
      disposed = true;
      for (const t of INPUT_EVENTS) window.removeEventListener(t, onInput, { capture: true });
      window.removeEventListener("pointermove", onMove, { capture: true });
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("focus", onFocus);
      window.removeEventListener("blur", onBlur);
      window.removeEventListener("pagehide", onPageHide);
      window.removeEventListener("pageshow", onPageShow);
      document.removeEventListener("freeze", onFreeze);
      // SPA route change / unmount closes this page instance (§3.6).
      tracker?.close("route_change");
      trackerRef.current = null;
      early.current = [];
    };
  }, [enabled, route, surface, entityKey]);

  useEffect(() => {
    trackerRef.current?.mediaPlaying(mediaPlaying);
  }, [mediaPlaying]);

  return handle;
}

/** A VideoEvents that forwards every call to the current tracker's session (if any). */
export function forwardVideo(target: () => VideoEvents | null): VideoEvents {
  return {
    play: (p, r) => target()?.play(p, r),
    pause: (p) => target()?.pause(p),
    seek: (f, t) => target()?.seek(f, t),
    rateChange: (f, t, p) => target()?.rateChange(f, t, p),
    ended: (p, d) => target()?.ended(p, d),
    bufferingStart: (p) => target()?.bufferingStart(p),
    bufferingEnd: (p, b) => target()?.bufferingEnd(p, b),
    error: (c, p) => target()?.error(c, p),
    timeUpdate: (p) => target()?.timeUpdate(p),
  };
}
