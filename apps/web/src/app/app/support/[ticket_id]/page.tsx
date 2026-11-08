import type { Metadata } from "next";
import { MyTicket } from "@/features/support/components/StudentSupport";

export const metadata: Metadata = { title: "Support ticket" };

/** STU-025 */
export default async function Page({ params }: { params: Promise<{ ticket_id: string }> }) {
  const { ticket_id } = await params;
  return <MyTicket ticketId={ticket_id} />;
}
