"use client";

import type { CourseDetailDto } from "@/features/catalog/lib/types";
import type { CourseOverviewDto } from "./types";
import { type Resource, useResource } from "@/lib/api/use-resource";

interface MyEnrolment {
  course_id: string;
  course_slug: string | null;
}

type EnrolmentList = { data?: MyEnrolment[] } | MyEnrolment[];

function enrolmentRows(v: EnrolmentList | undefined): MyEnrolment[] {
  if (!v) return [];
  return Array.isArray(v) ? v : (v.data ?? []);
}

/**
 * Student routes are slug-based (/app/courses/[slug], /app/learn/[course_slug]/…) while LRN
 * endpoints take course_id. The slug resolves through CAT-02 (public / unlisted courses) or,
 * failing that, through the learner's own enrolments (LRN-02): courses made in the LMS editor are
 * ``private`` and never appear in the public catalogue, yet an enrolled student must be able to
 * open them (bug found 2026-11-21: "My learning" listed them but opening one showed an error).
 * A catalogue error is only surfaced when the learner is not enrolled in a course with that slug.
 */
export function useEnrolledCourse(slug: string): { catalog: Resource<CourseDetailDto>; course: Resource<CourseOverviewDto>; courseId: string | null } {
  const catalog = useResource<CourseDetailDto>(`catalog/courses/${encodeURIComponent(slug)}`);
  const enrolments = useResource<EnrolmentList>(catalog.error ? "me/enrolments" : null);
  const enrolled = enrolmentRows(enrolments.data).find((e) => e.course_slug === slug)?.course_id ?? null;
  const courseId = catalog.data?.id ?? enrolled;
  const course = useResource<CourseOverviewDto>(courseId ? `me/courses/${encodeURIComponent(courseId)}` : null);
  // Catalogue failed: wait for the enrolment lookup; only a learner without that course sees the error.
  const settled = Boolean(enrolments.data || enrolments.error);
  const catalogError = catalog.error && !enrolled && settled ? catalog.error : null;
  return { catalog: { ...catalog, error: catalogError } as Resource<CourseDetailDto>, course, courseId };
}

export function lessonHref(slug: string, lessonId: string): string {
  return `/app/learn/${encodeURIComponent(slug)}/${encodeURIComponent(lessonId)}`;
}
