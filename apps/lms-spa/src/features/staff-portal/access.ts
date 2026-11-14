import { PORTALS, type PortalKey } from "@/lib/nav/portals";

/** `GET /me/grants` (RBAC-06): `portals` lists the route prefixes the caller's live grants open. */
export interface MyGrantsPortals {
  portals?: string[];
  /** Live grants; only `role_key` is used here. */
  data?: { role_key: string }[];
}

/**
 * ADM-12: may the caller enter this staff portal? `portals` comes from the api
 * (sessions/login.py PORTALS: role → prefix). A super admin also gets the read views of the
 * other portals (role-permission-matrix §9). Since the single-company conversion (D2) the finance,
 * support and security portals are Admin sections, so `/admin` opens them all.
 * UX only — every request is still authorised by the api.
 */
export function canEnterPortal(portals: readonly string[] | undefined, portal: PortalKey, roleKeys?: readonly string[]): boolean {
  if (!portals) return false;
  const prefix = PORTALS[portal].prefix;
  if (portals.includes(prefix)) return true;
  // The api's PORTALS map still sends the `evaluator` role to `/trainer` (sessions/login.py);
  // a live grant of one of the portal's roles opens it too (e.g. Evaluator → `/evaluator`).
  if (roleKeys?.some((r) => PORTALS[portal].roles.includes(r))) return true;
  return portals.includes(PORTALS.admin.prefix) && portal !== "student";
}

/** The portals the caller can open, in registry order (a portal-switcher list).
 * Admin sections (finance, support, security) are reached through the Admin portal. */
export function reachablePortals(portals: readonly string[] | undefined): { href: string; title: string }[] {
  const set = new Set(portals ?? []);
  return Object.values(PORTALS)
    .filter((p) => set.has(p.prefix) && !p.parent)
    .map((p) => ({ href: p.prefix, title: p.title }));
}

/**
 * Content studio pages an Admin without the Content manager role can use (live audit 2026-11-14,
 * admin.md F2). The role matrix (apps/api/app/modules/rbac/catalogue.py) gives `super_admin` only
 * `course.archive`, `question.review` and `question.publish` among the studio permissions, so the
 * course list/detail and the review queue answer 200, while taxonomy, all questions, question banks,
 * reported errors, coding problems, media, template mocks and the studio dashboard
 * widgets answer 403. RBAC is unchanged; the gate and nav follow it.
 */
export const ADMIN_STUDIO_PATHS: readonly string[] = ["/studio/courses", "/studio/review"];

/**
 * How the caller may use the Content studio: `full` (Content manager, or `/studio` in `portals`),
 * `admin` (an Admin without that role: only ADMIN_STUDIO_PATHS) or `none`.
 */
export function studioAccess(portals: readonly string[] | undefined, roleKeys?: readonly string[]): "full" | "admin" | "none" {
  if (!portals) return "none";
  if (portals.includes(PORTALS.studio.prefix) || roleKeys?.some((r) => PORTALS.studio.roles.includes(r))) return "full";
  if (portals.includes(PORTALS.admin.prefix)) return "admin";
  return "none";
}

