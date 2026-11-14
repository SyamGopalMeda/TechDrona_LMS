"use client";

import { EmptyState, LinkButton } from "@/components/ui";
import type { CourseCardDto, Paged } from "@/features/catalog/lib/types";
import { useResource } from "../lib/use-resource";

export interface CoursesCta {
  /** Empty-state description under "no courses yet". */
  description: string;
  /** Button label; the button always opens Explore courses (/app/courses). */
  label: string;
}

export const EXPLORE_COURSES_HREF = "/app/courses";

/**
 * Copy for the "no courses yet" call to action (My learning, dashboard "Continue learning"),
 * driven by the LMS catalogue (CAT-01) so it never promises free courses that don't exist
 * (live audit F-3: "Browse free courses" opened a page with 0 free courses).
 * - free self-paced courses published → "Browse free courses"
 * - only paid self-paced courses → "Explore courses"
 * - none (or the catalogue can't be read) → the Tech Drona batches on Explore courses
 */
export function coursesCta(courses: CourseCardDto[] | undefined): CoursesCta {
  const list = courses ?? [];
  if (list.some((c) => c.price_type === "free" || c.is_free === true)) {
    return { description: "Free courses need only your account. Pick one to get started.", label: "Browse free courses" };
  }
  if (list.length > 0) return { description: "Pick a course to get started.", label: "Explore courses" };
  return {
    description: "Self-paced courses appear here once they're published. Meanwhile, see Tech Drona's upcoming batches and register when one opens.",
    label: "See upcoming courses",
  };
}

/** `coursesCta` over the live catalogue (one small request; errors fall back to the neutral copy). */
export function useCoursesCta(): CoursesCta {
  const { data } = useResource<Paged<CourseCardDto>>("catalog/courses", { limit: 50 });
  return coursesCta(data?.data);
}

/**
 * "No courses yet" empty state with the catalogue-driven CTA. Mounted only when the learner has
 * no courses, so the catalogue is asked for only then.
 */
export function NoCoursesEmptyState({ title, variant = "card", size = "md" }: { title: string; variant?: "card" | "inline"; size?: "sm" | "md" }) {
  const cta = useCoursesCta();
  return (
    <EmptyState
      variant={variant}
      icon="book"
      title={title}
      description={cta.description}
      action={
        <LinkButton href={EXPLORE_COURSES_HREF} size={size}>
          {cta.label}
        </LinkButton>
      }
    />
  );
}
