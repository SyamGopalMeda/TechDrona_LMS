import type { ReactNode } from "react";
import { PortalShell } from "@/components/shell/PortalShell";
import { StaffPortalGate } from "@/features/staff-portal/StaffPortalGate";

/** Evaluator portal (plan §4.2): the trainer grading screens with authoring hidden. Role-gated for
 * UX (ADM-12); authorisation is enforced by the api. */
export default function Layout({ children }: { children: ReactNode }) {
  return (
    <StaffPortalGate portal="evaluator">
      <PortalShell portal="evaluator">{children}</PortalShell>
    </StaffPortalGate>
  );
}
