import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { LearnerEngage } from "@/features/engage/components/Learner";

export const metadata: Metadata = { title: "Live activities" };

/** STU-030 */
export default function Page() {
  return (
    <div>
      <PageHeader title="Live activities" eyebrow="STU-030" description="Join live polls, quizzes, word clouds and surveys run by your trainers." />
      <LearnerEngage />
    </div>
  );
}
