import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { StudioDashboard } from "@/features/studio/components/StudioDashboard";

export const metadata: Metadata = { title: "Content dashboard" };

/** CMS-001 */
export default function Page() {
  return (
    <div>
      <PageHeader title="Content dashboard" eyebrow="CMS-001" />
      <StudioDashboard />
    </div>
  );
}
