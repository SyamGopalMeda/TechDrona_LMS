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

/** The portals the caller can open, in registry order, for the 403 page's portal switcher.
 * Admin sections (finance, support, security, mentoring) are reached through the Admin portal. */
export function reachablePortals(portals: readonly string[] | undefined): { href: string; title: string }[] {
  const set = new Set(portals ?? []);
  return Object.values(PORTALS)
    .filter((p) => set.has(p.prefix) && !p.parent)
    .map((p) => ({ href: p.prefix, title: p.title }));
}
