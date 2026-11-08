import type { Metadata } from "next";
import Link from "next/link";
import { PageHeader } from "@/components/ui";
import { LearningPath } from "@/features/dashboard/components/LearnerHubs";

export const metadata: Metadata = { title: "Learning path" };

/** STU-006 learning path and recommendations (LRN-01, PLC-26). */
export default function Page() {
  return (
    <div className="max-w-4xl">
      <PageHeader
        title="Learning path"
        description="What to continue and what to practise next."
        actions={
          <Link href="/app/path/my" className="inline-flex h-10 items-center rounded-md border border-line-control px-4 text-sm font-medium hover:bg-surface-hover">
            My assigned paths →
          </Link>
        }
      />
      <LearningPath />
    </div>
  );
}
