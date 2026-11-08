import type { Metadata } from "next";
import { Subscriptions } from "@/features/finance/components/FinanceCatalog";

export const metadata: Metadata = { title: "Subscriptions" };

/** FIN-006 */
export default function Page() {
  return <Subscriptions />;
}
