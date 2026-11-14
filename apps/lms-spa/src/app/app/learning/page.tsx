import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { MyCourses } from "@/features/learning/components/MyCourses";

export const metadata: Metadata = { title: "My learning" };

/** STU-004 My courses */
export default function Page() {
  return (
    <div>
      <PageHeader title="My learning" description="Your courses and how far you've got." />
      <MyCourses />
    </div>
  );
}
