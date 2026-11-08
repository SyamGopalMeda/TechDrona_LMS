"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api/client";
import { PORTALS, type PortalKey } from "@/lib/nav/portals";

interface GrantsResponse {
  /** verified: app/modules/rbac/router.py my_grants → sorted portal prefixes, at least ["/app"]. */
  portals?: string[];
}

/** Portal prefixes → title, from the nav registry (one source of truth for names). */
/** Admin sections (`parent: "admin"`) are reached through the Admin nav, not listed separately. */
const BY_PREFIX = new Map(Object.values(PORTALS).filter((p) => !p.parent).map((p) => [p.prefix, p.title] as const));

/**
 * Portal switcher (FR-RBAC-002): lists the portals the signed-in user holds grants for
 * (RBAC `GET /me/grants` → `portals`). Shown only when there is more than one. A UX convenience:
 * the api authorises every request regardless of what is listed here.
 */
export function PortalSwitcher({ current }: { current: PortalKey }) {
  const [portals, setPortals] = useState<string[]>([]);

  useEffect(() => {
    let live = true;
    api
      .get<GrantsResponse>("me/grants", { handle: { stepUp: false, restriction: false, auth: false, sessionChoice: false } })
      .then((r) => {
        if (live) setPortals((r.portals ?? []).filter((p) => BY_PREFIX.has(p)));
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);

  if (portals.length < 2) return null;
  const here = PORTALS[current].prefix;
  return (
    <details className="relative">
      <summary className="flex min-h-touch cursor-pointer list-none items-center rounded-md px-2.5 font-display text-sm font-semibold text-fg-secondary hover:bg-brand-subtle hover:text-brand focus-visible:shadow-focus focus-visible:outline-none [&::-webkit-details-marker]:hidden">
        Switch portal
      </summary>
      <ul aria-label="Your portals" className="absolute right-0 z-dropdown mt-1 min-w-[13rem] rounded-xl border border-line bg-surface p-1.5 shadow-lg">
        {portals.map((p) => (
          <li key={p}>
            <Link
              href={p}
              aria-current={p === here ? "page" : undefined}
              className="block rounded-lg px-3 py-2 text-sm text-fg no-underline hover:bg-surface-hover hover:text-brand focus-visible:shadow-focus focus-visible:outline-none aria-[current=page]:bg-surface-selected aria-[current=page]:font-semibold aria-[current=page]:text-brand-on-subtle"
            >
              {BY_PREFIX.get(p)}
            </Link>
          </li>
        ))}
      </ul>
    </details>
  );
}
