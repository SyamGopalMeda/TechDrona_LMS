import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { MentorSlots } from "@/features/mentor/components/Slots";

export const metadata: Metadata = { title: "Availability" };

/** MEN-002 */
export default function Page() {
  return (
    <div>
      <PageHeader title="Availability" eyebrow="MEN-002" description="Publish 30, 45 or 60 minute slots. Cancelling a booked session gives the student their credit back." />
      <MentorSlots />
    </div>
  );
}
