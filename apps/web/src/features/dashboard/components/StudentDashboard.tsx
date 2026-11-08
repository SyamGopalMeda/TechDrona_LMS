"use client";

import Link from "next/link";
import { Card, EmptyState, PageHeader } from "@/components/ui";
import { useActivityTracker } from "@/lib/analytics/use-activity-tracker";
import { formatDate, formatDateTime } from "@/features/catalog/lib/format";
import { LinkButton, ProgressBar } from "@/features/catalog/components/LinkButton";
import { ContentErrorState, LoadingBlock } from "@/features/learning/components/States";
import type { DashboardDto } from "@/features/learning/lib/types";
import { useResource } from "@/features/learning/lib/use-resource";
import { TestsCard } from "./LearnerHubs";

const courseHref = (slug: string | null) => (slug ? `/app/courses/${encodeURIComponent(slug)}` : "/app/learning");

/**
 * STU-001 student dashboard (LRN-01). Only server data is shown; empty sections say so.
 * LRN-01 returns enrolments (no next lesson), assignments (no tests: `tests` is always []),
 * expiring enrolments, and no greeting name or banners (verified: learning/router.py dashboard);
 * upcoming tests come from ASM-01 `me/tests`.
 */
export function StudentDashboard() {
  const { data, error, loading, reload } = useResource<DashboardDto>("me/dashboard");
  useActivityTracker({ route: "/app", surface: "dashboard", enabled: Boolean(data) });

  if (error) return <ContentErrorState error={error} onRetry={reload} />;
  if (loading && !data) return <LoadingBlock label="Loading your dashboard" rows={4} />;
  if (!data) return null;

  const cont = data.continue_learning;
  const work = data.assigned_work;
  const expiring = data.expiring;

  return (
    <div className="space-y-6">
      <PageHeader title="Dashboard" />

      <div className="grid gap-6 xl:grid-cols-2">
        <Card title="Continue learning" actions={<Link href="/app/learning" className="text-sm font-medium text-fg-link">My learning</Link>}>
          {cont.length === 0 ? (
            <EmptyState title="No courses in progress" description="Start a free course to see it here." action={<LinkButton href="/courses?price_type=free" size="sm">Browse free courses</LinkButton>} />
          ) : (
            <ul className="space-y-4">
              {cont.map((c) => (
                <li key={c.id}>
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="font-medium text-fg">{c.course_title}</p>
                    </div>
                    <LinkButton href={courseHref(c.course_slug)} size="sm" aria-label={`Resume ${c.course_title ?? "course"}`}>
                      Resume
                    </LinkButton>
                  </div>
                  <div className="mt-2">
                    <ProgressBar value={c.progress_pct} label={`Progress in ${c.course_title ?? "course"}`} />
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Upcoming">
          {work.length === 0 ? (
            <p className="text-sm text-fg-muted">Nothing due. When your trainer assigns work, it appears here.</p>
          ) : (
            <ul className="divide-y divide-line">
              {work.map((w) => (
                <li key={w.id} className="flex justify-between gap-3 py-2 text-sm">
                  <Link href={`/app/assignments/${encodeURIComponent(w.id)}`} className="text-fg-link hover:text-fg-link-hover">
                    {w.title}
                  </Link>
                  <span className="shrink-0 text-fg-muted">
                    {w.my_status === "returned" ? "Returned for changes" : "Assignment"}
                    {w.due_at ? ` · due ${formatDateTime(w.due_at)}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <TestsCard
          title="Upcoming tests"
          statuses={["in_progress", "available", "scheduled"]}
          limit={5}
          empty={{ title: "No tests coming up", description: "Tests assigned to you and free tests appear here." }}
        />

        <Card title="Access & billing" actions={<Link href="/app/billing" className="text-sm font-medium text-fg-link">Manage</Link>}>
          {expiring.length === 0 ? (
            <p className="text-sm text-fg-muted">
              Nothing is expiring soon. <Link href="/app/access" className="text-fg-link underline">See what you have access to</Link>.
            </p>
          ) : (
            <ul className="space-y-1 text-sm">
              {expiring.map((e) => (
                <li key={e.id} className="text-warning-fg">
                  {e.course_title ?? "Course"} access ends {formatDate(e.expires_at)}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}
