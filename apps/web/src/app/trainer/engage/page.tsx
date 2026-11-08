import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { EngageActivities } from "@/features/engage/components/ActivityList";

export const metadata: Metadata = { title: "Engage" };

/** TRN-020 */
export default function Page() {
  return (
    <div>
      <PageHeader title="Engage" eyebrow="TRN-020" description="Run live polls, word clouds, quizzes and surveys with your batch." />
      <EngageActivities />
    </div>
  );
}
