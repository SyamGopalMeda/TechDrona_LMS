/**
 * Modals, drawers (bottom sheets on phones), confirm dialogs and toasts (components.js modal / drawer / confirm /
 * toast). They render into the portal's overlay root (inside `.tdp`), trap focus, close on Esc / backdrop /
 * the × button and give focus back to what opened them.
 *
 *   const [open, setOpen] = useState(false);
 *   <Modal open={open} title="Add a person" onClose={() => setOpen(false)} footer={<…buttons…/>}>…</Modal>
 *   <Drawer open={open} title="Branch details" onClose={…}>…</Drawer>
 *
 *   if (await confirm({ title: "Deactivate this lead?", text: "…", confirmLabel: "Deactivate", danger: true })) …
 *   toast("Saved", "good");                // anywhere (plain function); shown by <OverlayHost/> in the shell
 *
 * Not ported: the old "Back closes the top overlay" history entries (they would fight React Router's history).
 */
import { useEffect, useId, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Button } from "./Button";
import { cx, useOverlayRoot, usePortalUi } from "./context";
import { Icon } from "./Icon";

const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]):not([type="hidden"]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';

/** Open overlays, innermost last (Esc and Tab belong to the top one). */
const stack: HTMLElement[] = [];

function lockScroll(on: boolean): void {
  if (typeof document === "undefined") return;
  document.body.style.overflow = on ? "hidden" : "";
}

export interface OverlayProps {
  open: boolean;
  title: ReactNode;
  onClose: () => void;
  children?: ReactNode;
  /** footer (buttons) — modal only; a drawer puts its actions in the body */
  footer?: ReactNode;
  wide?: boolean;
  /** form dialogs get the taller phone sheet (td-modal--form) */
  form?: boolean;
  /** compact width for short confirmations */
  compact?: boolean;
}

function OverlayFrame({ kind, open, title, onClose, children, footer, wide, form, compact }: OverlayProps & { kind: "modal" | "drawer" }) {
  const root = useOverlayRoot();
  const { coarse } = usePortalUi();
  const titleId = useId();
  const panel = useRef<HTMLDivElement>(null);
  const [shown, setShown] = useState(false);
  const close = useRef(onClose);
  close.current = onClose;

  useEffect(() => {
    if (!open) return;
    const el = panel.current;
    if (!el) return;
    const returnTo = document.activeElement as HTMLElement | null;
    stack.push(el);
    lockScroll(true);
    const raf = requestAnimationFrame(() => {
      setShown(true);
      const explicit = el.querySelector<HTMLElement>("[autofocus],[data-autofocus]");
      const auto = explicit ?? (coarse ? null : el.querySelector<HTMLElement>(`.td-${kind}__body input:not([type=hidden]):not([type=checkbox]), .td-${kind}__body select, .td-${kind}__body textarea`));
      (auto ?? el).focus({ preventScroll: !auto });
    });
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (stack[stack.length - 1] !== el) return;
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        close.current();
        return;
      }
      if (e.key !== "Tab") return;
      const f = [...el.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((x) => x.offsetParent !== null || x === document.activeElement);
      if (!f.length) {
        e.preventDefault();
        el.focus();
        return;
      }
      const first = f[0]!;
      const last = f[f.length - 1]!;
      if (!el.contains(document.activeElement)) {
        e.preventDefault();
        first.focus();
      } else if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey, true);
    return () => {
      cancelAnimationFrame(raf);
      document.removeEventListener("keydown", onKey, true);
      const i = stack.indexOf(el);
      if (i >= 0) stack.splice(i, 1);
      if (!stack.length) lockScroll(false);
      setShown(false);
      if (returnTo && document.contains(returnTo)) returnTo.focus();
    };
  }, [open, kind, coarse]);

  if (!open || !root) return null;
  return createPortal(
    <div
      className={cx("td-overlay", `td-overlay--${kind}`, shown && "is-open")}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={panel}
        className={cx(`td-${kind}`, wide && `td-${kind}--wide`, form && `td-${kind}--form`, kind === "modal" && compact && !form && "td-modal--compact")}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
      >
        {kind === "drawer" ? <div className="td-drawer__grab" aria-hidden="true" /> : null}
        <header className={`td-${kind}__head`}>
          <h2 id={titleId} className={`td-${kind}__title`}>
            {title}
          </h2>
          <Button icon="close" tone="ghost" ariaLabel="Close" onClick={onClose} />
        </header>
        <div className={`td-${kind}__body`}>{children}</div>
        {footer ?? null}
      </div>
    </div>,
    root,
  );
}

export function Modal(props: OverlayProps) {
  return <OverlayFrame kind="modal" {...props} footer={props.footer ? <footer className="td-modal__foot">{props.footer}</footer> : null} />;
}

export function Drawer(props: Omit<OverlayProps, "footer">) {
  return <OverlayFrame kind="drawer" {...props} />;
}

