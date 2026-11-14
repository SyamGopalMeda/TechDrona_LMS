import type { Metadata } from "next";
import { CourseRegister } from "@/features/registration/components/CourseRegister";
import { loadSiteCatalog } from "@/features/site-catalog/lib/server";

export const metadata: Metadata = { title: "Course registration" };

/** Register for a Tech Drona course inside the LMS (UPI QR payment + proof upload, then status). */
export default async function Page({ params }: { params: Promise<{ slug: string }> }) {
  const { slug: raw } = await params;
  const slug = decodeURIComponent(raw).toLowerCase();
  // The website catalogue's title (the fee plan has its own) and the LMS registration status.
  const course = await loadSiteCatalog()
    .then((c) => c.courses.find((x) => x.slug === slug))
    .catch(() => undefined);
  return <CourseRegister slug={slug} courseTitle={course?.title} courseStatus={course?.regStatusSource === "lms" ? course.regStatus : undefined} />;
}
