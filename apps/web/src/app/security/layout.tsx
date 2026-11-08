import type { ReactNode } from "react";
import { PortalShell } from "@/components/shell/PortalShell";
import { StaffPortalGate } from "@/features/staff-portal/StaffPortalGate";

/** security portal (PRD §6). Role-gated for UX (ADM-12); authorisation is enforced by the api. */
export default function Layout({ children }: { children: ReactNode }) {
  return (
    <StaffPortalGate portal="security">
      <PortalShell portal="security">{children}</PortalShell>
    </StaffPortalGate>
  );
}
