"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import type { NavItem } from "@/lib/nav/portals";
import { cn } from "@/lib/ui/cn";
import { isFocusRoute } from "./MobileTabBar";
import { PortalNav, useActiveNavItem } from "./PortalNav";
import { useSignOut } from "./SignOutButton";
import { Icon } from "@/components/ui/Display";
import { Logo } from "@/components/ui/Logo";
import { SITE_URL } from "@/lib/site/website";

/** Bottom of the navy sidebar (website `.adm-side-foot`): the main website, sign out, icon-only toggle. */
function SidebarFooter({ rail, onToggleRail }: { rail: boolean; onToggleRail: () => void }) {
  const { busy, start, dialog } = useSignOut();
  const item = cn(
    "flex min-h-touch w-full items-center gap-3 rounded-lg text-sm font-medium no-underline transition-colors duration-fast focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-white/70 lg:min-h-9",
    rail ? "justify-center px-0" : "px-2.5",
  );
  return (
    <div className="space-y-0.5 border-t border-white/10 px-3 py-3">
      <a href={SITE_URL} title={rail ? "Tech Drona website" : undefined} className={cn(item, "text-[#8ee0b8] hover:bg-white/[0.07] hover:text-white")}>
        <Icon name="external" className="h-[18px] w-[18px] shrink-0" />
        <span className={cn(rail && "sr-only")}>Tech Drona website</span>
      </a>
      <button
        type="button"
        aria-busy={busy || undefined}
        title={rail ? "Sign out" : undefined}
        onClick={() => {
          if (!busy) void start();
        }}
        className={cn(item, "text-[#FCA5A5] hover:bg-white/[0.06] hover:text-[#FECACA]")}
      >
        <Icon name="logout" className="h-[18px] w-[18px] shrink-0" />
        <span className={cn(rail && "sr-only")}>Sign out</span>
      </button>
      <button
        type="button"
        onClick={onToggleRail}
        aria-pressed={rail}
        title={rail ? "Expand sidebar" : undefined}
        className={cn(item, "text-white/55 hover:bg-white/[0.06] hover:text-white")}
      >
        <Icon name="panel" className="h-[18px] w-[18px] shrink-0" />
        <span className={cn(rail && "sr-only")}>{rail ? "Expand sidebar" : "Collapse sidebar"}</span>
      </button>
      {dialog}
    </div>
  );
}

const RAIL_KEY = "td.sidebar.rail";

/** Icon-only desktop sidebar, remembered per browser (storage failures fall back to expanded). */
function useRail(): [boolean, () => void] {
  const [rail, setRail] = useState(false);
  useEffect(() => {
    try {
      setRail(window.localStorage.getItem(RAIL_KEY) === "1");
    } catch {
      /* ignore */
    }
  }, []);
  const toggle = () =>
    setRail((r) => {
      try {
        window.localStorage.setItem(RAIL_KEY, r ? "0" : "1");
      } catch {
        /* ignore */
      }
      return !r;
    });
  return [rail, toggle];
}

/**
 * Data-heavy pages that may use the whole viewport width (no `max-w-wide` cap on the body row);
 * they still choose their own width with `PageContainer width="wide" | "full"`.
 */
const WIDE_ROUTES = [/^\/admin\/college-data\/?$/];

export function isWideRoute(pathname: string): boolean {
  return WIDE_ROUTES.some((rx) => rx.test(pathname));
}

/**
 * Staff portals below `lg`: a sticky "Menu · <current page>" bar whose panel overlays the page.
 * It closes on navigation (the layout persists across client navigation, so a plain <details>
 * stayed open over the new page), on any link click/tap inside it (lazy routes can update the
 * pathname late, so waiting for it alone could leave the panel over the new page; audit F7), on
 * Escape (focus returns to the button) and on the scrim.
 */
export function StaffMenu({ nav, label, root }: { nav: NavItem[]; label: string; root: string }) {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  const current = useActiveNavItem(nav, root);
  const panelId = useId();
  const buttonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => setOpen(false), [pathname]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        buttonRef.current?.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <div className="sticky top-topbar z-sticky border-b border-line bg-surface lg:hidden">
      <button
        ref={buttonRef}
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((o) => !o)}
        className="flex min-h-touch w-full items-center gap-2 px-4 text-left font-display text-sm font-semibold text-fg focus-visible:shadow-focus focus-visible:outline-none"
      >
        <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="h-5 w-5 shrink-0 text-brand">
          <path d="M4 7h16M4 12h16M4 17h16" />
        </svg>
        <span className="shrink-0">Menu</span>
        {current ? (
          <span className="min-w-0 truncate font-medium text-fg-secondary">
            <span aria-hidden="true">· </span>
            {current.label}
          </span>
        ) : null}
        <svg
          aria-hidden="true"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className={cn("ml-auto h-4 w-4 shrink-0 text-fg-muted transition-transform", open && "rotate-180")}
        >
          <path d="m6 9 6 6 6-6" />
        </svg>
      </button>
      {open ? (
        <>
          <div aria-hidden="true" onClick={() => setOpen(false)} className="fixed inset-0 top-[calc(var(--td-layout-topbar)+2.75rem)] bg-scrim" />
          <div
            id={panelId}
            onClickCapture={(e) => {
              if ((e.target as Element).closest("a[href]")) setOpen(false);
            }}
            className="absolute inset-x-0 top-full max-h-[70dvh] overflow-y-auto border-b border-line bg-surface px-3 pb-3 pt-2 shadow-lg"
          >
            <PortalNav items={nav} label={label} root={root} searchable />
          </div>
        </>
      ) : (
        <div id={panelId} hidden />
      )}
    </div>
  );
}

