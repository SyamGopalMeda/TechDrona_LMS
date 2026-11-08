import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { MyPaths } from "@/features/paths/components/Learner";

export const metadata: Metadata = { title: "My paths" };

export default function Page() {
  return (
    <div className="max-w-5xl">
      <PageHeader title="My paths" description="Guided learning paths assigned to you." />
      <MyPaths />
    </div>
  );
}
