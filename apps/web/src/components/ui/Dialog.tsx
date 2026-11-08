"use client";

import { useEffect, useId, useRef, type ReactNode } from "react";
import { cn } from "@/lib/ui/cn";

export interface DialogProps {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  /** Prevent closing with Escape / backdrop (e.g. while a request is running). */
  dismissible?: boolean;
  className?: string;
}

/**
 * Modal dialog on the native <dialog> element: showModal() gives a focus trap, inert
 * background and Escape handling; focus returns to the opener on close.
 */
export function Dialog({ open, onClose, title, description, children, footer, dismissible = true, className }: DialogProps) {
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
        "w-[calc(100%-2rem)] max-w-lg rounded-2xl border border-line bg-surface-raised p-0 text-fg shadow-xl backdrop:bg-scrim backdrop:backdrop-blur-[2px]",
        className,
      )}
    >
      {open ? (
        <div className="p-6 sm:p-7">
          <h2 id={titleId} className="font-display text-lg font-extrabold text-fg-heading">
            {title}
          </h2>
          {description ? (
            <p id={descId} className="mt-1 text-sm text-fg-secondary">
              {description}
            </p>
          ) : null}
          {children ? <div className="mt-4">{children}</div> : null}
          {footer ? <div className="-mx-6 -mb-6 mt-6 flex flex-wrap justify-end gap-2 rounded-b-2xl border-t border-line-subtle bg-surface-subtle px-6 py-4 sm:-mx-7 sm:-mb-7 sm:px-7">{footer}</div> : null}
        </div>
      ) : null}
    </dialog>
  );
}
