import type { Metadata } from "next";
import { TicketDetail } from "@/features/support/components/SupportDesk";

export const metadata: Metadata = { title: "Ticket" };

/** SUP-002 */
export default async function Page({ params }: { params: Promise<{ ticket_id: string }> }) {
  const { ticket_id } = await params;
  return <TicketDetail ticketId={ticket_id} />;
}
