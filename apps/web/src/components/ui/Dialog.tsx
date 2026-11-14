"use client";

import { useEffect, useId, useRef, type ReactNode } from "react";
import { cn } from "@/lib/ui/cn";

export type DialogSize = "sm" | "md" | "lg" | "xl";

/* Max width from `sm` up; below `sm` every dialog is a full-width bottom sheet. */
const dialogSizes: Record<DialogSize, string> = {
  sm: "sm:max-w-md",
  md: "sm:max-w-lg",
  lg: "sm:max-w-2xl",
  xl: "sm:max-w-4xl",
};

export interface DialogProps {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  /** Action row pinned under the scrolling body: secondary "Cancel" first, primary/danger last. */
  footer?: ReactNode;
  /** Prevent closing with Escape / backdrop / × (e.g. while a request is running). */
  dismissible?: boolean;
  /** "md" (default) 32rem, "sm" 28rem, "lg" 42rem (forms), "xl" 56rem (previews, tables). */
  size?: DialogSize;
  /** Show the × close button in the corner (default true; hidden while not dismissible). */
  showClose?: boolean;
  className?: string;
}

/**
 * Modal dialog on the native <dialog> element: showModal() gives a focus trap, inert
 * background and Escape handling; focus returns to the opener on close.
 *
 * Layout: title + description at the top, a body that scrolls on its own when the content is
 * taller than the viewport, and the footer pinned at the bottom. Below `sm` it opens as a bottom
 * sheet (full width, rounded top). The × button comes last in DOM order so showModal()'s initial
 * focus still lands on the first field or action, not on "close".
 */
export function Dialog({ open, onClose, title, description, children, footer, dismissible = true, size = "md", showClose = true, className }: DialogProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const descId = useId();
  const opener = useRef<Element | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) {
      opener.current = document.activeElement;
      if (typeof el.showModal === "function") el.showModal();
      else el.setAttribute("open", "");
    } else if (!open && el.open) {
      if (typeof el.close === "function") el.close();
      else el.removeAttribute("open");
      (opener.current as HTMLElement | null)?.focus?.();
    }
  }, [open]);

  // Callers often unmount the dialog instead of setting open=false ({show ? <X open /> : null}):
  // restore focus to the opener then too (audit S5).
  const isOpen = useRef(open);
  isOpen.current = open;
  useEffect(
    () => () => {
      if (isOpen.current) (opener.current as HTMLElement | null)?.focus?.();
    },
    [],
  );

  const closable = dismissible && showClose;
  // Older callers widen the dialog with a max-w-* className: let that win over `size`.
  const customWidth = /(^|\s)max-w-/.test(className ?? "");

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      aria-describedby={description ? descId : undefined}
      onCancel={(e) => {
        e.preventDefault();
        if (dismissible) onClose();
      }}
      onClick={(e) => {
        if (dismissible && e.target === ref.current) onClose();
      }}
      className={cn(
        "w-[calc(100%-2rem)] max-h-[calc(100dvh-2rem)] flex-col overflow-hidden rounded-2xl border border-line bg-surface-raised p-0 text-fg shadow-xl open:flex backdrop:bg-scrim backdrop:backdrop-blur-[2px]",
        // Phones: bottom sheet.
        "max-sm:mb-0 max-sm:max-h-[90dvh] max-sm:w-full max-sm:max-w-none max-sm:rounded-b-none max-sm:border-x-0 max-sm:border-b-0",
        customWidth ? null : cn("max-w-lg", dialogSizes[size]),
        className,
      )}
    >
      {open ? (
        <>
          <div className={cn("shrink-0 px-6 pt-6 sm:px-7 sm:pt-7", closable && "pr-14 sm:pr-16", !children && !footer && "pb-6 sm:pb-7")}>
            <h2 id={titleId} className="font-display text-lg font-extrabold text-fg-heading">
              {title}
            </h2>
            {description ? (
              <p id={descId} className="mt-1 text-[0.9375rem] text-fg-secondary">
                {description}
              </p>
            ) : null}
          </div>
          {children ? (
            <div className={cn("min-h-0 flex-1 overflow-y-auto px-6 pt-4 sm:px-7", footer ? "pb-6" : "pb-6 sm:pb-7")}>{children}</div>
          ) : footer ? (
            <div className="pb-6" />
          ) : null}
          {footer ? (
            <div className="flex shrink-0 flex-wrap justify-end gap-2 border-t border-line-subtle bg-surface-subtle px-6 py-4 pb-[max(1rem,env(safe-area-inset-bottom))] sm:rounded-b-2xl sm:px-7">
              {footer}
            </div>
          ) : null}
          {closable ? (
            <button
              type="button"
              aria-label="Close dialog"
              onClick={onClose}
              className="absolute right-3 top-3 grid h-11 w-11 place-items-center rounded-md text-fg-muted transition-colors duration-fast hover:bg-surface-hover hover:text-fg focus-visible:shadow-focus focus-visible:outline-none sm:right-4 sm:top-4"
            >
              <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="h-5 w-5">
                <path d="M6 6l12 12M18 6 6 18" />
              </svg>
            </button>
          ) : null}
        </>
      ) : null}
    </dialog>
  );
}
