import Link from "next/link";
import { use, useEffect, useState, type ReactNode } from "react";
import { useLocation } from "react-router";
import { Logo } from "@/components/ui/Logo";
import { PORTALS, signInNext, visibleNav, type PortalKey } from "@/lib/nav/portals";
import { NotificationBell } from "@/features/notifications/components/NotificationBell";
import { noteShellPortal, useStaffGrants } from "@/features/staff-portal/StaffPortalGate";
import { ADMIN_STUDIO_PATHS, studioAccess } from "@/features/staff-portal/access";
import { useIntegrations } from "./Integrations";
import { ClientRedirect } from "@/spa/boundary";
import { probeSession } from "@/spa/session";
import { AccountMenu, type AccountLink } from "./AccountMenu";
import { MobileTabBar, STUDENT_TABS } from "./MobileTabBar";
import { PortalFrame } from "./PortalFrame";
import { ModuleSwitcher } from "./ModuleSwitcher";
import { PortalSwitcher } from "./PortalSwitcher";

const APP_NAME = process.env.NEXT_PUBLIC_APP_NAME ?? "Tech Drona";

/**
 * SPA override of apps/web/src/components/shell/PortalShell.tsx (same markup).
 *
 * The server version (and the Next middleware) redirected to `/login?next=<requested path>` when
 * the session cookie was missing. Here the session is probed once when the portal mounts
 * (src/spa/session.ts): "no" → the same redirect; "unknown" (API unreachable) → the shell renders
 * and the pages' own API calls handle 401 through the browser client, as before.
 */
export function PortalShell({ portal, children }: { portal: PortalKey; children: ReactNode }) {
  const def = PORTALS[portal];
  const isStudent = portal === "student";
  const location = useLocation();
  const requestPath = `${location.pathname}${location.search}`;
  const [probe] = useState(() => probeSession());
  const session = use(probe);
  // Live audit 2026-11-14 (docs/qa/live-audit/fixes-nav.md): list only what the caller can use.
  // Hidden registry items drop out; gateway pages wait for a connected payment gateway; an Admin
  // in the Content studio (no Content manager role) sees only the studio pages its APIs allow.
  const integrations = useIntegrations();
  const grants = useStaffGrants();
  const adminInStudio = portal === "studio" && !!grants && studioAccess(grants.portals, grants.data?.map((g) => g.role_key)) === "admin";
  const nav = visibleNav(def.nav, { connected: integrations, only: adminInStudio ? ADMIN_STUDIO_PATHS : null });
  // Admin sections (finance, desk, security, mentor) share the Admin nav: the logo goes to the Admin dashboard.
  const home = def.parent ? PORTALS[def.parent].prefix : def.prefix;
  const homeTitle = def.parent ? PORTALS[def.parent].title : def.title;
  // The account pages (settings, account status) live under /app for every account; for staff they
  // render inside the staff shell (app/app/layout.tsx → StudentPortalGate), never the Student portal.
  useEffect(() => noteShellPortal(portal), [portal]);
  const accountLinks: AccountLink[] = isStudent
    ? [
        { href: "/app/settings/profile", label: "Settings" },
        { href: "/app/account-status", label: "Account status" },
      ]
    : [{ href: "/app/settings/profile", label: "Settings" }];
  if (session === "no") {
    const next = signInNext(requestPath, def.prefix);
    return <ClientRedirect to={`/login?next=${encodeURIComponent(next)}`} />;
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
      {isStudent ? null : <ModuleSwitcher current={requestPath.startsWith("/admin/college-data") ? "colleges" : "lms"} />}
      <PortalSwitcher current={portal} />
      {isStudent ? <NotificationBell /> : null}
      <AccountMenu links={accountLinks} />
    </>
  );

  return (
    <div className="min-h-dvh bg-surface-canvas text-fg">
      <PortalFrame nav={nav} label={`${def.title} navigation`} root={def.prefix} title={def.title} isStudent={isStudent} brand={brand} actions={actions}>
        {children}
      </PortalFrame>
      {isStudent ? <MobileTabBar tabs={STUDENT_TABS} nav={nav} label={`${def.title} navigation`} root={def.prefix} /> : null}
    </div>
  );
}
