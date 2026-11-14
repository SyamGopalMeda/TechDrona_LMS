import type { ReactNode } from "react";
import { PortalShell } from "@/components/shell/PortalShell";
import { StaffPortalGate } from "@/features/staff-portal/StaffPortalGate";

/** finance portal (PRD §6). Role-gated for UX (ADM-12); authorisation is enforced by the api. */
export default function Layout({ children }: { children: ReactNode }) {
  return (
    <StaffPortalGate portal="finance">
      <PortalShell portal="finance">{children}</PortalShell>
    </StaffPortalGate>
  );
}