/** For an Admin-only studio visit: where to send `pathname` (null = it may stay). */
export function adminStudioRedirect(pathname: string): string | null {
  const p = pathname.split(/[?#]/)[0] ?? "";
  if (ADMIN_STUDIO_PATHS.some((x) => p === x || p.startsWith(`${x}/`))) return null;
  return ADMIN_STUDIO_PATHS[0]!;
}

/**
 * Portal switcher list (admin.md F3): the portals the caller can really work in, in registry order.
 * - a portal listed in `portals`, or one whose role the caller holds (any scope);
 * - for an Admin, the Content studio too (its course list and review queue work for Admin);
 * - not the Teacher or Evaluator portal just because the caller is an Admin: only with that grant.
 * Admin sections (finance, support, security) are reached through the Admin portal.
 */
export function switcherPortals(portals: readonly string[] | undefined, roleKeys?: readonly string[]): { href: string; title: string }[] {
  const set = new Set(portals ?? []);
  const roles = new Set(roleKeys ?? []);
  const admin = set.has(PORTALS.admin.prefix);
  return Object.values(PORTALS)
    .filter((p) => !p.parent)
    .filter((p) => set.has(p.prefix) || p.roles.some((r) => roles.has(r)) || (admin && p.key === "studio"))
    .map((p) => ({ href: p.prefix, title: p.title }));
}

/** Home portal priority, most privileged first (api sessions/login.py LANDING_ORDER, then student). */
const HOME_ORDER: readonly PortalKey[] = ["admin", "studio", "trainer", "evaluator", "student"];

/**
 * Where to send a signed-in user who opened a portal their roles do not open: their own home
 * portal (Student → `/app`, Trainer → `/trainer`, Admin → `/admin`…). `null` only when the
 * account opens no portal at all (then a friendly "no access yet" page is shown instead).
 */
export function homePortal(portals: readonly string[] | undefined): string | null {
  if (!portals?.length) return null;
  for (const key of HOME_ORDER) if (portals.includes(PORTALS[key].prefix)) return PORTALS[key].prefix;
  // Any other known portal prefix the api lists (e.g. a legacy /desk grant).
  return portals.find((p) => Object.values(PORTALS).some((d) => d.prefix === p)) ?? null;
}

/*
 * SPA-specific: the Student portal (`/app`) gate.
 * Role/portal navigation fix 2026-11-13 (docs/firebase/agents/role-nav-fix.md).
 */

/**
 * Account pages every signed-in account uses, whatever its role: profile / security / devices /
 * privacy settings (incl. the MFA enrolment page the api client sends staff to) and the account
 * status page. They live under `/app` but are not student pages.
 */
export const SHARED_ACCOUNT_PREFIXES: readonly string[] = ["/app/settings", "/app/account-status"];

export function isSharedAccountPath(pathname: string): boolean {
  const p = pathname.split(/[?#]/)[0] ?? "";
  return SHARED_ACCOUNT_PREFIXES.some((x) => p === x || p.startsWith(`${x}/`));
}

/** The portal registry key for a portal prefix (`/admin` → "admin"), null for anything else. */
export function portalKeyForPrefix(prefix: string | null | undefined): PortalKey | null {
  if (!prefix) return null;
  return Object.values(PORTALS).find((p) => p.prefix === prefix)?.key ?? null;
}

export type StudentAreaDecision = { kind: "shell"; portal: PortalKey } | { kind: "redirect"; to: string } | { kind: "forbidden" };

/**
 * Which shell an `/app/*` page opens in (same rule as StaffPortalGate, mirrored: a Student opening
 * /admin lands on /app, so a staff-only account opening a student page lands on its own portal).
 *
 * - `grants` null = unknown (no session yet, or the api failed) or no `portals`: the Student shell, as before;
 *   the api still authorises every request.
 * - A caller whose grants open the Student portal (`/app` in `portals`, which the api also returns
 *   when the account holds no grant at all, or a live `student` grant) keeps the Student portal.
 * - Shared account pages (settings, account status) open for everyone, inside the shell of the
 *   staff portal the caller just came from (`lastPortal`, when they may open it), else the Student
 *   shell for a student, else their own home portal's shell — so a staff member's "Settings" never
 *   drops them into the Student portal.
 * - Any other `/app` page sends a staff-only account to its home portal.
 */
export function decideStudentArea(grants: MyGrantsPortals | null, pathname: string, lastPortal?: PortalKey | null): StudentAreaDecision {
  // Unknown, or a reply without portals (the api always lists at least one): fail open, as before.
  if (!grants?.portals?.length) return { kind: "shell", portal: "student" };
  const roleKeys = grants.data?.map((g) => g.role_key);
  const studentOk = canEnterPortal(grants.portals, "student", roleKeys);
  if (isSharedAccountPath(pathname)) {
    if (lastPortal && lastPortal !== "student" && canEnterPortal(grants.portals, lastPortal, roleKeys)) return { kind: "shell", portal: lastPortal };
    if (studentOk) return { kind: "shell", portal: "student" };
    return { kind: "shell", portal: portalKeyForPrefix(homePortal(grants.portals)) ?? "student" };
  }
  if (studentOk) return { kind: "shell", portal: "student" };
  const home = homePortal(grants.portals);
  if (home) return { kind: "redirect", to: home };
  return { kind: "forbidden" };
}
