import { createContext, Suspense, use, useContext, useState, type ReactNode } from "react";
import { useLocation } from "react-router";
import { Skeleton } from "@/components/ui";
import { isApiError } from "@/lib/api/errors";
import { hasSessionCookie } from "@/lib/api/server";
import { clearIdentityCache, getIdentity, peekIdentity } from "@/lib/api/session-cache";
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
 *
 * The grants come from the session cache (src/lib/api/session-cache.ts, docs/perf/spa-requests.md):
 * usually already there (prefetched at app start, or read by an earlier portal), so the decision is
 * made on the first render without a request; otherwise the portal skeleton shows meanwhile.
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
    grants = await getIdentity<MyGrantsPortals>("me/grants");
  } catch (err) {
    if (isApiError(err) && err.status === 401) return { kind: "redirect", to: `/login?next=${encodeURIComponent(def.prefix)}` };
    return { kind: "enter" };
  }
  return decideFromGrants(portal, grants);
}

function decideFromGrants(portal: PortalKey, grants: MyGrantsPortals): GateDecision {
  if (canEnterPortal(grants.portals, portal, grants.data?.map((g) => g.role_key))) return { kind: "enter", grants };
  const home = homePortal(grants.portals);
  if (home) return { kind: "redirect", to: home };
  return { kind: "forbidden" };
}

/** A promise React's `use()` reads synchronously (no suspension, no request). */
function fulfilled<T>(value: T): Promise<T> {
  const p = Promise.resolve(value) as Promise<T> & { status?: string; value?: T };
  p.status = "fulfilled";
  p.value = value;
  return p;
}

/* One decision per portal entry; memoised briefly so a suspended first render reuses it. */
const pending = new Map<PortalKey, { p: Promise<GateDecision>; at: number }>();
function decisionFor(portal: PortalKey): Promise<GateDecision> {
  const cached = peekIdentity<MyGrantsPortals>("me/grants");
  if (cached) return fulfilled(decideFromGrants(portal, cached));
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

/**
 * Shown while the gate waits for the grants (only when they are not cached yet): the portal
 * header bar and content skeleton, instead of a blank page.
 */
export function PortalSkeleton() {
  return (
    <div aria-busy="true" className="min-h-dvh bg-surface-canvas">
      <span className="sr-only">Loading…</span>
      <div className="h-topbar border-b border-line bg-surface" />
      <div className="mx-auto max-w-6xl space-y-4 p-4 sm:p-6">
        <Skeleton className="h-8 w-1/3" />
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-32 w-full" />
      </div>
    </div>
  );
}

function StaffPortalGateInner({ portal, children }: { portal: PortalKey; children: ReactNode }) {
  const [decision] = useState(() => decisionFor(portal));
  return <GateView decision={use(decision)}>{portal === "studio" ? <StudioScope>{children}</StudioScope> : children}</GateView>;
}

export function StaffPortalGate({ portal, children }: { portal: PortalKey; children: ReactNode }) {
  return (
    <Suspense fallback={<PortalSkeleton />}>
      <StaffPortalGateInner portal={portal}>{children}</StaffPortalGateInner>
    </Suspense>
  );
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
    return { kind: "grants", grants: await getIdentity<MyGrantsPortals>("me/grants") };
  } catch (err) {
    if (isApiError(err) && err.status === 401) return { kind: "signin" };
    return { kind: "grants", grants: null };
  }
}

let studentPending: { p: Promise<StudentGrants>; at: number } | null = null;
function studentGrantsFor(): Promise<StudentGrants> {
  const cached = peekIdentity<MyGrantsPortals>("me/grants");
  if (cached) return fulfilled({ kind: "grants", grants: cached });
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
  return (
    <Suspense fallback={<PortalSkeleton />}>
      <StudentPortalGateInner>{children}</StudentPortalGateInner>
    </Suspense>
  );
}

function StudentPortalGateInner({ children }: { children: (portal: PortalKey) => ReactNode }) {
  const [p] = useState(studentGrantsFor);
  const loaded = use(p);
  const location = useLocation();
  if (loaded.kind === "signin") return <ClientRedirect to={`/login?next=${encodeURIComponent(`${location.pathname}${location.search}`)}`} />;
  const decision = decideStudentArea(loaded.grants, location.pathname, lastShell);
  if (decision.kind === "redirect") return <ClientRedirect to={decision.to} />;
  if (decision.kind === "forbidden") return <PortalForbidden />;
  return <>{children(decision.portal)}</>;
}

/** Tests: forget the memoised grants (and the cached identity) and the last shell. */
export function resetStudentGate(): void {
  studentPending = null;
  pending.clear();
  lastShell = null;
  clearIdentityCache();
}
