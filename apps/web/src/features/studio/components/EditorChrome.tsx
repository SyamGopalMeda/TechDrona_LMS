"use client";

import type { ReactNode } from "react";
import { PageHeader, type Crumb } from "@/components/ui";
import { cn } from "@/lib/ui/cn";

/**
 * Detail-page header for studio/trainer editors: breadcrumbs to the parent list, the entity's
 * name as the h1 (the generic `fallback` while it loads or when it has no name) and its status
 * beside the title (design-system §4.1).
 */
export function EntityHeader({
  title,
  fallback,
  crumbs,
  meta,
  description,
  actions,
}: {
  title?: string | null;
  fallback: string;
  /** Parent trail, e.g. `[{ label: "Courses", href: "/studio/courses" }]`; the current page is appended. */
  crumbs: Crumb[];
  meta?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  const name = title?.trim() || fallback;
  return <PageHeader title={name} breadcrumbs={[...crumbs, { label: name }]} meta={meta} description={description} actions={actions} />;
}

export interface EditorSection {
  id: string;
  label: string;
}

/** In-page jump links for long editors (anchors to the Card ids), 44 px tall on touch. */
export function SectionNav({ sections, label = "Jump to section" }: { sections: EditorSection[]; label?: string }) {
  return (
    <nav aria-label={label} className="-mx-1 overflow-x-auto">
      <ul className="flex gap-1 px-1">
        {sections.map((s) => (
          <li key={s.id} className="shrink-0">
            <a
              href={`#${s.id}`}
              className="inline-flex min-h-touch items-center rounded-full border border-line px-3 text-sm font-medium text-fg-secondary no-underline hover:border-brand/40 hover:bg-surface-hover hover:text-brand focus-visible:shadow-focus focus-visible:outline-none md:min-h-9"
            >
              {s.label}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}

/**
 * Save / Publish bar that stays in view at the bottom of a long editor, so authors don't scroll
 * back to the top after editing the last section. `status` is a short line (validation result,
 * "Unsaved changes") announced politely.
 */
export function StickyActionBar({ children, status, className }: { children: ReactNode; status?: ReactNode; className?: string }) {
  return (
    <div
      className={cn(
        "sticky bottom-0 z-sticky -mx-4 flex flex-col gap-2 border-t border-line bg-surface px-4 py-3 shadow-sm sm:mx-0 sm:flex-row sm:items-center sm:justify-between sm:rounded-lg sm:border",
        className,
      )}
    >
      <div role="status" aria-live="polite" className="min-w-0 text-sm">
        {status}
      </div>
      <div className="flex flex-wrap gap-2 sm:justify-end">{children}</div>
    </div>
  );
}
