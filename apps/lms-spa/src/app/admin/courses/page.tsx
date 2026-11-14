import type { Metadata } from "next";
import { AdminCoursesPage } from "@/features/admin/components/CourseCards";
import { SiteCatalogAdminSection } from "@/features/site-catalog/components/SiteCatalogAdminSection";

export const metadata: Metadata = { title: "Courses" };

/**
 * ADM-016 courses: the website catalogue (live from the Tech Drona website), then the LMS
 * delivery cards grouped Running / Coming soon / Draft / Completed with enrolment and certificate counts.
 */
export default function Page() {
  return <AdminCoursesPage websiteCatalogue={<SiteCatalogAdminSection />} />;
}
