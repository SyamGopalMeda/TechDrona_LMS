"use client";

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { cn } from "@/lib/ui/cn";

export type ToastTone = "info" | "success" | "warning" | "danger";

export interface ToastInput {
  title: string;
  description?: string;
  tone?: ToastTone;
  /** Shown as "Reference: ..." so users can quote it to support. */
  requestId?: string | null;
  /** ms; 0 = sticky. Errors default to sticky. */
  duration?: number;
}

interface ToastItem extends ToastInput {
  id: number;
}

export interface ToastApi {
  show: (t: ToastInput) => number;
  dismiss: (id: number) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

/* White card with a coloured edge + tone icon (title in the tone's text colour). */
const tones: Record<ToastTone, { edge: string; title: string; icon: string; glyph: string }> = {
  info: { edge: "border-l-info-border", title: "text-info-fg", icon: "bg-info-solid text-info-on-solid", glyph: "i" },
  success: { edge: "border-l-success-border", title: "text-success-fg", icon: "bg-success-solid text-success-on-solid", glyph: "✓" },
  warning: { edge: "border-l-warning-border", title: "text-warning-fg", icon: "bg-warning-solid text-warning-on-solid", glyph: "!" },
  danger: { edge: "border-l-danger-border", title: "text-danger-fg", icon: "bg-danger-solid text-danger-on-solid", glyph: "!" },
};

let nextId = 1;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const dismiss = useCallback((id: number) => setItems((xs) => xs.filter((x) => x.id !== id)), []);
  const show = useCallback(
    (t: ToastInput) => {
      const id = nextId++;
      setItems((xs) => [...xs.slice(-4), { ...t, id }]);
      const duration = t.duration ?? (t.tone === "danger" ? 0 : 6000);
      if (duration > 0) setTimeout(() => dismiss(id), duration);
      return id;
    },
    [dismiss],
  );
  const api = useMemo(() => ({ show, dismiss }), [show, dismiss]);

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div
        aria-live="polite"
        className="pointer-events-none fixed inset-x-0 bottom-0 z-toast flex flex-col items-center gap-2 p-4 sm:items-end"
      >
        {items.map((t) => (
          <div
            key={t.id}
            role={t.tone === "danger" ? "alert" : "status"}
            className={cn("pointer-events-auto w-full max-w-sm rounded-xl border border-l-4 border-line bg-surface-raised p-4 shadow-lg", tones[t.tone ?? "info"].edge)}
          >
            <div className="flex items-start gap-3">
              <span aria-hidden="true" className={cn("mt-px grid h-5 w-5 shrink-0 place-items-center rounded-full text-[0.6875rem] font-bold", tones[t.tone ?? "info"].icon)}>
                {tones[t.tone ?? "info"].glyph}
              </span>
              <div className="min-w-0 flex-1">
                <p className={cn("font-display text-sm font-bold", tones[t.tone ?? "info"].title)}>{t.title}</p>
                {t.description ? <p className="mt-1 text-sm text-fg-secondary">{t.description}</p> : null}
                {t.requestId ? <p className="mt-1 font-mono text-xs text-fg-muted">Reference: {t.requestId}</p> : null}
              </div>
              <button
                type="button"
                onClick={() => dismiss(t.id)}
                className="-m-1 grid h-7 w-7 place-items-center rounded-md text-lg leading-none text-fg-muted hover:bg-surface-hover hover:text-fg focus-visible:shadow-focus focus-visible:outline-none"
                aria-label="Dismiss notification"
              >
                <span aria-hidden="true">×</span>
              </button>
            </div>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used inside <ToastProvider>");
  return ctx;
}
