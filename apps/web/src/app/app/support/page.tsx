import type { Metadata } from "next";
import { MyTickets } from "@/features/support/components/StudentSupport";

export const metadata: Metadata = { title: "Support tickets" };

/** STU-025 */
export default function Page() {
  return <MyTickets />;
}
