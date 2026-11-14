import type { Metadata } from "next";
import { AllocationProgressView } from "@/features/paths/components/AllocationProgressView";

export const metadata: Metadata = { title: "Path progress" };

/** The view renders its header: breadcrumbs back to the path and the allocated batch/learners as the h1. */
export default async function Page({ params }: { params: Promise<{ allocationId: string }> }) {
  const { allocationId } = await params;
  return <AllocationProgressView allocationId={allocationId} />;
}
