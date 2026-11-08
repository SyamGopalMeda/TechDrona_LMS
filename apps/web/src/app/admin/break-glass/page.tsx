import type { Metadata } from "next";
import { BreakGlass } from "@/features/admin/components/Governance";

export const metadata: Metadata = { title: "Break-glass" };

/** ADM-012 */
export default function Page() {
  return <BreakGlass />;
}
