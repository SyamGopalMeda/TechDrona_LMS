import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { CourseOverview } from "@/features/learning/components/CourseOverview";

export const metadata: Metadata = { title: "Course" };

/** STU-005 enrolled course overview */
async function Page__server({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return <CourseOverview slug={decodeURIComponent(slug)} />;
}

// SPA: ex-server components run on the client (scripts/sync-from-web.mjs).
export default asyncComponent(Page__server, "app/app/courses/[slug]/page.tsx#Page");
