import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { MentorStudents } from "@/features/mentor/components/Mentor";

export const metadata: Metadata = { title: "Students" };

/** MEN-004 */
export default function Page() {
  return (
    <div>
      <PageHeader title="Students" description="Students you mentor, their batch, target companies and next session." />
      <MentorStudents />
    </div>
  );
}
