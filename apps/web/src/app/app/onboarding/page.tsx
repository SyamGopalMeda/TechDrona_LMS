import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { GetStarted } from "@/features/dashboard/components/LearnerHubs";

export const metadata: Metadata = { title: "Get started" };

/** STU-002 get started (goal saving PLC-28/29 is not in the api yet). */
export default function Page() {
  return (
    <div className="max-w-4xl">
      <PageHeader title="Get started" description="Three steps to start preparing for placements." />
      <GetStarted />
    </div>
  );
}
