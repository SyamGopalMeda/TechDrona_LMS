import type { Metadata } from "next";
import { PageHeader, Tabs } from "@/components/ui";
import { TrainerAssignments } from "@/features/trainer/components/Grading";
import { AssignmentManagerList } from "@/features/learning/assignment-manager/AssignmentManagerList";

export const metadata: Metadata = { title: "Assignments" };

/** TRN-012 */
export default function Page() {
  return (
    <div>
      <PageHeader
        title="Assignments"
        eyebrow="TRN-012"
        description="Build assignments from sections and bank questions, set marks, then allocate them to a batch with a schedule."
      />
      <Tabs
        label="Assignment kinds"
        items={[
          { id: "structured", label: "Sections & questions", content: <AssignmentManagerList /> },
          { id: "classic", label: "Single submission", content: <TrainerAssignments /> },
        ]}
      />
    </div>
  );
}
