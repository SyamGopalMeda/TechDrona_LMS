import type { ReactNode } from "react";
import { PortalShell } from "@/components/shell/PortalShell";
import { StudentPortalGate } from "@/features/staff-portal/StaffPortalGate";

/**
 * student portal (PRD §6). Authorisation is enforced by the api.
 *
 * SPA override (spa-overrides/app/app/layout.tsx): role-gated for UX like the staff portals. A
 * staff-only account opening a student page goes to its own portal; the shared account pages
 * (settings, account status) render inside that account's staff shell (StudentPortalGate).
 */
export default function Layout({ children }: { children: ReactNode }) {
  return <StudentPortalGate>{(portal) => <PortalShell portal={portal}>{children}</PortalShell>}</StudentPortalGate>;
}
