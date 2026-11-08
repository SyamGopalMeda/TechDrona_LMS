import type { Metadata } from "next";
import { LessonView } from "@/features/learning/components/LessonView";

export const metadata: Metadata = { title: "Lesson" };

/** PLY-001 video / PLY-002 reading / PLY-005 playback conflict (modal) */
export default async function Page({ params }: { params: Promise<{ course_slug: string; lesson_id: string }> }) {
  const { course_slug, lesson_id } = await params;
  return <LessonView key={lesson_id} slug={decodeURIComponent(course_slug)} lessonId={decodeURIComponent(lesson_id)} />;
}
