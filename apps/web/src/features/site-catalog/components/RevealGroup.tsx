"use client";

import { useEffect, useRef, type ReactNode } from "react";

/**
 * Scroll reveal for the `[data-reveal]` elements inside (website `Reveal`, src/lib/motion.js).
 * Without JS (and above the fold) the CSS load animation already plays; this only re-arms the
 * elements that are still below the viewport so they fade up when scrolled into view. Honours
 * prefers-reduced-motion (does nothing) and browsers without IntersectionObserver.
 */
export function useRevealOnScroll(ref: React.RefObject<HTMLElement | null>) {
  useEffect(() => {
    const root = ref.current;
    if (!root || typeof window === "undefined" || typeof IntersectionObserver === "undefined") return;
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    const items = Array.from(root.querySelectorAll<HTMLElement>("[data-reveal]"));
    const below = items.filter((el) => el.getBoundingClientRect().top > window.innerHeight);
    if (!below.length) return;
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (!e.isIntersecting) continue;
          (e.target as HTMLElement).dataset.reveal = "in";
          io.unobserve(e.target);
        }
      },
      { rootMargin: "0px 0px -8% 0px", threshold: 0.12 },
    );
    for (const el of below) {
      el.dataset.reveal = "wait";
      io.observe(el);
    }
    return () => {
      io.disconnect();
      for (const el of below) el.dataset.reveal = "in";
    };
  }, [ref]);
}

export function RevealGroup({ children, className }: { children: ReactNode; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useRevealOnScroll(ref);
  return (
    <div ref={ref} className={className}>
      {children}
    </div>
  );
}
