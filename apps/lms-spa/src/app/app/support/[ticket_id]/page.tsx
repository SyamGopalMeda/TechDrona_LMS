import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { MyTicket } from "@/features/support/components/StudentSupport";

export const metadata: Metadata = { title: "Support ticket" };

/** STU-025 */
async function Page__server({ params }: { params: Promise<{ ticket_id: string }> }) {
  const { ticket_id } = await params;
  return <MyTicket ticketId={ticket_id} />;
}

// SPA: ex-server components run on the client (src/spa/async.tsx).
export default asyncComponent(Page__server, "app/app/support/[ticket_id]/page.tsx#Page");
