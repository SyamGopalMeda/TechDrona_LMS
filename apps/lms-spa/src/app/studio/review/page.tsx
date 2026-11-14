import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { ReviewQueue } from "@/features/studio/components/Questions";

export const metadata: Metadata = { title: "Review queue" };

/** CMS-007 */
export default function Page() {
  return (
    <div>
      <PageHeader
        title="Review queue"
        description="Questions and courses other authors sent for review. Any content manager except the author can review an item, so your own drafts are not listed here."
      />
      <ReviewQueue />
    </div>
  );
}
