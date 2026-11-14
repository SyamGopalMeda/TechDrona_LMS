"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { Button, Card, DashboardHero, EmptyState, LinkButton, ProgressBar, QuickActions, Reveal, StatTile, StatusBadge, ViewAllLink } from "@/components/ui";
import { useIntegrations } from "@/components/shell/Integrations";
import { useActivityTracker } from "@/lib/analytics/use-activity-tracker";
import { formatDate, formatDateTime } from "@/features/catalog/lib/format";
import type { MyTestsResponse, TestListItem } from "@/features/assessment/lib/types";
import { NoCoursesEmptyState } from "@/features/learning/components/BrowseCoursesCta";
import { ContentErrorState, LoadingBlock } from "@/features/learning/components/States";
import type { AssignmentListItemDto, DashboardDto } from "@/features/learning/lib/types";
import { useResource, type Resource } from "@/features/learning/lib/use-resource";

const enc = encodeURIComponent;
const courseHref = (slug: string | null) => (slug ? `/app/courses/${enc(slug)}` : "/app/learning");

/** Tests a student can still act on (ASM-01 statuses). */
const OPEN_TEST_STATUSES = ["in_progress", "available", "scheduled"];
/** Assignment states that still need the student (LRN `my_status`). */
const OPEN_WORK_STATUSES = ["not_submitted", "returned"];

export interface DueItem {
  key: string;
  href: string;
  title: string;
  kind: "Assignment" | "Test";
  status: string;
  statusLabel?: string;
  /** What the date means ("due", "closes", "opens"), plus the ISO date. */
  when: { verb: string; at: string } | null;
  /** Sort key: in-progress first, then soonest date, undated last. */
  rank: number;
}

const FAR_FUTURE = Number.MAX_SAFE_INTEGER;
const time = (iso: string | null | undefined) => (iso ? Date.parse(iso) || FAR_FUTURE : FAR_FUTURE);

/** Merge assignments (LRN-01) and open tests (ASM-01) into one "Due soon" list, soonest first. */
export function dueSoonItems(work: AssignmentListItemDto[], tests: TestListItem[], limit = 6): DueItem[] {
  const fromWork: DueItem[] = work
    .filter((w) => OPEN_WORK_STATUSES.includes(w.my_status))
    .map((w) => ({
      key: `a-${w.id}`,
      href: `/app/assignments/${enc(w.id)}`,
      title: w.title,
      kind: "Assignment",
      status: w.my_status,
      statusLabel: w.my_status === "returned" ? "Returned for changes" : w.my_status === "not_submitted" ? "To do" : undefined,
      when: w.due_at ? { verb: "due", at: w.due_at } : null,
      rank: time(w.due_at),
    }));
  const fromTests: DueItem[] = tests
    .filter((t) => OPEN_TEST_STATUSES.includes(t.status))
    .map((t) => {
      const at = t.status === "scheduled" ? t.available_from : t.available_until;
      return {
        key: `t-${t.test_id}`,
        href: `/app/tests/${enc(t.test_id)}`,
        title: t.title,
        kind: "Test",
        status: t.status,
        when: at ? { verb: t.status === "scheduled" ? "opens" : "closes", at } : null,
        rank: t.status === "in_progress" ? -1 : time(at),
      };
    });
  return [...fromWork, ...fromTests].sort((a, b) => a.rank - b.rank).slice(0, limit);
}

function DueSoon({ work, tests }: { work: AssignmentListItemDto[]; tests: Resource<MyTestsResponse> }) {
  const items = dueSoonItems(work, tests.data?.items ?? []);
  return (
    <Card title="Due soon" icon="clock" description="Assignments and tests waiting for you, soonest first." actions={<ViewAllLink href="/app/tests">All tests</ViewAllLink>}>
      {tests.loading && !tests.data && items.length === 0 ? (
        <LoadingBlock label="Loading what's due" rows={2} />
      ) : items.length === 0 ? (
        <EmptyState
          variant="inline"
          icon="calendar"
          title="Nothing due right now"
          description="When your trainer assigns work or a test opens for you, it appears here."
          action={
            <LinkButton href="/app/practice" variant="secondary" size="sm">
              Practise a topic
            </LinkButton>
          }
        />
      ) : (
        <ul className="divide-y divide-line" aria-label="Due soon">
          {items.map((i) => (
            <li key={i.key} className="flex flex-col gap-1 py-3 sm:flex-row sm:items-center sm:justify-between sm:gap-3">
              <div className="min-w-0">
                <Link href={i.href} className="break-words font-semibold text-fg-link hover:text-fg-link-hover">
                  {i.title}
                </Link>
                <p className="text-sm text-fg-muted">
                  {i.kind}
                  {i.when ? ` · ${i.when.verb} ${formatDateTime(i.when.at)}` : ""}
                </p>
              </div>
              <StatusBadge status={i.status} label={i.statusLabel} className="self-start sm:self-auto" />
            </li>
          ))}
        </ul>
      )}
      {tests.error ? (
        <p className="mt-3 flex flex-wrap items-center gap-2 text-sm text-fg-muted">
          We couldn&apos;t load your tests.
          <Button variant="ghost" size="sm" onClick={() => void tests.reload()}>
            Try again
          </Button>
        </p>
      ) : null}
    </Card>
  );
}

