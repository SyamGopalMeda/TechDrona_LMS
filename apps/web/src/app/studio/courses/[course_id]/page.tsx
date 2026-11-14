import type { Metadata } from "next";
import { CourseEditor } from "@/features/studio/components/Courses";

export const metadata: Metadata = { title: "Course builder" };

/** CMS-003: the course title is the h1 (rendered by the editor once it loads). */
export default async function Page({ params }: { params: Promise<{ course_id: string }> }) {
  const { course_id } = await params;
  return <CourseEditor courseId={course_id} crumbs={[{ label: "Courses", href: "/studio/courses" }]} />;
}
