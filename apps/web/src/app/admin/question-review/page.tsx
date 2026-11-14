import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { ReviewQueue } from "@/features/studio/components/Questions";

export const metadata: Metadata = { title: "Question review" };

/** Admin review of questions sent for review (question.review; the reviewer is never the author). */
export default function Page() {
  return (
    <div>
      <PageHeader
        title="Question review"
        description="Questions content managers sent for review. Approve them or ask for changes; the author then publishes. You can't review a question you wrote or edited."
      />
      <ReviewQueue mode="admin" />
    </div>
  );
}
