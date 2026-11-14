import type { ReactNode } from "react";
import { cn } from "@/lib/ui/cn";

/* Server-safe layout primitives (no hooks, no handlers). */

/* ----------------------------------------------------------- PageContainer */

/**
 * Named page widths from the layout tokens (packages/design-tokens `layout.container.*`):
 * - `prose`   45rem — reading, forms, settings, single-column flows
 * - `content` 72rem — the default for portal pages (lists, dashboards)
 * - `wide`    90rem — data-heavy pages (wide tables, College Data Portal)
 * - `full`    no cap — fill whatever the shell gives you
 */
export type PageWidth = "prose" | "content" | "wide" | "full";

export const PAGE_WIDTHS: Record<PageWidth, string> = {
  prose: "max-w-prose",
  content: "max-w-content",
  wide: "max-w-wide",
  full: "max-w-none",
};

/** Class string for a named page width (for elements that can't be wrapped in PageContainer). */
export function pageWidthClass(width: PageWidth = "content"): string {
  return PAGE_WIDTHS[width];
}

/**
 * Constrains a page (or a section of one) to a named width so pages stop changing width as users
 * move between them. `align="start"` keeps it left-aligned under the PageHeader instead of centred.
 */
export function PageContainer({
  width = "content",
  align = "start",
  className,
  children,
}: {
  width?: PageWidth;
  align?: "start" | "center";
  className?: string;
  children: ReactNode;
}) {
  return <div className={cn("w-full", PAGE_WIDTHS[width], align === "center" && "mx-auto", className)}>{children}</div>;
}

/* ------------------------------------------------------------ KeyValueList */

export interface KeyValueItem {
  label: string;
  /** null/undefined/"" renders an em dash. */
  value: ReactNode;
  /** Stable key when labels repeat (defaults to the label). */
  key?: string;
  /** Span the full row (long text, addresses, notes). */
  wide?: boolean;
}

/**
 * Description list for "label: value" facts about one record (order, user, case). Stacks to one
 * column on phones; `columns` applies from `sm` up.
 */
export function KeyValueList({ items, columns = 2, className }: { items: KeyValueItem[]; columns?: 1 | 2 | 3; className?: string }) {
  return (
    <dl
      className={cn(
        "grid grid-cols-1 gap-x-6 gap-y-3 text-[0.9375rem]",
        columns === 2 && "sm:grid-cols-2",
        columns === 3 && "sm:grid-cols-2 lg:grid-cols-3",
        className,
      )}
    >
      {items.map((it) => (
        <div key={it.key ?? it.label} className={cn("min-w-0", it.wide && columns > 1 && "sm:col-span-full")}>
          <dt className="text-xs font-semibold uppercase tracking-wide text-fg-muted">{it.label}</dt>
          <dd className="mt-0.5 break-words text-fg">{it.value === null || it.value === undefined || it.value === "" ? "—" : it.value}</dd>
        </div>
      ))}
    </dl>
  );
}
