/**
 * Runs an ex-server component (an `async function` component from apps/web) on the client.
 *
 * Server components never use hooks, so calling one as a plain async function is safe: the
 * returned element tree is rendered with `use()`, which suspends to the nearest Suspense
 * boundary (the segment's loading.tsx, like Next streaming) while the data loads. Errors thrown
 * by the function (ApiError, redirect(), notFound()) propagate to the segment boundaries.
 *
 * The promise is cached per (component, navigation, refresh, props) so re-renders reuse it and a
 * new navigation or `router.refresh()` loads fresh data, as Next re-renders server components.
 *
 * Ported pages were rewritten from `export default async function Page(...)` into
 * `async function Page__server(...)` + `export default asyncComponent(Page__server, "...")`
 * (by the apps/web sync, retired 2026-11-14; src is now the source of truth).
 */
import { use, type ReactNode } from "react";
import { useInRouterContext, useLocation } from "react-router";
import { useRefreshVersion } from "./nav-store";

const MAX_ENTRIES = 300;
const cache = new Map<string, Promise<ReactNode>>();

const ids = new WeakMap<object, number>();
let nextId = 1;
function identity(v: object): string {
  let id = ids.get(v);
  if (!id) {
    id = nextId++;
    ids.set(v, id);
  }
  return `#${id}`;
}

/** Stable key for props: data by value; elements, functions and promises by identity. */
export function propsKey(props: unknown): string {
  try {
    return JSON.stringify(props ?? null, (_k, v: unknown) => {
      if (typeof v === "function") return identity(v);
      if (v && typeof v === "object") {
        if ("$$typeof" in v || typeof (v as { then?: unknown }).then === "function") return identity(v);
      }
      if (typeof v === "bigint") return v.toString();
      return v;
    });
  } catch {
    return identity(props as object);
  }
}

function useNavToken(): string {
  const refresh = useRefreshVersion();
  // In or out of a router is fixed for a tree, so the conditional hook is stable.
  const key = useInRouterContext() ? useLocation().key : "default";
  return `${key}.${refresh}`;
}

export function loadOnce<T>(key: string, load: () => Promise<T>): Promise<T> {
  let p = cache.get(key) as Promise<T> | undefined;
  if (!p) {
    p = load();
    // Pre-mark rejections as handled; `use()` still sees the rejection.
    p.catch(() => undefined);
    cache.set(key, p as Promise<ReactNode>);
    if (cache.size > MAX_ENTRIES) {
      const oldest = cache.keys().next().value;
      if (oldest !== undefined) cache.delete(oldest);
    }
  }
  return p;
}

export type AsyncServerComponent<P> = ((props: P) => ReactNode) & {
  /** The original async function (tests call it directly, as they did with the server component). */
  server: (props: P) => Promise<ReactNode> | ReactNode;
};

export function asyncComponent<P extends object>(fn: (props: P) => Promise<ReactNode> | ReactNode, name: string): AsyncServerComponent<P> {
  function AsyncServerComponent(props: P): ReactNode {
    const token = useNavToken();
    const p = loadOnce(`${name}|${token}|${propsKey(props)}`, async () => fn(props));
    return use(p);
  }
  AsyncServerComponent.displayName = name.split("#").pop() ?? name;
  return Object.assign(AsyncServerComponent, { server: fn });
}
