"use client";

import Link from "next/link";
import { useIdentity } from "@/lib/api/session-cache";
import { Icon } from "@/components/ui/Display";
import { PORTALS, type PortalKey } from "@/lib/nav/portals";
import { switcherPortals, type MyGrantsPortals } from "@/features/staff-portal/access";

/**
 * Portal switcher (FR-RBAC-002): lists the portals the signed-in user can work in (RBAC
 * `GET /me/grants` → `portals` and live role grants; `switcherPortals`). An Admin also gets the
 * Content studio, and the Teacher portal only with a trainer grant, so an Admin who followed a
 * dashboard link into Studio or Teacher always has "Admin" one click away (live audit admin.md F3).
 * Shown only when there is more than one. A UX convenience: the api authorises every request.
 * The grants come from the session cache (src/lib/api/session-cache.ts): no request of its own
 * when the gate already read them.
 * Below `sm` the button is icon-only (the label stays for screen readers), so the header fits a
 * 320px phone without wrapping (live re-check 2026-11-14, verification.md).
 */
export function PortalSwitcher({ current }: { current: PortalKey }) {
  const grants = useIdentity<MyGrantsPortals>("me/grants").data;
  const portals = grants ? switcherPortals(grants.portals, grants.data?.map((g) => g.role_key)) : [];

  if (portals.length < 2) return null;
  // Admin sections (finance, desk, security) are part of the Admin portal.
  const def = PORTALS[current];
  const here = def.parent ? PORTALS[def.parent].prefix : def.prefix;
  return (
    <details className="relative">
      <summary title="Switch portal" className="flex min-h-touch min-w-touch cursor-pointer justify-center list-none items-center gap-1.5 rounded-xl px-2.5 font-display text-sm font-semibold text-brand transition-colors duration-fast hover:bg-[#f4f7fd] focus-visible:shadow-focus focus-visible:outline-none md:min-h-10 md:border md:border-[#e6eaf2] md:bg-surface md:px-3.5 md:hover:border-[#c9d4ea] [&::-webkit-details-marker]:hidden">
        <Icon name="repeat" className="h-5 w-5 sm:hidden" />
        <span className="sr-only whitespace-nowrap sm:not-sr-only">Switch portal</span>
      </summary>
      <ul aria-label="Your portals" className="absolute right-0 z-dropdown mt-1 min-w-[13rem] max-w-[calc(100vw-2rem)] rounded-2xl border border-line bg-surface p-1.5 shadow-[0_30px_60px_-24px_rgba(5,11,36,0.35)]">
        {portals.map((p) => (
          <li key={p.href}>
            <Link
              href={p.href}
              aria-current={p.href === here ? "page" : undefined}
              className="block rounded-lg px-3 py-2 text-sm text-fg no-underline hover:bg-surface-hover hover:text-brand focus-visible:shadow-focus focus-visible:outline-none aria-[current=page]:bg-surface-selected aria-[current=page]:font-semibold aria-[current=page]:text-brand-on-subtle"
            >
              {p.title}
            </Link>
          </li>
        ))}
      </ul>
    </details>
  );
}
