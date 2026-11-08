import type { Metadata } from "next";
import { CourseOverview } from "@/features/learning/components/CourseOverview";

export const metadata: Metadata = { title: "Course" };

/** STU-005 enrolled course overview */
export default async function Page({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return <CourseOverview slug={decodeURIComponent(slug)} />;
}
