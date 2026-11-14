import type { Metadata } from "next";
import { LinkButton, PageHeader } from "@/components/ui";
import { QuestionBank } from "@/features/studio/components/Questions";

export const metadata: Metadata = { title: "All questions" };

/** CMS-004: every question across banks (the nav calls it "All questions"). */
export default function Page() {
  return (
    <div>
      <PageHeader
        title="All questions"
        description="Every question you can see, across all question banks. Search, filter and open one to edit or send it for review."
        actions={
          <>
            <LinkButton href="/studio/question-banks" variant="secondary">
              Browse question banks
            </LinkButton>
            <LinkButton href="/studio/questions/new">New question</LinkButton>
          </>
        }
      />
      <QuestionBank />
    </div>
  );
}
