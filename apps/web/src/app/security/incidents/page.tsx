import type { Metadata } from "next";
import { Incidents } from "@/features/security-admin/components/Incidents";

export const metadata: Metadata = { title: "Incidents" };

/** ADM-11: security incident register (SEC-37..39). */
export default function Page() {
  return <Incidents />;
}
