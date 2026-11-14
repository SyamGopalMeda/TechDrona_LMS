import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { MentorSessions } from "@/features/mentor/components/Mentor";

export const metadata: Metadata = { title: "Sessions" };

/** MEN-001 */
export default function Page() {
  return (
    <div>
      <PageHeader title="Sessions" description="Upcoming sessions, feedback you owe and résumé reviews." />
      <MentorSessions />
    </div>
  );
}
