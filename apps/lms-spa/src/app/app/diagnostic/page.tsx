import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { DiagnosticLauncher } from "@/features/dashboard/components/LearnerHubs";

export const metadata: Metadata = { title: "Free diagnostic" };

/** STU-003 diagnostic launcher (ASM-01 tests of kind diagnostic). */
export default function Page() {
  return (
    <div className="max-w-4xl">
      <PageHeader title="Free diagnostic" description="A short test that shows your strong and weak topics." />
      <DiagnosticLauncher />
    </div>
  );
}
