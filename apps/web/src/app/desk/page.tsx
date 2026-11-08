import type { Metadata } from "next";
import { TicketQueue } from "@/features/support/components/SupportDesk";

export const metadata: Metadata = { title: "Support desk" };

/** SUP-001 */
export default function Page() {
  return <TicketQueue />;
}
