"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useId } from "react";
import { PORTAL_PREFIXES, type NavItem } from "@/lib/nav/portals";
import { useNavApps } from "@/features/ai/hooks/useNavApps";
import { cn } from "@/lib/ui/cn";

/** Portal home pages: matched exactly only. */
const ROOTS: readonly string[] = PORTAL_PREFIXES;

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

/** Sidebar navigation with aria-current on the active item, grouped by `section` when set.
 * Items with an `appKey` are hidden when that app is turned off (fails open while loading / on error). */
export function PortalNav({ items, label, root }: { items: NavItem[]; label: string; root: string }) {
  const pathname = usePathname() ?? "";
  const visible = useNavApps(items);
  const current = activeHref(visible, pathname, ROOTS.includes(root) ? ROOTS : [...ROOTS, root]);
  const groups: { section: string | null; items: NavItem[] }[] = [];
  for (const item of visible) {
    const section = item.section ?? null;
    const last = groups[groups.length - 1];
    if (last && last.section === section) last.items.push(item);
    else groups.push({ section, items: [item] });
  }
  const list = (entries: NavItem[], labelledBy?: string) => (
    <ul className="space-y-0.5" aria-labelledby={labelledBy}>
      {entries.map((item) => {
        const active = item.href === current;
        return (
          <li key={item.href}>
            <Link
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "relative flex min-h-[2.5rem] items-center rounded-lg px-3 py-2 text-sm no-underline transition-colors duration-fast focus-visible:shadow-focus focus-visible:outline-none",
                active
                  ? "bg-surface-selected font-semibold text-brand-on-subtle before:absolute before:inset-y-2 before:left-0 before:w-[3px] before:rounded-full before:bg-brand"
                  : "font-medium text-fg-secondary hover:bg-surface-hover hover:text-brand",
              )}
            >
              {item.label}
            </Link>
          </li>
        );
      })}
    </ul>
  );
  const idBase = useId();
  return (
    <nav aria-label={label}>
      {groups.map((g, i) =>
        g.section ? (
          <div key={`${g.section}-${i}`} className="mt-5 border-t border-line-subtle pt-4 first:mt-0 first:border-t-0 first:pt-0">
            <h2 id={`${idBase}-${i}`} className="px-3 pb-1.5 font-display text-[0.6875rem] font-bold uppercase tracking-[0.1em] text-fg-muted">
              {g.section}
            </h2>
            {list(g.items, `${idBase}-${i}`)}
          </div>
        ) : (
          <div key={`root-${i}`}>{list(g.items)}</div>
        ),
      )}
    </nav>
  );
}
