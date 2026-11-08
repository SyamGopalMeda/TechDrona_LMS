import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { ReviewQueue } from "@/features/studio/components/Questions";

export const metadata: Metadata = { title: "Review queue" };

/** CMS-007 */
export default function Page() {
  return (
    <div>
      <PageHeader title="Review queue" eyebrow="CMS-007" description="You can't review content you wrote." />
      <ReviewQueue />
    </div>
  );
}
