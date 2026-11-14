import type { Metadata } from "next";
import { Refunds } from "@/features/finance/components/Finance";

export const metadata: Metadata = { title: "Refunds" };

/** FIN-005 */
export default function Page() {
  return <Refunds />;
}
