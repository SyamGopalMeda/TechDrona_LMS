/**
 * Per-browser portal preferences and the device class, as in the old portal:
 *  - theme: localStorage `td.theme` ('light' | 'dark'), else the OS preference (followed live while no choice is saved);
 *  - sidebar collapsed: localStorage `td.nav` = 'collapsed';
 *  - form factor (components.js `formFactor`): phone < 700 px (or a landscape phone), tablet 700–1279, desktop ≥ 1280.
 * The portal root carries them as attributes (`data-tdp-theme`, `data-form`, `data-pointer`, `data-short`) so the
 * scoped CSS (styles/*.css) responds exactly like the old `:root[...]` rules. The LMS `<html data-theme>` is never touched.
 */
import { useEffect, useState, useSyncExternalStore } from "react";

export type Theme = "light" | "dark";
export type FormFactor = "phone" | "tablet" | "desktop";

const THEME_KEY = "td.theme";
const NAV_KEY = "td.nav";

function readLS(k: string): string | null {
  try {
    return localStorage.getItem(k);
  } catch {
    return null;
  }
}
function writeLS(k: string, v: string | null): void {
  try {
    if (v === null) localStorage.removeItem(k);
    else localStorage.setItem(k, v);
  } catch {
    /* private mode */
  }
}

const mq = (q: string): MediaQueryList | null => (typeof window !== "undefined" && typeof window.matchMedia === "function" ? window.matchMedia(q) : null);

/* ------------------------------------------------------------------ theme */

const themeListeners = new Set<() => void>();
function storedTheme(): Theme | null {
  let t: string | null = null;
  try {
    t = new URLSearchParams(window.location.search).get("theme");
  } catch {
    /* no window */
  }
  t = t === "light" || t === "dark" ? t : readLS(THEME_KEY);
  return t === "light" || t === "dark" ? t : null;
}
function computeTheme(): Theme {
  return storedTheme() ?? (mq("(prefers-color-scheme: dark)")?.matches ? "dark" : "light");
}
let theme: Theme = typeof window === "undefined" ? "light" : computeTheme();

export function getTheme(): Theme {
  return theme;
}
export function setTheme(t: Theme): void {
  writeLS(THEME_KEY, t);
  theme = t;
  for (const l of themeListeners) l();
}
/** "Match device": forget the saved choice; the portal follows the OS preference live again. */
export function clearTheme(): void {
  writeLS(THEME_KEY, null);
  theme = computeTheme();
  for (const l of themeListeners) l();
}
export function toggleTheme(): void {
  setTheme(theme === "dark" ? "light" : "dark");
}
function subscribeTheme(fn: () => void): () => void {
  themeListeners.add(fn);
  const m = mq("(prefers-color-scheme: dark)");
  const onOs = () => {
    if (!storedTheme()) {
      theme = computeTheme();
      fn();
    }
  };
  m?.addEventListener?.("change", onOs);
  return () => {
    themeListeners.delete(fn);
    m?.removeEventListener?.("change", onOs);
  };
}
export function useTheme(): Theme {
  return useSyncExternalStore(subscribeTheme, getTheme, getTheme);
}

/** Browser chrome colour follows the portal theme while the portal is open (restored on leave). */
export function useThemeColorMeta(t: Theme): void {
  useEffect(() => {
    const metas = [...document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]')];
    const before = metas.map((m) => m.content);
    metas.forEach((m) => {
      m.content = t === "dark" ? "#060C20" : "#032269";
    });
    return () => metas.forEach((m, i) => (m.content = before[i] ?? m.content));
  }, [t]);
}

/* ------------------------------------------------------------------ sidebar */

export function readNavCollapsed(): boolean {
  return readLS(NAV_KEY) === "collapsed";
}
export function writeNavCollapsed(c: boolean): void {
  writeLS(NAV_KEY, c ? "collapsed" : null);
}

/* ------------------------------------------------------------------ form factor */

export interface Device {
  form: FormFactor;
  coarse: boolean;
  /** viewport shorter than 500 px (landscape phone) */
  short: boolean;
}

export function computeDevice(): Device {
  if (typeof window === "undefined") return { form: "desktop", coarse: false, short: false };
  const w = window.innerWidth;
  const ht = window.innerHeight;
  const coarse = !!mq("(pointer: coarse)")?.matches;
  const sw = window.screen?.width || w;
  const sh = window.screen?.height || ht;
  const shortSide = Math.min(sw, sh);
  const landscapePhone = coarse && (shortSide < 500 || (ht < 500 && w < 950));
  const form: FormFactor = w < 700 || landscapePhone ? "phone" : w < 1280 ? "tablet" : "desktop";
  return { form, coarse, short: ht < 500 };
}

/** React: the device class; updates on resize / rotation / pointer change. */
export function useDevice(): Device {
  const [d, setD] = useState<Device>(computeDevice);
  useEffect(() => {
    let raf = 0;
    const on = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() =>
        setD((prev) => {
          const n = computeDevice();
          return n.form === prev.form && n.coarse === prev.coarse && n.short === prev.short ? prev : n;
        }),
      );
    };
    window.addEventListener("resize", on);
    window.addEventListener("orientationchange", on);
    const m = mq("(pointer: coarse)");
    m?.addEventListener?.("change", on);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", on);
      window.removeEventListener("orientationchange", on);
      m?.removeEventListener?.("change", on);
    };
  }, []);
  return d;
}

export const prefersReducedMotion = (): boolean => !!mq("(prefers-reduced-motion: reduce)")?.matches;
