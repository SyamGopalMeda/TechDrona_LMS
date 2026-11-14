import type { Metadata } from "next";
import { CourseList } from "@/features/studio/components/Courses";

export const metadata: Metadata = { title: "Courses" };

/** CMS-002 */
export default function Page() {
  return <CourseList hrefPattern="/studio/courses/:id" header={{ title: "Courses", description: "Author course drafts, send them for review and publish new versions." }} />;
}
