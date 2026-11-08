import type { Metadata } from "next";
import { Invoices } from "@/features/finance/components/Finance";

export const metadata: Metadata = { title: "Invoices" };

/** FIN-007 */
export default function Page() {
  return <Invoices />;
}
