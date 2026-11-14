import { Suspense, type ReactNode } from "react";
import { CollegesGate } from "@/features/colleges/shell/CollegesGate";
import { PortalBoot } from "@/features/colleges/shell/PortalBoot";
import { PortalLayout } from "@/features/colleges/shell/PortalLayout";

/**
 * Tech Drona Outreach Portal (College Data / "Colleges Management") as React routes: a full-screen layout of
 * its own (not the LMS admin shell), Admin-only (CollegesGate). The data API stays the Cloud Run portal server,
 * called at /college-portal/api/* through the lmsApi proxy. docs/colleges-react/PORTING-GUIDE.md.
 */
export default function Layout({ children }: { children: ReactNode }) {
  return (
    <Suspense fallback={<PortalBoot />}>
      <CollegesGate>
        <PortalLayout>{children}</PortalLayout>
      </CollegesGate>
    </Suspense>
  );
}
