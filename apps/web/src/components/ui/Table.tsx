import type { ReactNode } from "react";
import { cn } from "@/lib/ui/cn";
import { EmptyState, ErrorState, Skeleton } from "./Display";

export interface Column<Row> {
  key: string;
  header: ReactNode;
  cell: (row: Row) => ReactNode;
  align?: "left" | "right";
  /** Visually hidden header text when `header` is an icon. */
  className?: string;
}

export interface TableProps<Row> {
  /** Accessible table name (rendered as <caption>, visually hidden unless showCaption). */
  caption: string;
  showCaption?: boolean;
  columns: Column<Row>[];
  rows: Row[] | undefined;
  rowKey: (row: Row) => string;
  loading?: boolean;
  error?: unknown;
  onRetry?: () => void;
  empty?: { title: string; description?: ReactNode; action?: ReactNode };
  loadingRows?: number;
  footer?: ReactNode;
}

/** Plain-text column label for the stacked mobile layout ("" when the header is an icon/blank). */
function headerText<Row>(c: Column<Row>): string {
  return typeof c.header === "string" || typeof c.header === "number" ? String(c.header) : "";
}

/**
 * Data table with the PRD standard states: L (skeleton rows, aria-busy), X (ErrorState
 * with request id), E (EmptyState). Horizontal scroll on narrow screens.
 */
export function Table<Row>({
  caption,
  showCaption = false,
  columns,
  rows,
  rowKey,
  loading = false,
  error,
  onRetry,
  empty = { title: "Nothing here yet" },
  loadingRows = 5,
  footer,
}: TableProps<Row>) {
  if (error) return <ErrorState error={error} onRetry={onRetry} />;
  if (!loading && rows && rows.length === 0) return <EmptyState {...empty} />;

  return (
    // Focusable, named scroll region so keyboard users can scroll a wide table (WCAG 2.1.1, axe
    // scrollable-region-focusable).
    <div
      className="relative overflow-x-auto rounded-xl border border-line bg-surface shadow-xs focus-visible:outline-none focus-visible:shadow-focus"
      role="region"
      aria-label={caption}
      tabIndex={0}
      aria-busy={loading || undefined}
    >
      {/* Below `sm` each row is a stacked card (label: value, actions visible) instead of a squeezed
          scroller (audit S1, WCAG 1.4.10). Explicit roles keep table semantics when display changes. */}
      <table role="table" className="w-full border-collapse text-left text-sm max-sm:block">
        <caption className={showCaption ? "px-4 pb-1 pt-4 text-left font-display font-bold text-fg-heading" : "sr-only"}>{caption}</caption>
        <thead role="rowgroup" className="border-b border-line bg-surface-subtle text-xs uppercase tracking-[0.06em] text-fg-muted max-sm:sr-only">
          <tr role="row">
            {columns.map((c) => (
              <th key={c.key} role="columnheader" scope="col" className={cn("whitespace-nowrap px-4 py-3 font-display font-bold", c.align === "right" && "text-right", c.className)}>
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody role="rowgroup" className="max-sm:block">
          {loading || !rows
            ? Array.from({ length: loadingRows }, (_, i) => (
                <tr key={`sk-${i}`} role="row" className="border-t border-line-subtle max-sm:block max-sm:px-4 max-sm:py-3">
                  {columns.map((c) => (
                    <td key={c.key} role="cell" className="px-4 py-3 max-sm:block max-sm:px-0 max-sm:py-1">
                      <Skeleton className="h-4 w-full max-w-[12rem]" />
                    </td>
                  ))}
                </tr>
              ))
            : rows.map((row) => (
                <tr key={rowKey(row)} role="row" className="border-t border-line-subtle transition-colors duration-fast first:border-t-0 hover:bg-surface-hover max-sm:block max-sm:px-4 max-sm:py-3">
                  {columns.map((c) => (
                    <td
                      key={c.key}
                      role="cell"
                      data-label={headerText(c)}
                      className={cn(
                        "px-4 py-3.5 align-middle text-fg",
                        "max-sm:flex max-sm:min-h-[2rem] max-sm:flex-wrap max-sm:items-center max-sm:justify-between max-sm:gap-x-3 max-sm:gap-y-1 max-sm:px-0 max-sm:py-1",
                        "max-sm:before:shrink-0 max-sm:before:text-xs max-sm:before:font-semibold max-sm:before:uppercase max-sm:before:tracking-[0.06em] max-sm:before:text-fg-muted max-sm:before:content-[attr(data-label)]",
                        c.align === "right" && "text-right tabular-nums",
                      )}
                    >
                      {c.cell(row)}
                    </td>
                  ))}
                </tr>
              ))}
        </tbody>
      </table>
      {loading ? <span className="sr-only">Loading…</span> : null}
      {footer ? <div className="border-t border-line-subtle px-4 pb-3">{footer}</div> : null}
    </div>
  );
}
