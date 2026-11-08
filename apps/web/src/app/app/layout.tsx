import type { ReactNode } from "react";
import { PortalShell } from "@/components/shell/PortalShell";

/** student portal (PRD §6). Authorisation is enforced by the api. */
export default function Layout({ children }: { children: ReactNode }) {
  return <PortalShell portal="student">{children}</PortalShell>;
}
