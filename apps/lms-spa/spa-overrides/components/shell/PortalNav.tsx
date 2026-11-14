"use client";

import Link from "next/link";
import { useRouter, usePathname } from "next/navigation";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { Icon } from "@/components/ui/Display";
import { PORTAL_PREFIXES, type NavItem } from "@/lib/nav/portals";
import { navIcon } from "@/lib/nav/icons";
import { useNavApps } from "@/features/ai/hooks/useNavApps";
import { cn } from "@/lib/ui/cn";

/** Portal home pages: matched exactly only. */
const ROOTS: readonly string[] = PORTAL_PREFIXES;

/** Navs longer than this start with only the current page's section open (the admin nav). */
export const COLLAPSE_THRESHOLD = 24;

/** The nav item that owns `pathname`: the longest href that equals it or is a path prefix of it.
 * Portal roots (`roots`) only match exactly, so the dashboard is not highlighted on every page. */
export function activeHref(items: NavItem[], pathname: string, roots: readonly string[] = []): string | null {
  let best: string | null = null;
  for (const { href } of items) {
    if (roots.includes(href) && pathname !== href) continue;
    if ((pathname === href || pathname.startsWith(`${href}/`)) && (!best || href.length > best.length)) best = href;
  }
  return best;
}

function rootsFor(root: string): readonly string[] {
  return ROOTS.includes(root) ? ROOTS : [...ROOTS, root];
}

/** The nav item for the current page (null when the page is not in the nav). */
export function useActiveNavItem(items: NavItem[], root: string): NavItem | null {
  const pathname = usePathname() ?? "";
  const href = activeHref(items, pathname, rootsFor(root));
  return href ? (items.find((i) => i.href === href) ?? null) : null;
}

interface Group {
  section: string | null;
  items: NavItem[];
}

function groupItems(items: NavItem[]): Group[] {
  const groups: Group[] = [];
  for (const item of items) {
    const section = item.section ?? null;
    const last = groups[groups.length - 1];
    if (last && last.section === section) last.items.push(item);
    else groups.push({ section, items: [item] });
  }
  return groups;
}

/** Section open/closed choices survive reloads (per portal); storage failures are ignored. */
function useSectionMemory(key: string) {
  const [toggled, setToggled] = useState<Record<string, boolean>>({});
  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(key);
      if (raw) setToggled(JSON.parse(raw) as Record<string, boolean>);
    } catch {
      /* private mode / blocked storage: defaults only */
    }
  }, [key]);
  const update = (fn: (t: Record<string, boolean>) => Record<string, boolean>) =>
    setToggled((t) => {
      const next = fn(t);
      try {
        window.localStorage.setItem(key, JSON.stringify(next));
      } catch {
        /* ignore */
      }
      return next;
    });
  return [toggled, update] as const;
}

const norm = (s: string) => s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");

const words = (s: string) => s.split(/[^a-z0-9]+/).filter(Boolean);

const SUFFIXES = ["ings", "ing", "ers", "er", "es", "ed", "s", "e"];

/** A crude English stem so "grade" finds "Grading" and "tests" finds "Test": strip one common
 * suffix, keeping at least three letters ("user" stays "user", "users" becomes "user"). */
export function stem(word: string): string {
  for (const suffix of SUFFIXES) {
    if (word.endsWith(suffix) && word.length - suffix.length >= 3) return word.slice(0, -suffix.length);
  }
  return word;
}

/** Query word `q` matches text word `w` as a prefix ("refu" → "refunds") or by stem ("grade" → "grading"). */
function wordMatches(w: string, q: string): boolean {
  if (w.startsWith(q)) return true;
  const s = stem(q);
  return s.length >= 3 && (w.startsWith(s) || stem(w) === s);
}

/** True when every query word matches some word of the text. */
const allWordsMatch = (text: string[], query: string[]) => query.length > 0 && query.every((q) => text.some((w) => wordMatches(w, q)));

/**
 * "Find a page" ranking (lower is better; null = no match). Label matches always outrank matches on
 * the section name or optional keywords, so "tests" lists "Tests" before the items that merely sit
 * in a "Questions & tests" section:
 * 0 label starts with the query · 1 every query word starts (or shares a stem with) a label word ·
 * 2 label contains the query · 3 keywords match · 4 section name matches.
 */
export function navMatchRank(item: NavItem & { keywords?: readonly string[] }, query: string): number | null {
  const q = norm(query.trim());
  if (!q) return null;
  const qWords = words(q);
  const label = norm(item.label);
  if (label.startsWith(q)) return 0;
  if (allWordsMatch(words(label), qWords)) return 1;
  if (label.includes(q)) return 2;
  const keywords = norm((item.keywords ?? []).join(" "));
  if (keywords && (keywords.includes(q) || allWordsMatch(words(`${label} ${keywords}`), qWords))) return 3;
  const all = norm(`${item.label} ${item.section ?? ""} ${keywords}`);
  if (all.includes(q) || allWordsMatch(words(all), qWords)) return 4;
  return null;
}