/**
 * The client half of PortalShell. Desktop: a full-height navy sidebar (logo, "Find a page", the
 * grouped nav with icons, footer) beside a slim top bar that names the current page and holds the
 * portal switcher / account menu. Below `lg` the top bar shows the logo and staff get the
 * "Menu · <page>" bar. Focus routes (lesson player, coding workspace, test runner, practice
 * session, checkout) drop the sidebar so the task gets the full width; wide routes lift the 90rem
 * cap for data-heavy pages.
 */
export function PortalFrame({
  nav,
  label,
  root,
  title = "",
  isStudent,
  brand,
  actions,
  children,
}: {
  nav: NavItem[];
  label: string;
  root: string;
  title?: string;
  isStudent: boolean;
  /** Logo + portal name for the top bar (shown there only when the sidebar is not). */
  brand?: ReactNode;
  /** Right side of the top bar: portal switcher, bell, account menu. */
  actions?: ReactNode;
  children: ReactNode;
}) {
  const pathname = usePathname() ?? "";
  const focus = isFocusRoute(pathname);
  const wide = isWideRoute(pathname);
  const current = useActiveNavItem(nav, root);
  const [rail, toggleRail] = useRail();
  return (
    <div className="flex min-h-dvh">
      {focus ? null : (
        <aside
          className={cn(
            "td-adm-side sticky top-0 hidden h-dvh shrink-0 flex-col transition-[width] duration-base lg:flex",
            rail ? "w-[var(--td-layout-sidebar-collapsed)]" : "w-sidebar",
          )}
        >
          <div className={cn("flex h-topbar shrink-0 items-center border-b border-white/10", rail ? "justify-center px-2" : "px-4")}>
            <Link
              href={root}
              aria-label={`Tech Drona ${title} home`}
              className="flex min-w-0 items-center rounded-md no-underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/70"
            >
              {rail ? (
                <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-white">
                  <Logo variant="mark" alt="" className="h-6 w-6" />
                </span>
              ) : (
                <Logo tone="white" alt="" className="h-8" />
              )}
            </Link>
          </div>
          {/* Website `.adm-brand span`: the portal name as a mint pill under the logo. */}
          {rail || !title ? null : (
            <p className="px-5 pb-0 pt-4">
              <span className="td-adm-badge">{title} portal</span>
            </p>
          )}
          <div className={cn("min-h-0 flex-1 overflow-y-auto py-3 [scrollbar-color:rgb(255_255_255/0.2)_transparent] [scrollbar-width:thin]", rail ? "px-2" : "px-3")}>
            <PortalNav items={nav} label={label} root={root} tone="dark" searchable rail={rail} />
          </div>
          <SidebarFooter rail={rail} onToggleRail={toggleRail} />
        </aside>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        {/* Website `.adm-top`: white, blurred, hairline #e6eaf2 rule and a soft shadow once content scrolls under it. */}
        <header className="sticky top-0 z-topbar border-b border-[#e6eaf2] bg-surface/95 shadow-[0_6px_24px_-18px_rgba(11,21,51,0.25)] backdrop-blur supports-[backdrop-filter]:bg-surface/90">
          <div className="flex h-topbar items-center justify-between gap-3 px-4 lg:px-8">
            <div className="flex min-w-0 items-center gap-3">
              <div className={cn("flex min-w-0 items-center gap-3", focus ? null : "lg:hidden")}>{brand}</div>
              {focus || !title ? null : <span className="hidden shrink-0 rounded-full bg-accent-subtle px-2.5 py-0.5 font-display text-xs font-bold text-accent-on-subtle lg:inline-flex">{title}</span>}
              {focus || !current ? null : (
                <p className="hidden min-w-0 items-center gap-2 text-sm lg:flex">
                  {current.section ? (
                    <>
                      <span className="truncate text-fg-muted">{current.section}</span>
                      <span aria-hidden="true" className="text-fg-muted">
                        /
                      </span>
                    </>
                  ) : null}
                  <span className="truncate font-semibold text-fg">{current.label}</span>
                </p>
              )}
            </div>
            <div className="flex items-center gap-1 sm:gap-2">{actions}</div>
          </div>
        </header>
        {isStudent || focus ? null : <StaffMenu nav={nav} label={label} root={root} />}
        <main
          id="main"
          tabIndex={-1}
          className={cn(
            "mx-auto w-full flex-1 px-4 focus:outline-none sm:px-6 lg:px-8",
            wide ? "max-w-none" : "max-w-wide",
            isStudent ? "pb-24 pt-6 lg:pb-10 lg:pt-8" : "py-6 lg:py-8",
          )}
        >
          {children}
        </main>
      </div>
    </div>
  );
}
