"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api/client";
import { PORTALS, type PortalKey } from "@/lib/nav/portals";
import { canEnterPortal, homePortal, type MyGrantsPortals } from "@/features/staff-portal/access";
import { lastShellPortal } from "@/features/staff-portal/StaffPortalGate";

/**
 * Who is looking at a shared account page (`/app/settings/**`, `/app/account-status`). Since the
 * role/portal navigation fix those pages render inside a staff member's own shell, so they must not
 * ask staff for student-only details or link them to student pages that bounce them home
 * (live audit admin.md F8 / M13, staff-portals.md F4).
 */
export interface AccountScope {
  /** The account can open the Student portal (a student, or a staff member who is also a student). */
  student: boolean;
  /** Where "Go to my dashboard" leads: `/app` for students, else the staff shell's home. */
  home: string;
  /** Name of that home, for "Go to …" ("my dashboard" for students, "the Trainer portal"…). */
  homeTitle: string;
}

/** Unknown grants (no session yet, api down): student wording and links, as before. */
export const STUDENT_SCOPE: AccountScope = { student: true, home: PORTALS.student.prefix, homeTitle: "my dashboard" };

const portalHome = (key: PortalKey) => {
  const def = PORTALS[key];
  const top = def.parent ? PORTALS[def.parent] : def;
  return { home: top.prefix, homeTitle: `the ${top.title} portal` };
};

/**
 * Pure decision (unit-tested). `grants` null or without portals = unknown → STUDENT_SCOPE.
 * A staff-only account's home is the staff shell it came from (when it may open it), else its
 * own home portal (the same rule StudentPortalGate uses to pick the shell).
 */
export function accountScope(grants: MyGrantsPortals | null | undefined, lastShell: PortalKey | null = null): AccountScope {
  if (!grants?.portals?.length) return STUDENT_SCOPE;
  const roleKeys = grants.data?.map((g) => g.role_key);
  if (canEnterPortal(grants.portals, "student", roleKeys)) return STUDENT_SCOPE;
  if (lastShell && lastShell !== "student" && canEnterPortal(grants.portals, lastShell, roleKeys)) return { student: false, ...portalHome(lastShell) };
  const home = homePortal(grants.portals);
  const key = Object.values(PORTALS).find((p) => p.prefix === home)?.key;
  return key && key !== "student" ? { student: false, ...portalHome(key) } : STUDENT_SCOPE;
}

/**
 * `GET /me/grants` (silently: no step-up / restriction / sign-in handling, like the portal
 * switcher) → AccountScope. `null` while loading, so a page can wait instead of flashing student
 * fields at staff. Failures fall back to STUDENT_SCOPE.
 */
export function useAccountScope(): AccountScope | null {
  const [scope, setScope] = useState<AccountScope | null>(null);
  useEffect(() => {
    let live = true;
    api
      .get<MyGrantsPortals>("me/grants", { handle: { stepUp: false, restriction: false, auth: false, sessionChoice: false } })
      .then((g) => {
        if (live) setScope(accountScope(g, lastShellPortal()));
      })
      .catch(() => {
        if (live) setScope(STUDENT_SCOPE);
      });
    return () => {
      live = false;
    };
  }, []);
  return scope;
}
