import type { Metadata } from "next";
import { StudentDashboard } from "@/features/dashboard/components/StudentDashboard";
import { MyCoursesCard } from "@/features/registration/components/MyCoursesCard";
import { SiteCourseStrip } from "@/features/site-catalog/components/SiteCourseStrip";

export const metadata: Metadata = { title: "Dashboard" };

/** STU-001 */
export default function Page() {
  return <StudentDashboard myCourses={<MyCoursesCard />} courses={<SiteCourseStrip limit={3} />} />;
}
