"use client";

import { CourseList } from "@/features/studio/components/Courses";

/**
 * TRN-003 trainer courses (ADM-41). The api decides ownership (WS4): a batch trainer's new course is
 * a company course, enrollable by the company's batch learners and staff, never in the public catalogue.
 */
export function TrainerCourses({ hrefPattern }: { hrefPattern: string }) {
  return (
    <div className="space-y-4">
      <p className="text-sm text-fg-muted">New courses you create are company courses: your batches can use them, and they never appear in the public catalogue.</p>
      <CourseList hrefPattern={hrefPattern} />
    </div>
  );
}
