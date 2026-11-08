import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { MyCourses } from "@/features/learning/components/MyCourses";

export const metadata: Metadata = { title: "My learning" };

/** STU-004 My courses */
export default function Page() {
  return (
    <div>
      <PageHeader title="My learning" description="Courses you're enrolled in, with progress recorded by the server." />
      <MyCourses />
    </div>
  );
}
