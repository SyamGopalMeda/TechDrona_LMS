import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { TrainerCourses } from "@/features/trainer/components/TrainerCourses";

export const metadata: Metadata = { title: "Courses" };

/** TRN-003 */
export default function Page() {
  return (
    <div>
      <PageHeader
        title="Courses"
        eyebrow="TRN-003"
        description="Courses you author or teach."
      />
      <TrainerCourses hrefPattern="/trainer/courses/:id/edit" />
    </div>
  );
}
