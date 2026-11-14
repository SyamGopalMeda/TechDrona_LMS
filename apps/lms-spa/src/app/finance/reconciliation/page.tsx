import type { Metadata } from "next";
import { Reconciliation } from "@/features/finance/components/Finance";

export const metadata: Metadata = { title: "Reconciliation" };

/** FIN-009 */
export default function Page() {
  return <Reconciliation />;
}
