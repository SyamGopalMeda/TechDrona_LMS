"use client";

import { useId, type FormEvent, type ReactNode } from "react";
import { cn } from "@/lib/ui/cn";

/* ---------------------------------------------------------------- FilterBar */

export interface FilterBarProps {
  /** FormFields (Select, Input, search box…). */
  children: ReactNode;
  /** Accessible name of the search landmark. */
  label?: string;
  /** Controls per row from `lg` up (2 per row from `sm`, 1 on phones). Default 4. */
  columns?: 2 | 3 | 4;
  /** Buttons at the end of the bar (e.g. "Clear filters"); aligned to the bottom of the fields. */
  actions?: ReactNode;
  /** Optional submit handler (default: filters apply as they change, so submit is prevented). */
  onSubmit?: (e: FormEvent<HTMLFormElement>) => void;
  /** "card" (default) is a bordered box; "plain" has no box, for use in a Table toolbar or Card. */
  variant?: "card" | "plain";
  className?: string;
}

/** Responsive row of filter controls (a `search` landmark); children are FormFields. */
export function FilterBar({ children, label = "Filters", columns = 4, actions, onSubmit, variant = "card", className }: FilterBarProps) {
  return (
    <form
      role="search"
      aria-label={label}
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit?.(e);
      }}
      className={cn(
        "grid grid-cols-1 items-end gap-3 sm:grid-cols-2",
        columns === 4 && "lg:grid-cols-4",
        columns === 3 && "lg:grid-cols-3",
        variant === "card" ? "mb-4 rounded-xl border border-line bg-surface p-4" : null,
        className,
      )}
    >
      {children}
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </form>
  );
}

/* ---------------------------------------------------------------- Segmented */

export interface SegmentOption<V extends string> {
  value: V;
  label: string;
  hint?: string;
  disabled?: boolean;
}

export interface SegmentedProps<V extends string> {
  /** Visible group label (fieldset legend). */
  legend: string;
  /** Visually hide the legend (it is still announced). */
  hideLegend?: boolean;
  name: string;
  value: V;
  options: SegmentOption<V>[];
  onChange: (v: V) => void;
  /**
   * "cards" (default): side-by-side option cards with an optional hint, for settings choices.
   * "pills": a compact segmented control (one row of joined buttons), for view switches/filters.
   */
  variant?: "cards" | "pills";
  className?: string;
}

/** Single choice as a native radio group (arrow keys work), styled as cards or a segmented control. */
export function Segmented<V extends string>({ legend, hideLegend, name, value, options, onChange, variant = "cards", className }: SegmentedProps<V>) {
  const id = useId();
  const pills = variant === "pills";
  return (
    <fieldset className={cn("min-w-0 space-y-1.5", className)}>
      <legend className={cn(hideLegend ? "sr-only" : "mb-1.5 text-sm font-medium text-fg")}>{legend}</legend>
      <div className={pills ? "inline-flex max-w-full overflow-x-auto rounded-lg border border-line-control bg-surface p-1" : "grid gap-2 sm:grid-cols-2"}>
        {options.map((o) => {
          const checked = o.value === value;
          const inputId = `${id}-${o.value}`;
          return (
            <label
              key={o.value}
              htmlFor={inputId}
              className={cn(
                "cursor-pointer transition-colors duration-fast focus-within:shadow-focus",
                o.disabled && "cursor-not-allowed opacity-50",
                pills
                  ? cn(
                      "inline-flex min-h-touch shrink-0 items-center justify-center whitespace-nowrap rounded-md px-3 font-display text-sm font-semibold md:min-h-9",
                      checked ? "bg-brand text-brand-on" : "text-fg-secondary hover:bg-surface-hover hover:text-brand",
                    )
                  : cn(
                      "flex items-start gap-3 rounded-lg border p-3 text-[0.9375rem]",
                      checked ? "border-brand bg-brand-subtle" : "border-line-control bg-surface hover:bg-surface-hover",
                    ),
              )}
            >
              <input
                id={inputId}
                type="radio"
                name={`${name}-${id}`}
                value={o.value}
                checked={checked}
                disabled={o.disabled}
                onChange={() => onChange(o.value)}
                className={pills ? "sr-only" : "mt-1 h-4 w-4 shrink-0 accent-[var(--td-brand)] focus-visible:outline-none"}
              />
              {pills ? (
                o.label
              ) : (
                <span>
                  <span className="block font-medium text-fg">{o.label}</span>
                  {o.hint ? <span className="block text-sm text-fg-muted">{o.hint}</span> : null}
                </span>
              )}
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

/* --------------------------------------------------------------------- Chip */

export interface ChipProps {
  /** Pressed state (aria-pressed). */
  active: boolean;
  onClick: () => void;
  children: ReactNode;
  /** Optional count shown after the label. */
  count?: number;
  disabled?: boolean;
  className?: string;
}

/** Toggle chip for quick filters (type, subject, tag). 44px tall on touch, 36px from `md`. */
export function Chip({ active, onClick, children, count, disabled, className }: ChipProps) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "inline-flex min-h-touch items-center gap-1.5 rounded-full border px-3.5 text-sm transition-colors duration-fast focus-visible:shadow-focus focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50 md:min-h-9",
        active ? "border-brand bg-brand-subtle font-semibold text-brand-on-subtle" : "border-line-control bg-surface text-fg-secondary hover:bg-surface-hover hover:text-brand",
        className,
      )}
    >
      {children}
      {count !== undefined ? <span className="text-xs tabular-nums opacity-80">{count}</span> : null}
    </button>
  );
}
