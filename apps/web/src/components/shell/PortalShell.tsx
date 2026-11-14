import Link from "next/link";
import { headers } from "next/headers";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";
import { Logo } from "@/components/ui/Logo";
import { hasSessionCookie } from "@/lib/api/server";
import { PORTALS, signInNext, type PortalKey } from "@/lib/nav/portals";
import { NotificationBell } from "@/features/notifications/components/NotificationBell";
import { AccountMenu, type AccountLink } from "./AccountMenu";
import { MobileTabBar, STUDENT_TABS } from "./MobileTabBar";
import { PortalFrame } from "./PortalFrame";
import { ModuleSwitcher } from "./ModuleSwitcher";
import { PortalSwitcher } from "./PortalSwitcher";

const APP_NAME = process.env.NEXT_PUBLIC_APP_NAME ?? "Tech Drona";

/**
 * Authenticated portal layout: top bar (Tech Drona logo + portal name) + role navigation + main
 * landmark. Mirrors the website's own learning portal (`tech drona/src/styles/lms.css` `.lx`):
 * white sidebar with navy active item on a cool #F4F6FA canvas.
 * Session presence is checked here as well as in middleware (prefetches skip middleware).
 * Authorisation itself is enforced by the api on every request.
 *
 * Learner portal below `lg`: bottom tabs (Home · Learn · Practice · Tests · More) per sitemap §1;
 * staff portals get a "Menu · <page>" bar (PortalFrame/StaffMenu). The bell (in-app inbox, NTF-01)
 * is learner-only because the inbox lives at /app/notifications. The account menu (who is signed
 * in, Settings, Sign out) replaces the bare "Sign out" button.
 * The path-dependent parts (sidebar hidden on focus routes, staff menu, main width) live in the
 * client PortalFrame; this server component keeps the session check and the header.
 */
export async function PortalShell({ portal, children }: { portal: PortalKey; children: ReactNode }) {
  const def = PORTALS[portal];
  const isStudent = portal === "student";
  // Admin sections (finance, desk, security, mentor) share the Admin nav: the logo goes to the Admin dashboard.
  const home = def.parent ? PORTALS[def.parent].prefix : def.prefix;
  const homeTitle = def.parent ? PORTALS[def.parent].title : def.title;
  // Settings live in the learner area, which every signed-in account can open (me/grants always has /app).
  const accountLinks: AccountLink[] = isStudent
    ? [
        { href: "/app/settings/profile", label: "Settings" },
        { href: "/app/account-status", label: "Account status" },
      ]
    : [{ href: "/app/settings/profile", label: "Settings" }];
  const requestPath = (await headers()).get("x-td-request-path");
  if (!(await hasSessionCookie())) {
    const next = signInNext(requestPath, def.prefix);
    redirect(`/login?next=${encodeURIComponent(next)}`);
  }

  const brand = (
    <>
      <Link href={home} aria-label={`${APP_NAME} — ${homeTitle} home`} className="flex shrink-0 items-center rounded-md focus-visible:shadow-focus focus-visible:outline-none">
        <Logo alt="" tone="auto" className="h-7 sm:h-8" />
      </Link>
      <span aria-hidden="true" className="hidden h-6 w-px bg-line sm:block" />
      <span className="hidden truncate rounded-full bg-brand-subtle px-2.5 py-0.5 font-display text-xs font-bold text-brand-on-subtle sm:inline-flex">{def.title}</span>
    </>
  );
  const actions = (
    <>
      {isStudent ? null : <ModuleSwitcher current={requestPath?.startsWith("/admin/college-data") ? "colleges" : "lms"} />}
      <PortalSwitcher current={portal} />
      {isStudent ? <NotificationBell /> : null}
      <AccountMenu links={accountLinks} />
    </>
  );

  return (
    <div className="min-h-dvh bg-surface-canvas text-fg">
      <PortalFrame nav={def.nav} label={`${def.title} navigation`} root={def.prefix} title={def.title} isStudent={isStudent} brand={brand} actions={actions}>
        {children}
      </PortalFrame>
      {isStudent ? <MobileTabBar tabs={STUDENT_TABS} nav={def.nav} label={`${def.title} navigation`} root={def.prefix} /> : null}
    </div>
  );
}
