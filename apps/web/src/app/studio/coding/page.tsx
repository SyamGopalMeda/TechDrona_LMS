import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { CodingProblemList } from "@/features/studio/components/Coding";

export const metadata: Metadata = { title: "Coding problems" };

/** CMS-010 */
export default function Page() {
  return (
    <div>
      <PageHeader title="Coding problems" eyebrow="CMS-010" />
      <CodingProblemList />
    </div>
  );
}
