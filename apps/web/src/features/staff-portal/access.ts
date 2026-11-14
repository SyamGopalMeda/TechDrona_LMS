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
 * support, security and mentoring portals are Admin sections, so `/admin` opens them all.
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
 * Admin sections (finance, support, security, mentoring) are reached through the Admin portal. */
export function reachablePortals(portals: readonly string[] | undefined): { href: string; title: string }[] {
  const set = new Set(portals ?? []);
  return Object.values(PORTALS)
    .filter((p) => set.has(p.prefix) && !p.parent)
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
