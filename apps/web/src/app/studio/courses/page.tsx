import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { CourseList } from "@/features/studio/components/Courses";

export const metadata: Metadata = { title: "Courses" };

/** CMS-002 */
export default function Page() {
  return (
    <div>
      <PageHeader title="Courses" eyebrow="CMS-002" />
      <CourseList hrefPattern="/studio/courses/:id" />
    </div>
  );
}
