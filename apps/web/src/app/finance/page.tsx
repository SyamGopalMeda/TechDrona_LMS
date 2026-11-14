import type { Metadata } from "next";
import { FinanceHome } from "@/features/finance/components/Finance";

export const metadata: Metadata = { title: "Revenue" };

/** FIN-001 */
export default function Page() {
  return <FinanceHome />;
}
