import type { Metadata } from "next";
import { SupportUnblockTriage } from "@/features/support/components/SupportDesk";

export const metadata: Metadata = { title: "Unblock requests" };

/** SUP-005 */
export default function Page() {
  return <SupportUnblockTriage />;
}
