import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { CourseEditor } from "@/features/studio/components/Courses";

export const metadata: Metadata = { title: "Course builder" };

/** TRN-004: the course title is the h1 (rendered by the editor once it loads). */
async function Page__server({
  params,
}: {
  params: Promise<{ course_id: string }>;
}) {
  const { course_id } = await params;
  // ADM-56: trainers submit for review; publishing is a content-manager action.
  return <CourseEditor courseId={course_id} canPublish={false} crumbs={[{ label: "Courses", href: "/trainer/courses" }]} />;
}

// SPA: ex-server components run on the client (src/spa/async.tsx).
export default asyncComponent(Page__server, "app/trainer/courses/[course_id]/edit/page.tsx#Page");
