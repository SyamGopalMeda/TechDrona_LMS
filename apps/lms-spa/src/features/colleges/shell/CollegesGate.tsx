/**
 * Admin-only gate for /colleges (UX only: the lmsApi proxy re-checks every API call and fails closed).
 *
 * Same rule as the proxy (functions-lms/lms_edge/college_portal.py `is_admin`) and the hub's `can_open_colleges`:
 * the caller holds the Admin portal (`/admin` in GET /me/grants `portals`, or a live super_admin grant).
 *  - no LMS session → /login?next=<this page>;
 *  - signed in without Admin → their own home portal (StaffPortalGate), or "no access yet";
 *  - grants unknown (api down) → enter; the portal API then answers 401/403/503 and the shell shows it.
 */
import { use, useState, type ReactNode } from "react";
import { useLocation } from "react-router";
import { StaffPortalGate } from "@/features/staff-portal/StaffPortalGate";
import { ClientRedirect } from "@/spa/boundary";
import { probeSession } from "@/spa/session";

function SessionRequired({ children }: { children: ReactNode }) {
  const [probe] = useState(() => probeSession());
  const session = use(probe);
  const location = useLocation();
  if (session === "no") return <ClientRedirect to={`/login?next=${encodeURIComponent(`${location.pathname}${location.search}`)}`} />;
  return <>{children}</>;
}

export function CollegesGate({ children }: { children: ReactNode }) {
  return (
    <SessionRequired>
      <StaffPortalGate portal="admin">{children}</StaffPortalGate>
    </SessionRequired>
  );
}
