/**
 * `next/navigation` on React Router (data/library mode).
 *
 * - `redirect()` / `notFound()` throw marker errors; the segment boundaries (src/spa/boundary.tsx)
 *   turn them into a client navigation or the root not-found page, like Next does.
 * - Hooks also work outside a router (unit tests render components without one), falling back
 *   to `window.location`.
 */
import { useMemo } from "react";
import { useInRouterContext, useLocation, useMatches, useNavigate, useParams as useRRParams } from "react-router";
import { bumpRefresh, isExternalHref, navigateTo, needsDocumentLoad, toAppPath } from "../nav-store";

export class RedirectError extends Error {
  readonly digest: string;
  constructor(
    readonly url: string,
    readonly replace = true,
  ) {
    super(`NEXT_REDIRECT ${url}`);
    this.name = "RedirectError";
    this.digest = `NEXT_REDIRECT;${url}`;
  }
}

export class NotFoundError extends Error {
  readonly digest = "NEXT_NOT_FOUND";
  constructor() {
    super("NEXT_NOT_FOUND");
    this.name = "NotFoundError";
  }
}

export enum RedirectType {
  push = "push",
  replace = "replace",
}

export function redirect(url: string, type?: RedirectType): never {
  throw new RedirectError(url, type !== RedirectType.push);
}

export function notFound(): never {
  throw new NotFoundError();
}

export function isRedirectError(e: unknown): e is RedirectError {
  return e instanceof RedirectError;
}

export function isNotFoundError(e: unknown): e is NotFoundError {
  return e instanceof NotFoundError;
}

export type ReadonlyURLSearchParams = URLSearchParams;

export interface NavigateOptions {
  scroll?: boolean;
}

export interface AppRouterInstance {
  push(href: string, options?: NavigateOptions): void;
  replace(href: string, options?: NavigateOptions): void;
  back(): void;
  forward(): void;
  refresh(): void;
  prefetch(href: string): void;
}

const fallbackRouter: AppRouterInstance = {
  push: (href, o) => navigateTo(href, { scroll: o?.scroll }),
  replace: (href, o) => navigateTo(href, { replace: true, scroll: o?.scroll }),
  back: () => window.history.back(),
  forward: () => window.history.forward(),
  refresh: () => bumpRefresh(),
  prefetch: () => undefined,
};

/* The in/out-of-router branch is fixed for a given tree, so the conditional hook calls are stable. */

function useRouterNavigate(): ReturnType<typeof useNavigate> | null {
  return useInRouterContext() ? useNavigate() : null;
}

export function useRouter(): AppRouterInstance {
  const navigate = useRouterNavigate();
  return useMemo<AppRouterInstance>(() => {
    if (!navigate) return fallbackRouter;
    const go = (href: string, replace: boolean, o?: NavigateOptions) => {
      if (isExternalHref(href) || needsDocumentLoad(href)) {
        if (replace) window.location.replace(href);
        else window.location.assign(href);
        return;
      }
      void navigate(toAppPath(href), { replace, preventScrollReset: o?.scroll === false });
    };
    return {
      push: (href, o) => go(href, false, o),
      replace: (href, o) => go(href, true, o),
      back: () => void navigate(-1),
      forward: () => void navigate(1),
      refresh: () => bumpRefresh(),
      prefetch: () => undefined,
    };
  }, [navigate]);
}

function useLoc(): { pathname: string; search: string } {
  if (useInRouterContext()) return useLocation();
  return typeof window === "undefined" ? { pathname: "/", search: "" } : window.location;
}

export function usePathname(): string {
  return useLoc().pathname;
}

export function useSearchParams(): ReadonlyURLSearchParams {
  const { search } = useLoc();
  return useMemo(() => new URLSearchParams(search), [search]);
}

/** Route params; a Next catch-all (`[...x]`, mapped to `*`) comes back as `x: string[]`. */
export function useParams<T extends Record<string, string | string[]> = Record<string, string | string[]>>(): T {
  const inRouter = useInRouterContext();
  const params = inRouter ? useRRParams() : {};
  const matches = inRouter ? useMatches() : [];
  return useMemo(() => {
    const handle = matches.at(-1)?.handle as { catchAll?: string } | undefined;
    return toNextParams(params as Record<string, string | undefined>, handle?.catchAll) as T;
  }, [params, matches]);
}

export function toNextParams(params: Record<string, string | undefined>, catchAll?: string): Record<string, string | string[]> {
  const out: Record<string, string | string[]> = {};
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined) continue;
    if (k === "*") {
      if (catchAll) out[catchAll] = v.split("/").filter(Boolean);
    } else out[k] = v;
  }
  return out;
}