/* ------------------------------------------------------------------ imperative confirm + toasts */

interface ConfirmReq {
  id: number;
  title: ReactNode;
  text?: ReactNode;
  body?: ReactNode;
  confirmLabel: string;
  cancelLabel: string;
  tone: "danger" | "primary";
  resolve: (ok: boolean) => void;
}

export type ToastTone = "good" | "bad" | "warn" | "info" | "neutral" | "brand";
interface ToastItem {
  id: number;
  msg: string;
  tone: ToastTone;
}

let seq = 0;
let confirms: ConfirmReq[] = [];
let toasts: ToastItem[] = [];
const listeners = new Set<() => void>();
let version = 0;
const notify = () => {
  version += 1;
  listeners.forEach((l) => l());
};
const subscribe = (fn: () => void) => {
  listeners.add(fn);
  return () => listeners.delete(fn);
};

/** Ask a yes/no question; resolves false on Cancel, Esc or ×. Danger tone unless `danger: false`. */
export function confirm(opts: { title?: ReactNode; text?: ReactNode; body?: ReactNode; confirmLabel?: string; cancelLabel?: string; danger?: boolean; tone?: "danger" | "primary" }): Promise<boolean> {
  return new Promise((resolve) => {
    confirms = [
      ...confirms,
      {
        id: ++seq,
        title: opts.title ?? "Are you sure?",
        text: opts.text,
        body: opts.body,
        confirmLabel: opts.confirmLabel ?? "Confirm",
        cancelLabel: opts.cancelLabel ?? "Cancel",
        tone: opts.tone ?? (opts.danger === false ? "primary" : "danger"),
        resolve,
      },
    ];
    notify();
  });
}

const timers = new Map<number, ReturnType<typeof setTimeout>>();
function dismiss(id: number): void {
  clearTimeout(timers.get(id));
  timers.delete(id);
  toasts = toasts.filter((t) => t.id !== id);
  notify();
}
function arm(id: number, ms: number): void {
  clearTimeout(timers.get(id));
  timers.set(
    id,
    setTimeout(() => dismiss(id), ms),
  );
}

/** Short message in the corner (bottom on phones). Bad toasts stay 7 s, others 4.2 s; the same message replaces itself. */
export function toast(msg: string, tone: ToastTone = "neutral"): void {
  const text = String(msg ?? "");
  const id = ++seq;
  toasts = [...toasts.filter((t) => t.msg !== text), { id, msg: text, tone }].slice(-4);
  notify();
  arm(id, tone === "bad" ? 7000 : 4200);
}

const TOAST_ICON: Record<ToastTone, string> = { good: "check", bad: "warn", warn: "warn", info: "info", neutral: "info", brand: "sparkle" };

function ConfirmView({ req }: { req: ConfirmReq }) {
  const answer = (ok: boolean) => {
    confirms = confirms.filter((c) => c.id !== req.id);
    notify();
    req.resolve(ok);
  };
  return (
    <Modal
      open
      compact
      title={req.title}
      onClose={() => answer(false)}
      footer={
        <>
          <Button tone="ghost" onClick={() => answer(false)}>
            {req.cancelLabel}
          </Button>
          <Button tone={req.tone} onClick={() => answer(true)}>
            {req.confirmLabel}
          </Button>
        </>
      }
    >
      <div className="td-confirm">
        {req.text ? <p className="td-muted">{req.text}</p> : null}
        {req.body}
      </div>
    </Modal>
  );
}

/** Renders pending confirms and the toast region. PortalLayout mounts one; tests can mount it too. */
export function OverlayHost() {
  useSyncExternalStore(
    subscribe,
    () => version,
    () => 0,
  );
  const root = useOverlayRoot();
  return (
    <>
      {confirms.map((c) => (
        <ConfirmView key={c.id} req={c} />
      ))}
      {root
        ? createPortal(
            <div className="td-toasts" aria-live="polite">
              {toasts.map((t) => (
                <div
                  key={t.id}
                  className={cx("td-toast", `td-toast--${t.tone}`)}
                  role={t.tone === "bad" ? "alert" : "status"}
                  onMouseEnter={() => clearTimeout(timers.get(t.id))}
                  onMouseLeave={() => arm(t.id, 2500)}
                >
                  <Icon name={TOAST_ICON[t.tone]} size={18} />
                  <span className="td-toast__msg">{t.msg}</span>
                  <Button icon="close" tone="ghost" size="sm" ariaLabel="Dismiss" onClick={() => dismiss(t.id)} />
                </div>
              ))}
            </div>,
            root,
          )
        : null}
    </>
  );
}

/** Tests only. */
export function resetOverlaysForTests(): void {
  confirms = [];
  toasts = [];
  timers.forEach((t) => clearTimeout(t));
  timers.clear();
  notify();
}
