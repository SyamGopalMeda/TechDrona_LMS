import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { QuestionEditor } from "@/features/studio/components/Questions";

export const metadata: Metadata = { title: "Question editor" };

/** CMS-005 */
export default async function Page({ params }: { params: Promise<{ question_id: string }> }) {
  const { question_id } = await params;
  return (
    <div>
      <PageHeader title="Question editor" eyebrow="CMS-005" />
      <QuestionEditor questionId={question_id} />
    </div>
  );
}
