import { isValidElement, type ReactNode } from "react";
import { cn } from "@/lib/ui/cn";
import { EmptyState, ErrorState, Skeleton, type EmptyStateProps } from "./Display";

export interface Column<Row> {
  key: string;
  header: ReactNode;
  cell: (row: Row) => ReactNode;
  align?: "left" | "right";
  /** Visually hidden header text when `header` is an icon. */
  className?: string;
  /**
   * "secondary" columns are hidden between `sm` and `lg` (tablet widths) so the important ones
   * fit without sideways scrolling; they still show on desktop and in the stacked phone layout.
   */
  priority?: "primary" | "secondary";
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
  empty?: { title: string; description?: ReactNode; action?: ReactNode; icon?: EmptyStateProps["icon"] };
  loadingRows?: number;
  footer?: ReactNode;
  /**
   * Filters / search / bulk actions shown above the table, inside its frame. It stays visible in
   * the empty and error states so people can change the filters that produced "no results".
   */
  toolbar?: ReactNode;
  /** Keep the header row visible while the table body scrolls (the table gets its own max height). */
  stickyHeader?: boolean;
}

/** Plain-text column label for the stacked mobile layout ("" when the header is an icon/blank). */
function headerText<Row>(c: Column<Row>): string {
  return typeof c.header === "string" || typeof c.header === "number" ? String(c.header) : "";
}

/** A cell with nothing to say ("—", empty, null) is dropped from the stacked phone card. */
function isBlank(content: ReactNode): boolean {
  if (content === null || content === undefined || content === false || content === "") return true;
  if (typeof content === "string") return content.trim() === "" || content.trim() === "—";
  if (isValidElement(content)) return false;
  return false;
}

const secondaryCol = "sm:max-lg:hidden";

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
  toolbar,
  stickyHeader = false,
}: TableProps<Row>) {
  const toolbarEl = toolbar ? <div className="border-b border-line-subtle px-4 py-3">{toolbar}</div> : null;
  // Visible title above the table. The <caption> itself stays sr-only: a visible caption inside a
  // table that turns `display: block` on phones shrinks to a narrow column (audit 1.10).
  // In the empty/error states there is no <table>, so the title is then read out normally.
  const title = (hidden: boolean) =>
    showCaption ? (
      <p aria-hidden={hidden || undefined} className="px-4 pb-1 pt-4 font-display font-bold text-fg-heading">
        {caption}
      </p>
    ) : null;

  if (error || (!loading && rows && rows.length === 0)) {
    const state = error ? <ErrorState error={error} onRetry={onRetry} /> : <EmptyState {...empty} variant={toolbar || showCaption ? "inline" : "card"} />;
    if (!toolbar && !showCaption) return state;
    return (
      <div className="rounded-xl border border-line bg-surface shadow-xs">
        {title(false)}
        {toolbarEl}
        <div className={error ? "p-4" : undefined}>{state}</div>
      </div>
    );
  }

  const framed = Boolean(toolbar) || showCaption;
  const footerEl = footer ? <div className="border-t border-line-subtle px-4 pb-3">{footer}</div> : null;

  const region = (
      /* Focusable, named scroll region so keyboard users can scroll a wide table (WCAG 2.1.1, axe
         scrollable-region-focusable). */
      <div
        className={cn(
          "relative overflow-x-auto focus-visible:outline-none focus-visible:shadow-focus",
          framed ? "rounded-b-xl" : "rounded-xl border border-line bg-surface shadow-xs",
          stickyHeader && "max-h-[70dvh] overflow-y-auto",
        )}
        role="region"
        aria-label={caption}
        tabIndex={0}
        aria-busy={loading || undefined}
      >
        {/* Below `sm` each row is a stacked card (label: value, actions visible) instead of a squeezed
            scroller (audit S1, WCAG 1.4.10). Explicit roles keep table semantics when display changes. */}
        <table role="table" className="w-full border-collapse text-left text-[0.9375rem] max-sm:block">
          <caption className="sr-only">{caption}</caption>
          <thead
            role="rowgroup"
            className={cn(
              "border-b border-line bg-surface-subtle text-xs uppercase tracking-[0.06em] text-fg-muted max-sm:sr-only",
              stickyHeader && "sticky top-0 z-raised",
            )}
          >
            <tr role="row">
              {columns.map((c) => (
                <th
                  key={c.key}
                  role="columnheader"
                  scope="col"
                  className={cn(
                    "whitespace-nowrap px-4 py-3 font-display font-bold",
                    stickyHeader && "bg-surface-subtle",
                    c.align === "right" && "text-right",
                    c.priority === "secondary" && secondaryCol,
                    c.className,
                  )}
                >
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
                      <td key={c.key} role="cell" className={cn("px-4 py-3 max-sm:block max-sm:px-0 max-sm:py-1", c.priority === "secondary" && secondaryCol)}>
                        <Skeleton className="h-4 w-full max-w-[12rem]" />
                      </td>
                    ))}
                  </tr>
                ))
              : rows.map((row) => (
                  <tr key={rowKey(row)} role="row" className="border-t border-line-subtle transition-colors duration-fast first:border-t-0 hover:bg-surface-hover max-sm:block max-sm:px-4 max-sm:py-3">
                    {columns.map((c) => {
                      const content = c.cell(row);
                      return (
                        <td
                          key={c.key}
                          role="cell"
                          data-label={headerText(c)}
                          className={cn(
                            "px-4 py-3.5 align-middle text-fg",
                            "max-sm:flex max-sm:min-h-[2rem] max-sm:flex-wrap max-sm:items-center max-sm:justify-between max-sm:gap-x-3 max-sm:gap-y-1 max-sm:px-0 max-sm:py-1",
                            "max-sm:before:shrink-0 max-sm:before:text-xs max-sm:before:font-semibold max-sm:before:uppercase max-sm:before:tracking-[0.06em] max-sm:before:text-fg-muted max-sm:before:content-[attr(data-label)]",
                            c.align === "right" && "text-right tabular-nums",
                            c.priority === "secondary" && secondaryCol,
                            isBlank(content) && "max-sm:hidden",
                          )}
                        >
                          {content}
                        </td>
                      );
                    })}
                  </tr>
                ))}
          </tbody>
        </table>
        {loading ? <span className="sr-only">Loading…</span> : null}
        {framed ? null : footerEl}
      </div>
  );

  if (!framed) return region;
  return (
    <div className="rounded-xl border border-line bg-surface shadow-xs">
      {title(true)}
      {toolbarEl}
      {region}
      {footerEl}
    </div>
  );
}
