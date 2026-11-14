/**
 * What the shared UI needs from the portal shell: where overlays render (inside the `.tdp` root, so the scoped
 * CSS applies), the device class and whether the session may write. PortalLayout provides it; outside the
 * portal (tests) the defaults apply: overlays go to document.body, desktop, writable.
 */
import { createContext, useContext, type ReactNode } from "react";
import type { FormFactor } from "../lib/prefs";

export interface PortalUi {
  /** container for modals, drawers, menus and toasts (a child of the `.tdp` root) */
  overlayRoot: HTMLElement | null;
  form: FormFactor;
  coarse: boolean;
  canWrite: boolean;
}

const PortalUiContext = createContext<PortalUi>({ overlayRoot: null, form: "desktop", coarse: false, canWrite: true });

export function PortalUiProvider({ value, children }: { value: PortalUi; children: ReactNode }) {
  return <PortalUiContext value={value}>{children}</PortalUiContext>;
}

export function usePortalUi(): PortalUi {
  return useContext(PortalUiContext);
}

/** The element overlays portal into. */
export function useOverlayRoot(): HTMLElement | null {
  const { overlayRoot } = usePortalUi();
  return overlayRoot ?? (typeof document !== "undefined" ? document.body : null);
}

/** `<WriteOnly>` renders its children only for sessions that may write (hidden for viewers). */
export function WriteOnly({ children }: { children: ReactNode }) {
  return usePortalUi().canWrite ? <>{children}</> : null;
}

/** className helper: cx("a", cond && "b", undefined) → "a b" */
export function cx(...parts: (string | false | null | undefined | 0)[]): string {
  return parts.filter(Boolean).join(" ");
}
