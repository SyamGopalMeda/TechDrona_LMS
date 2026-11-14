import type { Metadata } from "next";
import { TicketQueue } from "@/features/support/components/SupportDesk";

export const metadata: Metadata = { title: "Ticket queue" };

/** SUP-001 */
export default function Page() {
  return <TicketQueue />;
}
