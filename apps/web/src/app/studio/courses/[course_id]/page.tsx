import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { CourseEditor } from "@/features/studio/components/Courses";

export const metadata: Metadata = { title: "Course builder" };

/** CMS-003 */
export default async function Page({ params }: { params: Promise<{ course_id: string }> }) {
  const { course_id } = await params;
  return (
    <div>
      <PageHeader title="Course builder" eyebrow="CMS-003" />
      <CourseEditor courseId={course_id} />
    </div>
  );
}
