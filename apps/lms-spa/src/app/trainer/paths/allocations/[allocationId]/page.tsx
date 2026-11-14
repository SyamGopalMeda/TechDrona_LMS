import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { AllocationProgressView } from "@/features/paths/components/AllocationProgressView";

export const metadata: Metadata = { title: "Path progress" };

/** The view renders its header: breadcrumbs back to the path and the allocated batch/learners as the h1. */
async function Page__server({ params }: { params: Promise<{ allocationId: string }> }) {
  const { allocationId } = await params;
  return <AllocationProgressView allocationId={allocationId} />;
}

// SPA: ex-server components run on the client (src/spa/async.tsx).
export default asyncComponent(Page__server, "app/trainer/paths/allocations/[allocationId]/page.tsx#Page");
