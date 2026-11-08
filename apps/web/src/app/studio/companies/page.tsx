import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { CompaniesManager } from "@/features/studio/components/Companies";

export const metadata: Metadata = { title: "Companies" };

/** CMS-009: companies and role paths (PLC-16..18). */
export default function Page() {
  return (
    <div>
      <PageHeader title="Companies" eyebrow="CMS-009" />
      <CompaniesManager />
    </div>
  );
}
