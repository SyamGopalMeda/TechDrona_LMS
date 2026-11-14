import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { LessonView } from "@/features/learning/components/LessonView";

export const metadata: Metadata = { title: "Lesson" };

/** PLY-001 video / PLY-002 reading / PLY-005 playback conflict (modal) */
async function Page__server({ params }: { params: Promise<{ course_slug: string; lesson_id: string }> }) {
  const { course_slug, lesson_id } = await params;
  return <LessonView key={lesson_id} slug={decodeURIComponent(course_slug)} lessonId={decodeURIComponent(lesson_id)} />;
}

// SPA: ex-server components run on the client (src/spa/async.tsx).
export default asyncComponent(Page__server, "app/app/learn/[course_slug]/[lesson_id]/page.tsx#Page");
