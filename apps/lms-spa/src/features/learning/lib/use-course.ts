"use client";

import type { CourseDetailDto } from "@/features/catalog/lib/types";
import type { CourseOverviewDto } from "./types";
import { type Resource, useResource } from "@/lib/api/use-resource";

/**
 * Student routes are slug-based (/app/courses/[slug], /app/learn/[course_slug]/…) while LRN
 * endpoints take course_id: resolve the slug via CAT-02, then load LRN-04.
 */
export function useEnrolledCourse(slug: string): { catalog: Resource<CourseDetailDto>; course: Resource<CourseOverviewDto>; courseId: string | null } {
  const catalog = useResource<CourseDetailDto>(`catalog/courses/${encodeURIComponent(slug)}`);
  const courseId = catalog.data?.id ?? null;
  const course = useResource<CourseOverviewDto>(courseId ? `me/courses/${encodeURIComponent(courseId)}` : null);
  return { catalog, course, courseId };
}

export function lessonHref(slug: string, lessonId: string): string {
  return `/app/learn/${encodeURIComponent(slug)}/${encodeURIComponent(lessonId)}`;
}
