"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button, LoadingBlock, PageHeader, buttonClasses } from "@/components/ui";
import { CollegePortalMoving, useCollegePortalAvailable } from "./availability";

/** Same-origin entry of the College Data Portal (served by the /college-portal route handler). */
export const COLLEGE_PORTAL_ENTRY = "/college-portal/index.html";

/** How long the frame may take before we offer "Open full screen" / "Try again" (ms). */
export const FRAME_LOAD_TIMEOUT_MS = 15_000;

/** Smallest frame height; the frame otherwise fills the viewport below its own top edge. */
const MIN_FRAME_PX = 320;
/** Space kept under the frame for the shell's bottom padding. */
const BOTTOM_GAP_PX = 24;

/**
 * True when the current document was loaded at `pathname` (not reached by client-side routing).
 * The frame is allowed only by this page's own CSP (`frame-src 'self'`, set by middleware for
 * /admin/college-data); after a soft navigation the previous page's CSP is still in force and the
 * browser would block the frame. No Navigation Timing entry (old browsers, tests): assume yes.
 */
export function loadedAsDocument(pathname: string): boolean {
  try {
    const nav = performance.getEntriesByType("navigation")[0];
    if (!nav?.name) return true;
    return new URL(nav.name).pathname === pathname;
  } catch {
    return true;
  }
}

/** Frame height that fills the viewport from `top` (px from the viewport top) down, never below the minimum. */
export function fillHeight(viewportHeight: number, top: number): number {
  return Math.max(MIN_FRAME_PX, Math.floor(viewportHeight - top - BOTTOM_GAP_PX));
}

type FrameState = "loading" | "loaded" | "slow";

/**
 * ADM-015: the College Data Portal (colleges, contacts, calls, targets, enrollments) embedded in
 * the Admin portal. The portal is a separate first-party app proxied same-origin under
 * /college-portal/, which re-checks the LMS session and Admin access on every request.
 *
 * Layout: the frame fills the rest of the viewport below the page header (measured, so the
 * phone "Menu" bar and padding are accounted for), which keeps a single scroll area — the
 * frame's — instead of the page scrolling and the frame scrolling too.
 */
export function CollegeDataPortal() {
  // Not deployed on Hosting yet (live audit admin.md F1): a friendly "being moved" state instead
  // of a frame blocked by the LMS app's own frame-ancestors 'none'. Unknown = frame as before.
  const available = useCollegePortalAvailable();
  const [ready, setReady] = useState(false);
  const [frameState, setFrameState] = useState<FrameState>("loading");
  const [attempt, setAttempt] = useState(0);
  const [height, setHeight] = useState<number | null>(null);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Soft navigation (Link, back/forward): reload once as a real document so the right CSP applies.
    if (loadedAsDocument(window.location.pathname)) setReady(true);
    else window.location.replace(window.location.href);
  }, []);

  // Fill the viewport below the frame's top edge; re-measure on resize / rotation.
  useEffect(() => {
    const fit = () => {
      const el = box.current;
      if (!el) return;
      setHeight(fillHeight(window.innerHeight, el.getBoundingClientRect().top + window.scrollY));
    };
    fit();
    window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  }, [ready, frameState]);

  // No load event in time: say so and offer a way out (the frame keeps loading behind it).
  useEffect(() => {
    if (!ready || frameState !== "loading") return;
    const t = window.setTimeout(() => setFrameState((s) => (s === "loading" ? "slow" : s)), FRAME_LOAD_TIMEOUT_MS);
    return () => window.clearTimeout(t);
  }, [ready, frameState, attempt]);

  const retry = useCallback(() => {
    setFrameState("loading");
    setAttempt((n) => n + 1);
  }, []);

  const fullScreen = (
    <a href={COLLEGE_PORTAL_ENTRY} target="_blank" rel="noopener" className={buttonClasses({ variant: "secondary", size: "sm" })}>
      Open full screen
      <span className="sr-only"> (opens in a new tab)</span>
    </a>
  );

  if (available === false) {
    return (
      <div>
        <PageHeader title="College Data Portal" description="Colleges, contacts, calls, targets and enrolments for college outreach." />
        <CollegePortalMoving />
      </div>
    );
  }

  return (
    <div>
      <PageHeader title="College Data Portal" description="Colleges, contacts, calls, targets and enrolments for college outreach." actions={fullScreen} />
      {frameState === "slow" ? (
        <div role="status" className="mb-3 flex flex-col gap-3 rounded-lg border border-warning-border bg-warning-subtle p-3 text-sm text-warning-fg sm:flex-row sm:items-center sm:justify-between">
          <p>
            The College Data Portal is taking longer than usual to load. Open it in its own tab, or try again.
          </p>
          <div className="flex shrink-0 flex-wrap gap-2">
            {fullScreen}
            <Button size="sm" variant="secondary" onClick={retry}>
              Try again
            </Button>
          </div>
        </div>
      ) : null}
      <div
        ref={box}
        className="relative h-[calc(100dvh-var(--td-layout-topbar)-12rem)] min-h-80 w-full overflow-hidden rounded-lg border border-line bg-surface"
        style={height ? { height } : undefined}
      >
        {ready ? (
          <iframe
            key={attempt}
            src={COLLEGE_PORTAL_ENTRY}
            title="College Data Portal"
            referrerPolicy="same-origin"
            allow=""
            className="block h-full w-full"
            onLoad={() => setFrameState("loaded")}
          />
        ) : null}
        {!ready || frameState === "loading" ? (
          <div className="absolute inset-0 bg-surface p-6">
            <LoadingBlock label="Loading the College Data Portal…" size="row" rows={6} />
          </div>
        ) : null}
      </div>
    </div>
  );
}
