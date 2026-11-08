import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { AssignmentsList } from "@/features/learning/components/Assignments";

export const metadata: Metadata = { title: "Assignments" };

/** STU-007 */
export default function Page() {
  return (
    <div>
      <PageHeader title="Assignments" />
      <AssignmentsList />
    </div>
  );
}
