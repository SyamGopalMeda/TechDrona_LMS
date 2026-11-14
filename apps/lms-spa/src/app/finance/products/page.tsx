import type { Metadata } from "next";
import { Products } from "@/features/finance/components/FinanceCatalog";

export const metadata: Metadata = { title: "Products and prices" };

/** FIN-002 */
export default function Page() {
  return <Products />;
}