/**
 * STU-001 student dashboard (LRN-01). Only server data is shown; empty sections say so.
 * LRN-01 returns enrolments (no next lesson), assignments (no tests: `tests` is always []),
 * expiring enrolments, certificates, and no greeting name or banners (verified:
 * learning/router.py dashboard); open tests come from ASM-01 `me/tests`.
 * Layout follows design-system §4.4: stat tiles → what needs attention → the rest.
 */
/** `courses`: the real Tech Drona website courses (features/site-catalog SiteCourseStrip), rendered
 * by the server page because the catalogue is loaded server-side. `myCourses`: the enrolled
 * courses / pending registrations card (features/registration MyCoursesCard), shown first. */
export function StudentDashboard({ courses, myCourses }: { courses?: ReactNode; myCourses?: ReactNode } = {}) {
  const { data, error, loading, reload } = useResource<DashboardDto>("me/dashboard");
  const tests = useResource<MyTestsResponse>("me/tests");
  useActivityTracker({ route: "/app", surface: "dashboard", enabled: Boolean(data) });
  // Billing exists only once an online gateway is connected; until then the card shows access only.
  const payments = useIntegrations()?.payments === true;

  if (error) return <ContentErrorState error={error} onRetry={reload} />;
  if (loading && !data) return <LoadingBlock label="Loading your dashboard" rows={4} />;
  if (!data) return null;

  const cont = data.continue_learning;
  const work = data.assigned_work;
  const expiring = data.expiring;
  const openWork = work.filter((w) => OPEN_WORK_STATUSES.includes(w.my_status)).length;
  const openTests = tests.data ? tests.data.items.filter((t) => t.status === "available" || t.status === "in_progress").length : null;

  return (
    <div className="space-y-6">
      <DashboardHero title="Dashboard" description="Pick up where you left off and see what's due next.">
        {/* Website `.adm-kpi` cards; they fade up one after another (Reveal stagger). */}
        <Reveal stagger className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
          <StatTile icon="book" label="Courses in progress" value={cont.length} hint="Keep going" href="/app/learning" />
          <StatTile icon="document" label="Assignments to do" value={openWork} hint="Open or returned" href="/app/assignments" tone={openWork > 0 ? "warning" : "brand"} />
          <StatTile icon="clock" label="Tests open now" value={openTests} hint="Ready to start" href="/app/tests" />
          <StatTile icon="award" tone="highlight" label="Certificates" value={data.certificates.length} hint="Earned so far" href="/app/certificates" />
        </Reveal>
      </DashboardHero>

      {myCourses}

      {courses ? <Reveal as="section" aria-label="Explore Tech Drona courses">{courses}</Reveal> : null}

      <Reveal stagger className="grid gap-6 xl:grid-cols-2">
        <DueSoon work={work} tests={tests} />

        <Card title="Continue learning" icon="book" actions={<ViewAllLink href="/app/learning">My learning</ViewAllLink>}>
          {cont.length === 0 ? (
            <NoCoursesEmptyState variant="inline" size="sm" title="No courses in progress" />
          ) : (
            <ul className="space-y-4">
              {cont.map((c) => (
                <li key={c.id}>
                  <div className="flex items-start justify-between gap-3">
                    <p className="min-w-0 break-words font-semibold text-fg">{c.course_title}</p>
                    <LinkButton href={courseHref(c.course_slug)} size="sm" variant="secondary" aria-label={`Resume ${c.course_title ?? "course"}`}>
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

        <Card title="Quick actions" icon="bolt">
          <QuickActions
            items={[
              { href: "/app/practice", label: "Practice", hint: "Topic-wise questions", icon: "pen" },
              { href: "/app/tests", label: "Tests", hint: "Diagnostic and mock tests", icon: "bolt" },
              { href: "/app/resume", label: "Résumé builder", hint: "Build and download your résumé", icon: "document" },
              { href: "/app/notifications", label: "Notifications", hint: "Announcements and updates", icon: "bell" },
              { href: "/app/support", label: "Get help", hint: "Raise or follow a support ticket", icon: "chat" },
            ]}
          />
        </Card>

        <Card title={payments ? "Access & billing" : "Access"} icon="card" actions={<ViewAllLink href={payments ? "/app/billing" : "/app/access"}>{payments ? "Manage" : "My access"}</ViewAllLink>}>
          {expiring.length === 0 ? (
            <p className="text-sm text-fg-secondary">
              Nothing is expiring soon.{" "}
              <Link href="/app/access" className="text-fg-link underline">
                See what you have access to
              </Link>
              .
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
      </Reveal>
    </div>
  );
}
