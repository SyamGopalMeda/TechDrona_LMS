"use client";

import { createElement, useLayoutEffect, useEffect, useRef, type ReactNode, type RefObject } from "react";
import { cn } from "@/lib/ui/cn";

/*
 * Reveal-on-scroll, after the website's `.rv` / `.reveal` / `.reveal-stagger` system
 * (tech drona/src/styles/global.css `.rv`, src/lib/scrollAnimations.js) without GSAP:
 * a tiny IntersectionObserver hook plus CSS in src/styles/site.css (`[data-rv]`).
 *
 * Safety rules (same as the website's):
 * - Nothing is hidden by CSS alone. The hook marks an element `data-rv="pending"` only on the
 *   client, so if JavaScript never runs everything simply shows.
 * - Content painted by the server and already on screen at hydration is never re-hidden (no flash).
 *   Below-the-fold content, and content rendered later on the client (dashboards after their data
 *   loads), fades up when it scrolls into view.
 * - prefers-reduced-motion: the hook does nothing and the CSS has no motion.
 * - Only opacity and transform animate, so layout never shifts.
 */

const useIsoLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;

/** False during the first (hydration) commit of a page load, true for every later render. */
let booted = false;

function reducedMotion(): boolean {
  try {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return true;
  }
}

/** Reveal `ref`'s element when it enters the viewport (once). */
export function useReveal<T extends HTMLElement>(ref: RefObject<T | null>) {
  useIsoLayoutEffect(() => {
    const el = ref.current;
    const hydrating = !booted;
    if (hydrating) {
      // Flip after this commit: later mounts (client navigation, data arriving) may animate.
      setTimeout(() => {
        booted = true;
      }, 0);
    }
    if (!el || typeof IntersectionObserver === "undefined" || reducedMotion()) return;
    const r = el.getBoundingClientRect();
    const onScreen = r.top < window.innerHeight && r.bottom > 0;
    if (onScreen && hydrating) return; // already painted by the server: leave it alone
    el.dataset.rv = "pending";
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) {
            (e.target as HTMLElement).dataset.rv = "in";
            io.unobserve(e.target);
          }
        }
      },
      { rootMargin: "0px 0px -8% 0px", threshold: 0.01 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);
}

export interface RevealProps {
  children: ReactNode;
  /** Element to render (default div). */
  as?: "div" | "section" | "ul" | "ol" | "li" | "header" | "aside";
  /** Children fade up one after another (website `.reveal-stagger`). */
  stagger?: boolean;
  className?: string;
  id?: string;
  "aria-labelledby"?: string;
  "aria-label"?: string;
}

/** Wrapper that fades its content up as it scrolls into view. Purely visual: no roles are added. */
export function Reveal({ children, as = "div", stagger = false, className, ...rest }: RevealProps) {
  const ref = useRef<HTMLElement>(null);
  useReveal(ref);
  return createElement(as, { ref, className: cn(stagger && "td-stagger", className), ...rest }, children);
}
