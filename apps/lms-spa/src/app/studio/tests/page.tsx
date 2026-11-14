import type { Metadata } from "next";
import { TestBlueprints } from "@/features/studio/components/Tests";

export const metadata: Metadata = { title: "Template mocks" };

/** CMS-011: test blueprints, labelled "Template mocks" in the studio nav. */
export default function Page() {
  return (
    <TestBlueprints
      hrefPattern="/studio/tests/:id"
      header={{ title: "Template mocks", description: "Test blueprints that trainers assign to batches: settings, review policy, integrity and question draw rules." }}
    />
  );
}
