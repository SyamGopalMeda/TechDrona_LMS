import Link from "next/link";
import type { ComponentProps } from "react";
import { cn } from "@/lib/ui/cn";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "danger-secondary" | "inverse" | "inverse-secondary" | "cta";
export type ButtonSize = "sm" | "md" | "lg";

/* Tech Drona website `.btn` (global.css:125-132): navy fill, white text, Plus Jakarta Sans 600,
   8px radius, 44px min height; outline = translucent white + navy/22 border + navy text. */
const variants: Record<ButtonVariant, string> = {
  primary: "bg-brand text-brand-on shadow-xs hover:bg-brand-hover active:bg-brand-active",
  secondary: "border border-brand/30 bg-surface text-brand hover:border-brand hover:bg-brand-subtle",
  ghost: "text-brand hover:bg-brand-subtle",
  danger: "bg-danger-solid text-danger-on-solid shadow-xs hover:opacity-90",
  "danger-secondary": "border border-danger-border bg-surface text-danger-fg hover:bg-danger-subtle",
  /* On the navy brand band (`bg-surface-brand`) only: primary would be navy on navy. `inverse` is the
     main action there (white fill, navy text); `inverse-secondary` is a white outline beside it. */
  inverse: "bg-fg-on-surface-brand text-surface-brand shadow-xs hover:bg-fg-on-surface-brand/90 active:bg-fg-on-surface-brand/80",
  "inverse-secondary": "border border-fg-on-surface-brand/70 bg-transparent text-fg-on-surface-brand hover:border-fg-on-surface-brand hover:bg-fg-on-surface-brand/10",
  /* Website `.header-contact-btn`: deep-green pill CTA ("Contact us", "Explore courses"). */
  cta: "bg-[#0b3b24] text-white shadow-[0_2px_10px_rgba(11,59,36,0.2)] hover:bg-[#082d1c] hover:text-white hover:shadow-[0_4px_14px_rgba(11,59,36,0.35)] motion-safe:hover:-translate-y-px",
};

const sizes: Record<ButtonSize, string> = {
  // 44px touch target below md, 36px on desktop toolbars/tables (WCAG 2.5.8; audit S6).
  sm: "h-11 px-3 text-sm md:h-9",
  md: "h-11 px-4 text-[0.9375rem]",
  lg: "min-h-touch h-12 px-6 text-base",
};

export const focusRing = "focus-visible:outline-none focus-visible:shadow-focus";

/** Class string for anything that should look like a button (e.g. a Next <Link>). */
export function buttonClasses({ variant = "primary", size = "md", className }: { variant?: ButtonVariant; size?: ButtonSize; className?: string } = {}) {
  return cn(
    /* Website .btn motion: colour fades, a 1px press on :active (transform only, motion-safe). */
    "inline-flex select-none items-center justify-center gap-2 whitespace-nowrap font-display font-semibold leading-tight no-underline transition-[color,background-color,border-color,box-shadow,transform] duration-base motion-safe:active:translate-y-px",
    variant === "cta" ? "rounded-full px-5" : "rounded-md",
    "disabled:cursor-not-allowed disabled:opacity-50 aria-disabled:cursor-not-allowed aria-disabled:opacity-50",
    focusRing,
    variants[variant],
    sizes[size],
    className,
  );
}

export interface ButtonProps extends ComponentProps<"button"> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
}

/**
 * While `loading`, the button stays focusable (aria-disabled, clicks ignored) instead of becoming
 * `disabled`, so keyboard focus is not dropped to <body> mid-request (audit S4, WCAG 2.4.3).
 */
export function Button({ variant = "primary", size = "md", loading = false, disabled, className, children, type = "button", onClick, ...props }: ButtonProps) {
  const busy = loading && !disabled;
  return (
    <button
      type={type}
      disabled={disabled}
      aria-disabled={busy || undefined}
      aria-busy={loading || undefined}
      className={buttonClasses({ variant, size, className })}
      // Only attach a handler when there is something to handle: this file is NOT "use client", and
      // server components (catalog filters, /verify form) render Button; a function prop on a host
      // element there crashes the whole route ("Event handlers cannot be passed to Client Component props").
      onClick={
        busy || onClick
          ? (e) => {
              if (busy) {
                // Also blocks implicit form submission (Enter in a field clicks the default button).
                e.preventDefault();
                return;
              }
              onClick?.(e);
            }
          : undefined
      }
      {...props}
    >
      {loading ? (
        <span aria-hidden="true" className="h-4 w-4 animate-spin rounded-full border-2 border-current border-r-transparent" />
      ) : null}
      {children}
    </button>
  );
}

export interface LinkButtonProps extends ComponentProps<typeof Link> {
  variant?: ButtonVariant;
  size?: ButtonSize;
}

/** A navigation link styled as a button (use for "go somewhere" primary actions). */
export function LinkButton({ variant = "primary", size = "md", className, ...props }: LinkButtonProps) {
  return <Link className={buttonClasses({ variant, size, className })} {...props} />;
}