/** The items matching `query`, best first (ties keep nav order). */
export function searchNav<T extends NavItem>(items: T[], query: string): T[] {
  return items
    .map((item, i) => ({ item, i, rank: navMatchRank(item, query) }))
    .filter((m): m is { item: T; i: number; rank: number } => m.rank !== null)
    .sort((a, b) => a.rank - b.rank || a.i - b.i)
    .map((m) => m.item);
}

/**
 * Sidebar navigation (aria-current on the active item), grouped by `section` when set.
 * - Every item has an icon (lib/nav/icons) and a 44px touch target (36px on desktop).
 * - Sections are disclosure buttons (aria-expanded). Long navs (> COLLAPSE_THRESHOLD items) start
 *   with only the current page's section open; the reader's own open/close choices are remembered,
 *   and the current page's section is always shown.
 * - `searchable`: a "Find a page" box filters every item into one flat list, best match first
 *   (`searchNav`: label prefix / word / stem matches before section-name matches; Enter opens the first).
 * - `rail`: icon-only mode for the collapsed desktop sidebar (labels become tooltips / sr-only).
 * Items with an `appKey` are hidden when that app is turned off (fails open while loading / on error).
 */
export function PortalNav({
  items,
  label,
  root,
  tone = "light",
  searchable = false,
  rail = false,
}: {
  items: NavItem[];
  label: string;
  root: string;
  tone?: "light" | "dark";
  searchable?: boolean;
  rail?: boolean;
}) {
  const dark = tone === "dark";
  const router = useRouter();
  const pathname = usePathname() ?? "";
  const visible = useNavApps(items);
  const current = activeHref(visible, pathname, rootsFor(root));
  const groups = groupItems(visible);
  const activeSection = visible.find((i) => i.href === current)?.section ?? null;
  const big = visible.length > COLLAPSE_THRESHOLD;
  const idBase = useId();
  const [toggled, setToggled] = useSectionMemory(`td.nav.sections:${label}`);
  const [query, setQuery] = useState("");
  const q = norm(query.trim());
  const matches = useMemo(() => (q ? searchNav(visible, q) : []), [q, visible]);

  // The current page's section is always open, even if the reader closed it earlier.
  const isOpen = (section: string) => rail || section === activeSection || (toggled[section] ?? !big);

  const activeRef = useRef<HTMLAnchorElement | null>(null);
  useEffect(() => {
    activeRef.current?.scrollIntoView?.({ block: "nearest" });
  }, [current]);

  // Ctrl+K / ⌘K focuses "Find a page" (only the copy that is on screen: sidebar or open menu sheet).
  const searchRef = useRef<HTMLInputElement | null>(null);
  useEffect(() => {
    if (!searchable || rail) return;
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        const el = searchRef.current;
        if (!el || el.offsetParent === null) return;
        e.preventDefault();
        el.focus();
        el.select();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [searchable, rail]);

  const ring = dark ? "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-white/70" : "focus-visible:shadow-focus focus-visible:outline-none";

  const link = (item: NavItem, hint?: string | null) => {
    const active = item.href === current;
    const props = {
      href: item.href,
      "aria-current": active ? ("page" as const) : undefined,
      ref: active ? activeRef : undefined,
      title: rail ? item.label : undefined,
      className: cn(
        "group relative flex min-h-touch items-center gap-3 rounded-xl text-sm no-underline transition-colors duration-fast lg:min-h-10",
        rail ? "justify-center px-0" : "px-2.5",
        ring,
        dark
          ? active
            ? "bg-white/[0.12] font-semibold text-white shadow-[inset_0_0_0_1px_rgb(255_255_255/0.06)]"
            : "font-semibold text-[#c9d4f1] hover:bg-white/[0.07] hover:text-white"
          : active
            ? "bg-surface-selected font-semibold text-brand-on-subtle"
            : "font-medium text-fg-secondary hover:bg-surface-hover hover:text-fg",
      ),
    };
    const body = (
      <>
        {/* Website `.adm-side nav button.is-active::before`: 4px emerald bar on the sidebar edge. */}
        {active && !rail ? <span aria-hidden="true" className={cn("absolute inset-y-2.5 w-1", dark ? "-left-3 rounded-r bg-[#34d399]" : "left-0 rounded-full bg-brand")} /> : null}
        <Icon
          name={navIcon(item.href)}
          className={cn(
            "h-[18px] w-[18px] shrink-0 transition-colors",
            dark ? (active ? "text-[#8ee0b8]" : "text-[#8fa3d8] group-hover:text-white/85") : active ? "text-brand" : "text-fg-muted group-hover:text-fg-secondary",
          )}
        />
        <span className={cn("min-w-0 flex-1 truncate", rail && "sr-only")}>{item.label}</span>
        {hint && !rail ? <span className={cn("shrink-0 text-xs font-normal", dark ? "text-white/50" : "text-fg-muted")}>{hint}</span> : null}
      </>
    );
    return (
      <li key={item.href}>
        {/* documentNav: a plain anchor, so the page loads as a new document with its own CSP. */}
        {item.documentNav ? <a {...props}>{body}</a> : <Link {...props}>{body}</Link>}
      </li>
    );
  };

  const list = (entries: NavItem[], id?: string, labelledBy?: string, hidden?: boolean) => (
    <ul id={id} className="space-y-0.5" aria-labelledby={labelledBy} hidden={hidden}>
      {entries.map((item) => link(item))}
    </ul>
  );

  return (
    <nav aria-label={label}>
      {searchable && !rail ? (
        <div className="relative mb-3">
          <Icon name="search" className={cn("pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2", dark ? "text-white/45" : "text-fg-muted")} />
          <input
            ref={searchRef}
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && matches[0]) {
                e.preventDefault();
                const first = matches[0];
                setQuery("");
                if (first.documentNav) window.location.assign(first.href);
                else router.push(first.href);
              } else if (e.key === "Escape") setQuery("");
            }}
            placeholder="Find a page"
            aria-label="Find a page"
            aria-keyshortcuts="Control+K"
            className={cn(
              "h-9 w-full rounded-lg border pl-8 pr-12 text-sm transition-colors [&::-webkit-search-cancel-button]:hidden",
              dark
                ? "border-white/10 bg-white/[0.06] text-white placeholder:text-white/45 hover:bg-white/[0.09] focus:border-white/30 focus:bg-white/[0.1] focus:outline-none"
                : "border-line bg-surface-subtle text-fg placeholder:text-fg-muted focus:border-brand focus:outline-none",
            )}
          />
          {query ? null : (
            <kbd aria-hidden="true" className={cn("pointer-events-none absolute right-2 top-1/2 hidden -translate-y-1/2 rounded border px-1.5 font-sans text-[11px] font-semibold leading-4 lg:block", dark ? "border-white/15 text-white/45" : "border-line text-fg-muted")}>
              Ctrl K
            </kbd>
          )}
        </div>
      ) : null}

      {q ? (
        matches.length ? (
          <ul className="space-y-0.5" aria-label="Matching pages">
            {matches.map((item) => link(item, item.section))}
          </ul>
        ) : (
          <p className={cn("px-2.5 py-2 text-sm", dark ? "text-white/60" : "text-fg-muted")}>No page matches “{query.trim()}”.</p>
        )
      ) : (
        groups.map((g, i) => {
          if (!g.section) return <div key={`root-${i}`}>{list(g.items)}</div>;
          const section = g.section;
          const open = isOpen(section);
          const headingId = `${idBase}-h${i}`;
          const listId = `${idBase}-l${i}`;
          if (rail) {
            return (
              <div key={`${section}-${i}`} className={cn("mt-2 border-t pt-2 first:mt-0 first:border-t-0 first:pt-0", dark ? "border-white/10" : "border-line-subtle")}>
                <h2 id={headingId} className="sr-only">
                  {section}
                </h2>
                {list(g.items, listId, headingId)}
              </div>
            );
          }
          return (
            <div key={`${section}-${i}`} className="mt-4 first:mt-0">
              <h2 id={headingId}>
                <button
                  type="button"
                  aria-expanded={open}
                  aria-controls={listId}
                  onClick={() => setToggled((t) => ({ ...t, [section]: !open }))}
                  className={cn(
                    "group flex min-h-touch w-full items-center gap-1.5 rounded-md px-2.5 text-left text-[11px] font-semibold uppercase tracking-[0.1em] transition-colors lg:min-h-7",
                    ring,
                    dark ? "text-[#9fb0dc] hover:text-white" : "text-fg-muted hover:text-fg-secondary",
                  )}
                >
                  <span className="min-w-0 flex-1 truncate">{section}</span>
                  {/* Collapsed-section count as the website's `.adm-badge-n` pill. */}
                  {!open ? <span aria-hidden="true" className={cn("rounded-full px-1.5 text-[11px] font-bold tracking-normal", dark ? "bg-[#34d399] text-[#04331f]" : "bg-brand-subtle text-brand")}>{g.items.length}</span> : null}
                  <Icon name="chevronDown" className={cn("h-3.5 w-3.5 shrink-0 transition-transform duration-fast", open ? "rotate-180" : null)} />
                </button>
              </h2>
              <div className="mt-1">{list(g.items, listId, headingId, !open)}</div>
            </div>
          );
        })
      )}
    </nav>
  );
}
