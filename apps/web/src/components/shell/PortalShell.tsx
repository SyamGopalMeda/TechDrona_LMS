import Link from "next/link";
import { headers } from "next/headers";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";
import { Logo } from "@/components/ui/Logo";
import { hasSessionCookie } from "@/lib/api/server";
import { PORTALS, signInNext, type PortalKey } from "@/lib/nav/portals";
import { NotificationBell } from "@/features/notifications/components/NotificationBell";
import { MobileTabBar, STUDENT_TABS } from "./MobileTabBar";
import { PortalNav } from "./PortalNav";
import { PortalSwitcher } from "./PortalSwitcher";
import { SignOutButton } from "./SignOutButton";

const APP_NAME = process.env.NEXT_PUBLIC_APP_NAME ?? "Tech Drona";

/**
 * Authenticated portal layout: top bar (Tech Drona logo + portal name) + role navigation + main
 * landmark. Mirrors the website's own learning portal (`tech drona/src/styles/lms.css` `.lx`):
 * white sidebar with navy active item on a cool #F4F6FA canvas.
 * Session presence is checked here as well as in middleware (prefetches skip middleware).
 * Authorisation itself is enforced by the api on every request.
 *
 * Learner portal below `lg`: bottom tabs (Home · Learn · Practice · Tests · More) per sitemap §1;
 * staff portals keep the collapsible menu. The bell (in-app inbox, NTF-01) is learner-only
 * because the inbox lives at /app/notifications.
 */
export async function PortalShell({ portal, children }: { portal: PortalKey; children: ReactNode }) {
  const def = PORTALS[portal];
  const isStudent = portal === "student";
  if (!(await hasSessionCookie())) {
    const next = signInNext((await headers()).get("x-td-request-path"), def.prefix);
    redirect(`/login?next=${encodeURIComponent(next)}`);
  }

  return (
    <div className="min-h-dvh bg-surface-canvas text-fg">
      <header className="sticky top-0 z-topbar border-b border-line bg-surface/95 backdrop-blur supports-[backdrop-filter]:bg-surface/85">
        <div className="mx-auto flex h-topbar max-w-wide items-center justify-between gap-3 px-4 lg:px-6">
          <div className="flex min-w-0 items-center gap-3">
            <Link
              href={def.prefix}
              aria-label={`${APP_NAME} — ${def.title} home`}
              className="flex shrink-0 items-center rounded-md focus-visible:shadow-focus focus-visible:outline-none"
            >
              <Logo alt="" className="h-7 sm:h-8" />
            </Link>
            <span aria-hidden="true" className="hidden h-6 w-px bg-line sm:block" />
            <span className="truncate rounded-full bg-brand-subtle px-2.5 py-0.5 font-display text-xs font-bold text-brand-on-subtle">{def.title}</span>
          </div>
          <div className="flex items-center gap-1 sm:gap-2">
            <PortalSwitcher current={portal} />
            {isStudent ? <NotificationBell /> : null}
            <SignOutButton />
          </div>
        </div>
      </header>
      <div className="mx-auto flex max-w-wide">
        <aside className="sticky top-topbar hidden h-[calc(100dvh-var(--td-layout-topbar))] w-sidebar shrink-0 overflow-y-auto border-r border-line bg-surface px-3 py-4 lg:block">
          <PortalNav items={def.nav} label={`${def.title} navigation`} root={def.prefix} />
        </aside>
        <div className="min-w-0 flex-1">
          {isStudent ? null : (
            <details className="group border-b border-line bg-surface lg:hidden">
              <summary className="flex min-h-touch cursor-pointer list-none items-center gap-2 px-4 font-display text-sm font-semibold text-fg focus-visible:shadow-focus focus-visible:outline-none [&::-webkit-details-marker]:hidden">
                <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="h-5 w-5 text-brand">
                  <path d="M4 7h16M4 12h16M4 17h16" />
                </svg>
                Menu
                <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="ml-auto h-4 w-4 text-fg-muted transition-transform group-open:rotate-180">
                  <path d="m6 9 6 6 6-6" />
                </svg>
              </summary>
              <div className="max-h-[70dvh] overflow-y-auto border-t border-line-subtle px-3 pb-3 pt-2">
                <PortalNav items={def.nav} label={`${def.title} navigation`} root={def.prefix} />
              </div>
            </details>
          )}
          <main
            id="main"
            tabIndex={-1}
            className={
              isStudent
                ? "mx-auto w-full max-w-[80rem] px-4 pb-24 pt-6 focus:outline-none sm:px-6 lg:px-8 lg:pb-10 lg:pt-8"
                : "mx-auto w-full max-w-[80rem] px-4 py-6 focus:outline-none sm:px-6 lg:px-8 lg:py-8"
            }
          >
            {children}
          </main>
        </div>
      </div>
      {isStudent ? <MobileTabBar tabs={STUDENT_TABS} nav={def.nav} label={`${def.title} navigation`} root={def.prefix} /> : null}
    </div>
  );
}
