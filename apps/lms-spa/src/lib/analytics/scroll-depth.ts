"use client";

import { useEffect, type RefObject } from "react";

/**
 * Reading depth for text lessons (`page.heartbeat.reading.max_scroll_depth_pct`,
 * analytics-event-schema §2.1.1): the share of the article that has been inside the viewport.
 *
 * `top` and `height` are the element's bounding box relative to the viewport; the bottom edge of
 * the viewport is the reading line. Content shorter than the viewport counts as 100 % once shown.
 */
export function scrollDepthPct(top: number, height: number, viewportHeight: number): number {
  if (!Number.isFinite(top) || !Number.isFinite(height) || height <= 0) return 0;
  const seen = viewportHeight - top;
  if (seen <= 0) return 0;
  return Math.max(0, Math.min(100, Math.round((seen / height) * 100)));
}

/** Reports the reading depth of `ref` on mount, scroll and resize (throttled to animation frames). */
export function useScrollDepth(ref: RefObject<HTMLElement | null>, onDepth: (pct: number) => void, enabled = true): void {
  useEffect(() => {
    if (!enabled || typeof window === "undefined") return;
    let frame = 0;
    const measure = () => {
      frame = 0;
      const el = ref.current;
      if (!el) return;
      const r = el.getBoundingClientRect();
      onDepth(scrollDepthPct(r.top, r.height, window.innerHeight));
    };
    const schedule = () => {
      if (frame) return;
      frame = typeof requestAnimationFrame === "function" ? requestAnimationFrame(measure) : (setTimeout(measure, 16) as unknown as number);
    };
    measure();
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule, { passive: true });
    return () => {
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      if (frame && typeof cancelAnimationFrame === "function") cancelAnimationFrame(frame);
    };
  }, [ref, onDepth, enabled]);
}
