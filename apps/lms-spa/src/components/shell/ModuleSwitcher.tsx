"use client";

import { FULL_SCREEN_COLLEGES } from "@/features/hub/last-page";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api/client";
import type { HubModule } from "@/features/hub/modules";
import { areaOf, continueHref } from "@/features/hub/last-page";

/**
 * Module switcher (central login): LMS, Colleges Management and Company Website Admin, limited to
 * the modules the user may open (GET /me/modules). Shown only when there is more than one. Each
 * module authorises every request itself; this is navigation only. The Company Website Admin opens
 * through /sso/website (single sign-on), so switching never asks for a password again.
 * Below `sm` the menu is pinned under the header across the screen (inset 1rem each side), so it
 * never opens off the left edge of a 320px phone (live re-check 2026-11-14, verification.md).
 */
export function ModuleSwitcher({ current: initial }: { current: "lms" | "colleges" }) {
  const [modules, setModules] = useState<HubModule[]>([]);
  // The shell (a layout) renders once; follow client navigation between the LMS and Colleges pages.
  const pathname = usePathname();
  const current = pathname ? areaOf(pathname) : initial;
  // Switching to the other module resumes the page last open there (/continue), else its landing page.
  const hrefFor = (m: HubModule) => {
    if (m.key === current) return m.href;
    if (m.key === "lms") return continueHref("lms", m.href);
    // Colleges Management always opens the portal full screen (owner 2026-11-14), never the
    // embedded Admin page that "resume last page" could pick.
    if (m.key === "colleges") return FULL_SCREEN_COLLEGES;
    return m.href;
  };

  useEffect(() => {
    let live = true;
    api
      .get<{ modules?: HubModule[] }>("me/modules", { handle: { stepUp: false, restriction: false, auth: false, sessionChoice: false } })
      .then((r) => {
        if (live) setModules(r.modules ?? []);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);

  if (modules.length < 2) return null;
  return (
    <details className="relative">
      <summary className="flex min-h-touch cursor-pointer whitespace-nowrap list-none items-center gap-1.5 rounded-xl px-2.5 font-display text-sm font-semibold text-brand transition-colors duration-fast hover:bg-[#f4f7fd] focus-visible:shadow-focus focus-visible:outline-none md:min-h-10 md:border md:border-[#e6eaf2] md:bg-surface md:px-3.5 md:hover:border-[#c9d4ea] [&::-webkit-details-marker]:hidden">
        Modules
      </summary>
      <ul
        aria-label="Tech Drona modules"
        className="fixed inset-x-4 top-[calc(theme(spacing.topbar)+0.25rem)] z-dropdown rounded-2xl sm:absolute sm:inset-x-auto sm:right-0 sm:top-full sm:mt-1 sm:min-w-[15rem] border border-line bg-surface p-1.5 shadow-[0_30px_60px_-24px_rgba(5,11,36,0.35)]">
        {modules.map((m) => (
          <li key={m.key}>
            {m.external ? (
              // the website admin is another site: a full page load, not client navigation
              <a
                href={m.href}
                className="block rounded-lg px-3 py-2 text-sm text-fg no-underline hover:bg-surface-hover hover:text-brand focus-visible:shadow-focus focus-visible:outline-none"
              >
                {m.title}
              </a>
            ) : (
              <Link
                href={hrefFor(m)}
                prefetch={false}
                aria-current={m.key === current ? "page" : undefined}
                className="block rounded-lg px-3 py-2 text-sm text-fg no-underline hover:bg-surface-hover hover:text-brand focus-visible:shadow-focus focus-visible:outline-none aria-[current=page]:bg-surface-selected aria-[current=page]:font-semibold aria-[current=page]:text-brand-on-subtle"
              >
                {m.title}
              </Link>
            )}
          </li>
        ))}
        <li className="mt-1 border-t border-line-subtle pt-1">
          <Link href="/modules" prefetch={false} className="block rounded-lg px-3 py-2 text-sm text-fg-secondary no-underline hover:bg-surface-hover hover:text-brand">
            All modules
          </Link>
        </li>
      </ul>
    </details>
  );
}
