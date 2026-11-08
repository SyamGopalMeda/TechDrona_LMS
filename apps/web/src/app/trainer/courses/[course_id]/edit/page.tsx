import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { CourseEditor } from "@/features/studio/components/Courses";

export const metadata: Metadata = { title: "Course builder" };

/** TRN-004 */
export default async function Page({
  params,
}: {
  params: Promise<{ course_id: string }>;
}) {
  const { course_id } = await params;
  return (
    <div>
      <PageHeader title="Course builder" eyebrow="TRN-004" />
      {/* ADM-56: trainers submit for review; publishing is a content-manager action. */}
      <CourseEditor courseId={course_id} canPublish={false} />
    </div>
  );
}
