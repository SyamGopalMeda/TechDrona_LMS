import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { StudentResume } from "@/features/resume/components/Resume";

export const metadata: Metadata = { title: "Résumé builder" };

/** STU-014 */
export default function Page() {
  return (
    <div>
      <PageHeader title="Résumé builder" description="Build an ATS-friendly résumé, check its score and keep a PDF of it." />
      <StudentResume />
    </div>
  );
}
