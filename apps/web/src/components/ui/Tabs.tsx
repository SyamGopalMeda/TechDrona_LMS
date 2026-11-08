"use client";

import { useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { cn } from "@/lib/ui/cn";

export interface TabItem {
  id: string;
  label: ReactNode;
  content: ReactNode;
  disabled?: boolean;
}

export interface TabsProps {
  items: TabItem[];
  label: string;
  defaultValue?: string;
  value?: string;
  onValueChange?: (id: string) => void;
}

/**
 * WAI-ARIA tabs (automatic activation): Left/Right/Home/End move between tabs, roving
 * tabindex, panels labelled by their tab.
 */
export function Tabs({ items, label, defaultValue, value, onValueChange }: TabsProps) {
  const base = useId();
  const [internal, setInternal] = useState(defaultValue ?? items[0]?.id);
  const active = value ?? internal;
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});
  const enabled = items.filter((i) => !i.disabled);

  const select = (id: string) => {
    if (value === undefined) setInternal(id);
    onValueChange?.(id);
    refs.current[id]?.focus();
  };

  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>) => {
    const idx = enabled.findIndex((i) => i.id === active);
    let next: TabItem | undefined;
    if (e.key === "ArrowRight") next = enabled[(idx + 1) % enabled.length];
    else if (e.key === "ArrowLeft") next = enabled[(idx - 1 + enabled.length) % enabled.length];
    else if (e.key === "Home") next = enabled[0];
    else if (e.key === "End") next = enabled[enabled.length - 1];
    if (next) {
      e.preventDefault();
      select(next.id);
    }
  };

  return (
    <div>
      <div role="tablist" aria-label={label} className="flex gap-1 overflow-x-auto border-b border-line">
        {items.map((item) => {
          const selected = item.id === active;
          return (
            <button
              key={item.id}
              ref={(el) => {
                refs.current[item.id] = el;
              }}
              id={`${base}-tab-${item.id}`}
              type="button"
              role="tab"
              aria-selected={selected}
              aria-controls={`${base}-panel-${item.id}`}
              tabIndex={selected ? 0 : -1}
              disabled={item.disabled}
              onClick={() => select(item.id)}
              onKeyDown={onKeyDown}
              className={cn(
                "-mb-px min-h-touch whitespace-nowrap rounded-t-md border-b-2 px-3.5 py-2 font-display text-sm font-semibold transition-colors duration-fast focus-visible:shadow-focus focus-visible:outline-none",
                selected ? "border-brand text-brand" : "border-transparent text-fg-secondary hover:border-line-strong hover:text-fg",
                "disabled:cursor-not-allowed disabled:text-fg-disabled",
              )}
            >
              {item.label}
            </button>
          );
        })}
      </div>
      {items.map((item) => (
        <div
          key={item.id}
          role="tabpanel"
          id={`${base}-panel-${item.id}`}
          aria-labelledby={`${base}-tab-${item.id}`}
          hidden={item.id !== active}
          tabIndex={0}
          className="pt-5 focus-visible:shadow-focus focus-visible:outline-none"
        >
          {item.id === active ? item.content : null}
        </div>
      ))}
    </div>
  );
}
