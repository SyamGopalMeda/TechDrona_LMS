import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { StudentMentoring } from "@/features/mentor/student/Mentoring";

export const metadata: Metadata = { title: "Mock interviews" };

/** STU-013 */
export default function Page() {
  return (
    <div>
      <PageHeader title="Mock interviews" description="Book 1:1 sessions with a mentor and see their feedback." />
      <StudentMentoring />
    </div>
  );
}
