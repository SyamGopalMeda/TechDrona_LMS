import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { TestsList } from "@/features/trainer/components/TestsList";

export const metadata: Metadata = { title: "Tests" };

/** EVL-003 tests to evaluate (reuses TRN-005 with authoring hidden). */
export default function Page() {
  return (
    <div>
      <PageHeader title="Tests" eyebrow="Evaluator" description="Evaluate submitted attempts and publish results." />
      <TestsList batches={[]} basePath="/evaluator" evaluateOnly />
    </div>
  );
}
