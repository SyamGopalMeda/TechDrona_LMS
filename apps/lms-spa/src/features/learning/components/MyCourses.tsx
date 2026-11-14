"use client";

import { Badge, LoadingBlock } from "@/components/ui";
import { LinkButton, ProgressBar } from "@/features/catalog/components/LinkButton";
import type { EnrolmentDto } from "../lib/types";
import { NoCoursesEmptyState } from "./BrowseCoursesCta";
import { ContentErrorState } from "./States";
import { formatDate } from "@/lib/format";
import { useAllPages } from "@/lib/api/use-resource";

/**
 * STU-004 My courses (LRN-02). Progress is the server value. LRN-02 is cursor-paginated
 * (default 100, learn R5): every page is followed.
 */
export function MyCourses() {
  const { data, error, loading, reload } = useAllPages<EnrolmentDto>("me/enrolments");

  if (loading && !data) return <LoadingBlock label="Loading your courses" size="card" />;
  if (error) return <ContentErrorState error={error} onRetry={reload} />;
  const rows = data?.data ?? [];
  if (rows.length === 0) {
    return <NoCoursesEmptyState title="You haven't enrolled in a course yet" />;
  }
  return (
    <div>
      <ul className="grid gap-4 md:grid-cols-2" aria-label="Enrolled courses">
        {rows.map((e) => {
          const expired = e.status === "expired";
          const title = e.course_title ?? "Course";
          const overview = e.course_slug ? `/app/courses/${encodeURIComponent(e.course_slug)}` : null;
          return (
            <li key={e.id} className="flex flex-col rounded-xl border border-line bg-surface p-5 shadow-xs">
              <div className="flex items-start justify-between gap-2">
                <h2 className="font-display text-base font-semibold text-fg">{title}</h2>
                {e.completed_at ? <Badge tone="success">Completed</Badge> : expired ? <Badge tone="warning">Access ended</Badge> : null}
              </div>
              <div className="mt-3">
                <ProgressBar value={e.progress_pct} label={`Progress in ${title}`} />
              </div>
              {e.expires_at ? <p className="mt-2 text-xs text-fg-muted">{expired ? "Access ended" : "Access until"} {formatDate(e.expires_at)}</p> : null}
              <div className="mt-4 flex flex-wrap gap-2">
                {overview ? (
                  <LinkButton href={overview} variant="secondary" size="sm" aria-label={`Open ${title} overview`}>
                    Course overview
                  </LinkButton>
                ) : null}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
