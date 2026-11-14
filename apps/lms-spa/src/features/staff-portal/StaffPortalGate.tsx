import { createContext, use, useContext, useState, type ReactNode } from "react";
import { useLocation } from "react-router";
import { isApiError } from "@/lib/api/errors";
import { hasSessionCookie, serverApiGet } from "@/lib/api/server";
import { PORTALS, type PortalKey } from "@/lib/nav/portals";
import { ClientRedirect } from "@/spa/boundary";
import { adminStudioRedirect, canEnterPortal, decideStudentArea, homePortal, studioAccess, type MyGrantsPortals } from "./access";
import { PortalForbidden } from "./PortalForbidden";

/**
 * SPA override of apps/web/src/features/staff-portal/StaffPortalGate.tsx — same decisions, made
 * in the browser when the portal mounts:
 *
 * ADM-12: role-gates a staff portal layout using `GET /me/grants` `portals`. Without a session
 * the PortalShell inside redirects to sign-in, so nothing is fetched. A 401 sends the user to
 * sign-in; any other failure (api down) falls through to the shell, whose pages show their own
 * error states — the api remains the authority for every request.
 *
 * A signed-in user whose roles do not open this portal is sent straight to their own home portal
 * (a Student opening /admin lands on /app) — no error page. Only an account that opens no portal
 * at all sees the "no access yet" page.
 */
export type GateDecision = { kind: "enter"; grants?: MyGrantsPortals } | { kind: "redirect"; to: string } | { kind: "forbidden" };

/**
 * The caller's `GET /me/grants` as read by the gate (null = unknown: no session yet or the api
 * failed). PortalShell uses it to list only what the caller can use. UX only.
 */
const StaffGrantsContext = createContext<MyGrantsPortals | null>(null);
export function useStaffGrants(): MyGrantsPortals | null {
  return useContext(StaffGrantsContext);
}

export async function decideStaffPortal(portal: PortalKey): Promise<GateDecision> {
  if (!(await hasSessionCookie())) return { kind: "enter" };
  const def = PORTALS[portal];
  let grants: MyGrantsPortals;
  try {
    grants = await serverApiGet<MyGrantsPortals>("me/grants");
  } catch (err) {
    if (isApiError(err) && err.status === 401) return { kind: "redirect", to: `/login?next=${encodeURIComponent(def.prefix)}` };
    return { kind: "enter" };
  }
  if (canEnterPortal(grants.portals, portal, grants.data?.map((g) => g.role_key))) return { kind: "enter", grants };
  const home = homePortal(grants.portals);
  if (home) return { kind: "redirect", to: home };
  return { kind: "forbidden" };
}

/* One decision per portal entry; memoised briefly so a suspended first render reuses it. */
const pending = new Map<PortalKey, { p: Promise<GateDecision>; at: number }>();
function decisionFor(portal: PortalKey): Promise<GateDecision> {
  const hit = pending.get(portal);
  if (hit && Date.now() - hit.at < 5_000) return hit.p;
  const p = decideStaffPortal(portal);
  pending.set(portal, { p, at: Date.now() });
  return p;
}

export function GateView({ decision, children }: { decision: GateDecision; children: ReactNode }) {
  if (decision.kind === "redirect") return <ClientRedirect to={decision.to} />;
  if (decision.kind === "forbidden") return <PortalForbidden />;
  return <StaffGrantsContext value={decision.grants ?? null}>{children}</StaffGrantsContext>;
}

/**
 * Content studio for an Admin without the Content manager role (live audit admin.md F2): only the
 * pages whose APIs answer the Admin (course list/detail, review queue). Any other studio URL goes
 * to the course list instead of a page full of 403 errors.
 */
export function StudioScope({ children }: { children: ReactNode }) {
  const grants = useStaffGrants();
  const location = useLocation();
  if (grants && studioAccess(grants.portals, grants.data?.map((g) => g.role_key)) === "admin") {
    const to = adminStudioRedirect(location.pathname);
    if (to) return <ClientRedirect to={to} />;
  }
  return <>{children}</>;
}

export function StaffPortalGate({ portal, children }: { portal: PortalKey; children: ReactNode }) {
  const [decision] = useState(() => decisionFor(portal));
  return <GateView decision={use(decision)}>{portal === "studio" ? <StudioScope>{children}</StudioScope> : children}</GateView>;
}

/* ---- Student portal (`/app`) gate — role/portal navigation fix (docs/firebase/agents/role-nav-fix.md) ---- */

/**
 * The portal whose shell rendered last (PortalShell notes it). A staff member who opens Settings
 * from the Trainer portal keeps the Trainer shell around the shared account pages.
 */
let lastShell: PortalKey | null = null;
export function noteShellPortal(portal: PortalKey): void {
  lastShell = portal;
}
export function lastShellPortal(): PortalKey | null {
  return lastShell;
}

/** `GET /me/grants` for the Student area: null = no session / unknown (fail open); 401 → sign-in. */
export type StudentGrants = { kind: "grants"; grants: MyGrantsPortals | null } | { kind: "signin" };

export async function loadStudentGrants(): Promise<StudentGrants> {
  if (!(await hasSessionCookie())) return { kind: "grants", grants: null };
  try {
    return { kind: "grants", grants: await serverApiGet<MyGrantsPortals>("me/grants") };
  } catch (err) {
    if (isApiError(err) && err.status === 401) return { kind: "signin" };
    return { kind: "grants", grants: null };
  }
}

let studentPending: { p: Promise<StudentGrants>; at: number } | null = null;
function studentGrantsFor(): Promise<StudentGrants> {
  if (studentPending && Date.now() - studentPending.at < 5_000) return studentPending.p;
  const p = loadStudentGrants();
  studentPending = { p, at: Date.now() };
  return p;
}

/**
 * Role-gates the Student portal like StaffPortalGate gates the staff portals. The grants are read
 * once when the portal mounts; the decision follows the current path, so a staff member moving
 * from Settings to a student page is sent to their own portal. `children` renders the shell for
 * the chosen portal (the Student shell for students — unchanged for them).
 */
export function StudentPortalGate({ children }: { children: (portal: PortalKey) => ReactNode }) {
  const [p] = useState(studentGrantsFor);
  const loaded = use(p);
  const location = useLocation();
  if (loaded.kind === "signin") return <ClientRedirect to={`/login?next=${encodeURIComponent(`${location.pathname}${location.search}`)}`} />;
  const decision = decideStudentArea(loaded.grants, location.pathname, lastShell);
  if (decision.kind === "redirect") return <ClientRedirect to={decision.to} />;
  if (decision.kind === "forbidden") return <PortalForbidden />;
  return <>{children(decision.portal)}</>;
}

/** Tests: forget the memoised grants and the last shell. */
export function resetStudentGate(): void {
  studentPending = null;
  pending.clear();
  lastShell = null;
}
