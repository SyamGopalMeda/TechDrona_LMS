import type { Metadata } from "next";
import { EmptyState, LinkButton, PageHeader } from "@/components/ui";

export const metadata: Metadata = { title: "Import questions" };

/** CMS-006: bulk import lives on question banks (BulkImportDialog), not on a separate screen. */
export default function Page() {
  return (
    <div>
      <PageHeader title="Import questions" breadcrumbs={[{ label: "All questions", href: "/studio/questions" }, { label: "Import questions" }]} />
      <EmptyState
        icon="document"
        title="Import questions from a question bank"
        description="Bulk import is part of question banks: open Question banks and choose Bulk import, or open a bank and import straight into it. Imported questions start as drafts for review."
        action={<LinkButton href="/studio/question-banks">Go to question banks</LinkButton>}
      />
    </div>
  );
}
