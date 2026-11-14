import type { Metadata } from "next";
import { Orders } from "@/features/finance/components/Finance";

export const metadata: Metadata = { title: "Orders" };

/** FIN-004 */
export default function Page() {
  return <Orders />;
}
