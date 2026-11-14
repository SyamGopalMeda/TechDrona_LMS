"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";
import type { NavItem } from "@/lib/nav/portals";
import { cn } from "@/lib/ui/cn";
import { PortalNav } from "./PortalNav";

export interface TabItem {
  href: string;
  label: string;
}

/** Sitemap §1 learner bottom tabs (below `lg`): Home · Learn · Practice · Tests · More. */
export const STUDENT_TABS: TabItem[] = [
  { href: "/app", label: "Home" },
  { href: "/app/learning", label: "Learn" },
  { href: "/app/practice", label: "Practice" },
  { href: "/app/tests", label: "Tests" },
];

/**
 * Focus-shell routes (design-system §4 "Focus": course player, practice session, timed test,
 * coding workspace, checkout) have no global navigation: no tab bar on phones (their own action
 * bars are pinned to the bottom; it sat on top of "Check answer" / "Save →") and no sidebar on
 * desktop, so the player/editor/runner gets the full width (PortalFrame).
 */
const FOCUS_ROUTES = [
  /^\/app\/attempts\/[^/]+(?:\/resume)?\/?$/,
  /^\/app\/practice\/sessions\/[^/]+\/?$/,
  /^\/app\/learn\/[^/]+\/[^/]+\/?$/,
  /^\/app\/coding\/[^/]+\/?$/,
  /^\/app\/checkout\/[^/]+\/?$/,
];

export function isFocusRoute(pathname: string): boolean {
  return FOCUS_ROUTES.some((rx) => rx.test(pathname));
}

/* Decorative 24px stroke icons (labels always shown), keyed by tab href; "more" for the sheet. */
const ICON_PATHS: Record<string, string> = {
  "/app": "M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z",
  "/app/learning": "M4 5.5A1.5 1.5 0 0 1 5.5 4H11v16H5.5A1.5 1.5 0 0 1 4 18.5zM13 4h5.5A1.5 1.5 0 0 1 20 5.5v13a1.5 1.5 0 0 1-1.5 1.5H13z",
  "/app/practice": "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zm0-4a5 5 0 1 0 0-10 5 5 0 0 0 0 10zm0-4a1 1 0 1 0 0-2 1 1 0 0 0 0 2z",
  "/app/tests": "M9 4h6v3H9zM7 5.5H5.5A1.5 1.5 0 0 0 4 7v12.5A1.5 1.5 0 0 0 5.5 21h13a1.5 1.5 0 0 0 1.5-1.5V7a1.5 1.5 0 0 0-1.5-1.5H17M8.5 13.5l2.5 2.5 4.5-5",
  more: "M4 7h16M4 12h16M4 17h16",
};

function TabIcon({ name, active }: { name: string; active: boolean }) {
  const d = ICON_PATHS[name];
  if (!d) return null;
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={active ? 2.2 : 1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      className="h-6 w-6"
    >
      <path d={d} />
    </svg>
  );
}

/**
 * Mobile bottom tab bar. "More" opens the rest of the portal navigation (the tab destinations are
 * left out) as a titled sheet above the bar, over a scrim. It closes on navigation, on Escape, on
 * the × button and on a tap on the scrim. The sheet follows the bar in DOM order, takes focus
 * (first link) when opened, and closing returns focus to "More" (audit S3, WCAG 2.4.3). Hidden at
 * `lg` and up, where the sidebar is shown, and on focus-shell routes (`isFocusRoute`).
 */
export function MobileTabBar({ tabs, nav, label, root }: { tabs: TabItem[]; nav: NavItem[]; label: string; root: string }) {
  const pathname = usePathname() ?? "";
  const [open, setOpen] = useState(false);
  const sheetId = useId();
  const titleId = useId();
  const moreRef = useRef<HTMLButtonElement>(null);
  const sheetRef = useRef<HTMLDivElement>(null);
  const isActive = (href: string) => (href === root ? pathname === root : pathname === href || pathname.startsWith(`${href}/`));
  const inTabs = tabs.some((t) => isActive(t.href));

  const sheetItems = nav.filter((item) => !tabs.some((t) => t.href === item.href));
  const close = (returnFocus = true) => {
    setOpen(false);
    if (returnFocus) moreRef.current?.focus();
  };

  useEffect(() => setOpen(false), [pathname]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        moreRef.current?.focus();
      }
    };
    sheetRef.current?.querySelector<HTMLElement>("a[href]")?.focus();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  const tabClass = (active: boolean) =>
    cn(
      "relative flex min-h-touch flex-1 flex-col items-center justify-center gap-0.5 px-1 font-display text-xs font-semibold no-underline focus-visible:shadow-focus focus-visible:outline-none",
      active ? "text-brand" : "text-fg-muted hover:text-fg",
    );

  if (isFocusRoute(pathname)) return null;

  return (
    <div className="lg:hidden">
      <nav
        aria-label="Primary"
        data-td-tabbar=""
        className="fixed inset-x-0 bottom-0 z-topbar flex h-[calc(4rem+env(safe-area-inset-bottom))] border-t border-line bg-surface/95 pb-[env(safe-area-inset-bottom)] backdrop-blur"
      >
        {tabs.map((t) => {
          const active = isActive(t.href);
          return (
            <Link key={t.href} href={t.href} aria-current={active ? "page" : undefined} className={tabClass(active)}>
              <span aria-hidden="true" className={cn("absolute inset-x-0 top-0 mx-auto h-[3px] w-8 rounded-b-full", active ? "bg-brand" : "bg-transparent")} />
              <TabIcon name={t.href} active={active} />
              {t.label}
            </Link>
          );
        })}
        <button ref={moreRef} type="button" aria-expanded={open} aria-controls={sheetId} onClick={() => setOpen((o) => !o)} className={tabClass(open || !inTabs)}>
          <span aria-hidden="true" className={cn("absolute inset-x-0 top-0 mx-auto h-[3px] w-8 rounded-b-full", !inTabs ? "bg-brand" : "bg-transparent")} />
          <TabIcon name="more" active={open || !inTabs} />
          More
        </button>
      </nav>
      {open ? (
        <>
          {/* Scrim: dims the page and closes the sheet on tap (decorative for assistive tech; Escape / × close it too). */}
          <div aria-hidden="true" onClick={() => close(false)} className="fixed inset-0 bottom-[calc(4rem+env(safe-area-inset-bottom))] z-overlay bg-scrim" />
          <div
            ref={sheetRef}
            id={sheetId}
            role="dialog"
            aria-labelledby={titleId}
            className="fixed inset-x-0 bottom-[calc(4rem+env(safe-area-inset-bottom))] z-drawer flex max-h-[75dvh] flex-col rounded-t-2xl border-t border-line bg-surface shadow-xl"
          >
            <div className="flex shrink-0 items-center justify-between gap-3 border-b border-line-subtle py-1 pl-5 pr-2">
              <h2 id={titleId} className="font-display text-base font-extrabold text-fg-heading">
                More
              </h2>
              <button
                type="button"
                aria-label="Close menu"
                onClick={() => close()}
                className="grid h-11 w-11 place-items-center rounded-md text-fg-muted hover:bg-surface-hover hover:text-fg focus-visible:shadow-focus focus-visible:outline-none"
              >
                <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="h-5 w-5">
                  <path d="M6 6l12 12M18 6 6 18" />
                </svg>
              </button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-3">
              <PortalNav items={sheetItems} label={label} root={root} />
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}
