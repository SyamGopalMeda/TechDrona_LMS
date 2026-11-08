import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { AllocationProgressView } from "@/features/paths/components/AllocationProgressView";

export const metadata: Metadata = { title: "Path progress" };

export default async function Page({ params }: { params: Promise<{ allocationId: string }> }) {
  const { allocationId } = await params;
  return (
    <div>
      <PageHeader title="Path progress" />
      <AllocationProgressView allocationId={allocationId} />
    </div>
  );
}
