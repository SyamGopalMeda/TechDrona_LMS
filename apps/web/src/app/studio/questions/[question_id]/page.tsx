import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { QuestionEditor } from "@/features/studio/components/Questions";

export const metadata: Metadata = { title: "Question editor" };

/** CMS-005 */
export default async function Page({ params }: { params: Promise<{ question_id: string }> }) {
  const { question_id } = await params;
  const title = question_id === "new" ? "New question" : "Edit question";
  return (
    <div>
      <PageHeader title={title} breadcrumbs={[{ label: "All questions", href: "/studio/questions" }, { label: title }]} />
      <QuestionEditor questionId={question_id} />
    </div>
  );
}
