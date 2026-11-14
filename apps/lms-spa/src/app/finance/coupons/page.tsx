import type { Metadata } from "next";
import { Coupons } from "@/features/finance/components/FinanceCatalog";

export const metadata: Metadata = { title: "Coupons" };

/** FIN-003 */
export default function Page() {
  return <Coupons />;
}
