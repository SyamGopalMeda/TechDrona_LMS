import type { ComponentProps } from "react";
import { cn } from "@/lib/ui/cn";

/* Website `.field input` (global.css:180-182): white, 1px border, 8px radius, navy border + soft
   navy halo on focus. Border uses line-control (#737C91) instead of the site's #d6d3cb so the
   control boundary meets WCAG 1.4.11 (3:1). */
export const controlBase =
  "block w-full rounded-md border bg-surface px-3.5 text-[0.9375rem] text-fg shadow-xs transition-colors duration-fast placeholder:text-fg-muted hover:border-fg-secondary disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-fg-disabled";

/** Focus treatment for text controls: navy border + 2-ring focus shadow (always on focus, not only keyboard). */
export const controlFocus = "focus:border-brand focus:shadow-focus focus:outline-none";

export const controlBorder = (invalid: boolean) => (invalid ? "border-danger-border" : "border-line-control");

export function isInvalid(value: unknown): boolean {
  return value === true || value === "true";
}

export function Input({ className, ...props }: ComponentProps<"input">) {
  return <input className={cn(controlBase, "h-11", controlBorder(isInvalid(props["aria-invalid"])), controlFocus, className)} {...props} />;
}

/** Multi-line text control with the same look as Input. */
export function Textarea({ className, rows = 4, ...props }: ComponentProps<"textarea">) {
  return (
    <textarea
      rows={rows}
      className={cn(controlBase, "py-2.5 leading-relaxed", controlBorder(isInvalid(props["aria-invalid"])), controlFocus, className)}
      {...props}
    />
  );
}
