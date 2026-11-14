import { startTransition, useSyncExternalStore } from "react";
import type { createBrowserRouter } from "react-router";

/**
 * Small global state shared by the next/* shims:
 * - the data router instance (navigation from non-component code: redirects, api client);
 * - a refresh counter: `router.refresh()` bumps it so every async (ex-server) component re-loads,
 *   like Next re-rendering server components.
 */
type Router = ReturnType<typeof createBrowserRouter>;

let router: Router | null = null;
let refreshVersion = 0;
const listeners = new Set<() => void>();

export function setRouter(r: Router): void {
  router = r;
}

export function bumpRefresh(): void {
  startTransition(() => {
    refreshVersion += 1;
    for (const l of listeners) l();
  });
}

function subscribe(l: () => void): () => void {
  listeners.add(l);
  return () => listeners.delete(l);
}

export function useRefreshVersion(): number {
  return useSyncExternalStore(subscribe, () => refreshVersion, () => refreshVersion);
}

/** Absolute URL on another origin (or a non-http scheme): must be a full page load. */
export function isExternalHref(href: string): boolean {
  if (href.startsWith("//")) return true;
  if (!/^[a-z][a-z0-9+.-]*:/i.test(href)) return false;
  if (typeof window === "undefined") return true;
  try {
    return new URL(href).origin !== window.location.origin;
  } catch {
    return true;
  }
}

/** Same-origin absolute URL → path; anything else unchanged. */
export function toAppPath(href: string): string {
  if (/^https?:/i.test(href) && typeof window !== "undefined") {
    const u = new URL(href);
    if (u.origin === window.location.origin) return `${u.pathname}${u.search}${u.hash}`;
  }
  return href;
}

/**
 * Pages whose Hosting response headers differ from the rest (Google sign-in CSP + COOP
 * same-origin-allow-popups on /login and /signup; frame-src 'self' on /admin/college-data).
 * Headers apply per document, so entering or leaving them is a full page load (as a first
 * visit to them was in the Next app).
 */
const DOCUMENT_ROUTES = new Set(["/login", "/signup", "/admin/college-data"]);

const pathOf = (href: string) => href.split(/[?#]/)[0] ?? href;

export function needsDocumentLoad(href: string): boolean {
  if (typeof window === "undefined") return false;
  const target = pathOf(toAppPath(href));
  const here = window.location.pathname;
  if (target === here || !target.startsWith("/")) return false;
  if (DOCUMENT_ROUTES.has(target) || DOCUMENT_ROUTES.has(here)) return true;
  // The Outreach Portal (/colleges) has its own CSP (map tiles in img-src): crossing into or out of it is a
  // full page load; moving inside it stays client-side.
  return isCollegesPath(target) !== isCollegesPath(here);
}

/** /colleges and everything under it (the React Outreach Portal; hosting-headers.ts collegesCsp). */
export function isCollegesPath(pathname: string): boolean {
  return pathname === "/colleges" || pathname.startsWith("/colleges/");
}

/** Navigate from anywhere (client-side when possible). */
export function navigateTo(href: string, opts: { replace?: boolean; scroll?: boolean } = {}): void {
  if (isExternalHref(href) || needsDocumentLoad(href)) {
    if (opts.replace) window.location.replace(href);
    else window.location.assign(href);
    return;
  }
  const to = toAppPath(href);
  if (router) void router.navigate(to, { replace: opts.replace, preventScrollReset: opts.scroll === false });
  else if (typeof window !== "undefined") window.location.assign(to);
}
