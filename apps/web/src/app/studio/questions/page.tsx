import type { Metadata } from "next";
import Link from "next/link";
import { PageHeader } from "@/components/ui";
import { QuestionBank } from "@/features/studio/components/Questions";

export const metadata: Metadata = { title: "Question bank" };

/** CMS-004 */
export default function Page() {
  return (
    <div>
      <PageHeader
        title="Question bank"
        eyebrow="CMS-004"
        actions={
          <Link href="/studio/question-banks" className="inline-flex h-10 items-center text-sm text-fg-link underline">
            Browse question banks
          </Link>
        }
      />
      <QuestionBank />
    </div>
  );
}
