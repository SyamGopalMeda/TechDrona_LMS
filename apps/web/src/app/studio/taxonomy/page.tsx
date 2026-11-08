import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { TaxonomyManager } from "@/features/studio/components/Taxonomy";

export const metadata: Metadata = { title: "Taxonomy" };

/** CMS-008: subjects and topics (PLC-01..03). */
export default function Page() {
  return (
    <div>
      <PageHeader title="Taxonomy" eyebrow="CMS-008" />
      <TaxonomyManager />
    </div>
  );
}
