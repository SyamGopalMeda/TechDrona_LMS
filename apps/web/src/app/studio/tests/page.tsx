import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { TestBlueprints } from "@/features/studio/components/Tests";

export const metadata: Metadata = { title: "Test blueprints" };

/** CMS-011 */
export default function Page() {
  return (
    <div>
      <PageHeader title="Test blueprints" eyebrow="CMS-011" />
      <TestBlueprints hrefPattern="/studio/tests/:id" />
    </div>
  );
}
