import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { TicketDetail } from "@/features/support/components/SupportDesk";

export const metadata: Metadata = { title: "Ticket" };

/** SUP-002 */
async function Page__server({ params }: { params: Promise<{ ticket_id: string }> }) {
  const { ticket_id } = await params;
  return <TicketDetail ticketId={ticket_id} />;
}

// SPA: ex-server components run on the client (src/spa/async.tsx).
export default asyncComponent(Page__server, "app/desk/tickets/[ticket_id]/page.tsx#Page");
