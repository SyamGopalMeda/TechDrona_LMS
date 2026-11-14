"use client";

import Link from "next/link";
import { useMemo } from "react";
import type { ReactNode } from "react";
import { Card, EmptyState, ErrorState, LinkButton, LoadingBlock, StatusBadge, type EmptyStateIcon } from "@/components/ui";
import { formatDateTime } from "@/features/auth/lib/format";
import { useResource } from "@/features/account/lib/use-resource";
import type { MyTestsResponse, TestListItem } from "@/features/assessment/lib/types";
import type { DashboardDto } from "@/features/learning/lib/types";
import type { RecommendationsResponse, SubjectsResponse, TaxonomyNode } from "@/features/practice/lib/types";

/*
 * STU-002/003/006/015 hubs and the dashboard's "Upcoming tests" (FE-05, FE-23). Built only on
 * existing endpoints: ASM-01 `me/tests`, PLC-01 `placement/subjects`, PLC-26 `me/recommendations`,
 * LRN-01 `me/dashboard`. Goal saving (PLC-28/29) and bookmarks are not in the api yet, so those
 * parts say so rather than pretend.
 */

const enc = encodeURIComponent;
const cardLink = "inline-flex min-h-6 items-center text-sm font-semibold text-fg-link hover:text-fg-link-hover";

function Loading({ label }: { label: string }) {
  return <LoadingBlock label={label} rows={2} size="row" />;
}

function TestRow({ t }: { t: TestListItem }) {
  const when = t.status === "scheduled" ? (t.available_from ? `opens ${formatDateTime(t.available_from)}` : "") : t.available_until ? `closes ${formatDateTime(t.available_until)}` : "";
  return (
    <li className="flex flex-col gap-1 py-2 text-sm sm:flex-row sm:items-center sm:justify-between">
      <span className="min-w-0">
        <Link href={`/app/tests/${enc(t.test_id)}`} className="font-medium text-fg-link hover:text-fg-link-hover">
          {t.title}
        </Link>{" "}
        <StatusBadge status={t.status} />
      </span>
      <span className="shrink-0 text-fg-muted">
        {Math.round(t.duration_seconds / 60)} min{when ? ` · ${when}` : ""}
      </span>
    </li>
  );
}

/** Tests from ASM-01, filtered by kind/status. */
export function TestsCard({
  title,
  kinds,
  statuses,
  empty,
  limit,
}: {
  title: string;
  kinds?: string[];
  statuses?: string[];
  empty: { title: string; description?: string; icon?: EmptyStateIcon; action?: ReactNode };
  limit?: number;
}) {
  const tests = useResource<MyTestsResponse>("me/tests");
  const items = (tests.data?.items ?? []).filter((t) => (!kinds || kinds.includes(t.test_kind)) && (!statuses || statuses.includes(t.status))).slice(0, limit ?? 50);
  return (
    <Card title={title} actions={<Link href="/app/tests" className={cardLink}>All tests</Link>}>
      {tests.error ? (
        <ErrorState error={tests.error} onRetry={tests.reload} />
      ) : tests.loading && !tests.data ? (
        <Loading label="Loading tests…" />
      ) : items.length === 0 ? (
        <EmptyState variant="inline" icon={empty.icon ?? "calendar"} title={empty.title} description={empty.description} action={empty.action} />
      ) : (
        <ul className="divide-y divide-line" aria-label={title}>
          {items.map((t) => (
            <TestRow key={t.test_id} t={t} />
          ))}
        </ul>
      )}
    </Card>
  );
}

/** Root subject of a topic (walks parent ids in the PLC-01 tree). */
export function subjectOf(topicId: string, nodes: TaxonomyNode[]): TaxonomyNode | undefined {
  const byId = new Map<string, TaxonomyNode>();
  const walk = (ns: TaxonomyNode[]) => ns.forEach((n) => (byId.set(n.id, n), walk(n.children ?? [])));
  walk(nodes);
  let cur = byId.get(topicId);
  while (cur?.parent_id && byId.has(cur.parent_id)) cur = byId.get(cur.parent_id);
  return cur;
}

function SubjectsCard({ title, description }: { title: string; description: string }) {
  const subjects = useResource<SubjectsResponse>("placement/subjects");
  const items = (subjects.data?.items ?? []).filter((s) => s.is_active);
  return (
    <Card title={title}>
      <p className="mb-3 text-sm text-fg-secondary">{description}</p>
      {subjects.error ? (
        <ErrorState error={subjects.error} onRetry={subjects.reload} />
      ) : subjects.loading && !subjects.data ? (
        <Loading label="Loading subjects…" />
      ) : items.length === 0 ? (
        <EmptyState variant="inline" icon="book" title="No practice subjects published yet" description="Subjects appear here as soon as our trainers publish them." />
      ) : (
        <ul className="grid gap-2 sm:grid-cols-2" aria-label="Subjects">
          {items.map((s) => (
            <li key={s.id}>
              <Link href={`/app/practice/${enc(s.slug)}`} className="flex min-h-touch items-center justify-between rounded-lg border border-line p-3 text-sm hover:bg-surface-hover focus-visible:shadow-focus focus-visible:outline-none">
                <span className="font-medium text-fg">{s.name}</span>
                <span className="text-fg-muted">{s.question_count} questions</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

/**
 * Step 1 of Get started. Links straight to an open diagnostic test when ASM-01 lists one; when
 * none is published it offers a mock test (or practice) instead of a page that says "none".
 */
function DiagnosticStep() {
  const tests = useResource<MyTestsResponse>("me/tests");
  const items = tests.data?.items ?? [];
  const isOpen = (t: TestListItem) => t.status === "available" || t.status === "in_progress";
  const diag = items.find((t) => t.test_kind === "diagnostic" && isOpen(t));
  const anyOpen = items.some(isOpen);
  return (
    <Card title="1. Check where you stand">
      {tests.loading && !tests.data ? (
        <Loading label="Checking for a diagnostic test…" />
      ) : diag ? (
        <>
          <p className="text-sm text-fg-secondary">A short diagnostic test shows your strong and weak topics so practice can focus on what matters.</p>
          <div className="mt-3">
            <LinkButton href={`/app/tests/${enc(diag.test_id)}`}>Take the free diagnostic</LinkButton>
          </div>
        </>
      ) : (
        <>
          <p className="text-sm text-fg-secondary">
            {anyOpen
              ? "The diagnostic test isn't open yet. A mock test shows your strong and weak topics in the same way."
              : "The diagnostic test isn't open yet. Practise a subject to see your mastery by topic; the diagnostic will be listed here when it opens."}
          </p>
          <div className="mt-3">{anyOpen ? <LinkButton href="/app/tests">Take a mock test</LinkButton> : <LinkButton href="/app/practice">Start practising</LinkButton>}</div>
        </>
      )}
    </Card>
  );
}

/** STU-002 Get started. */
export function GetStarted() {
  return (
    <div className="space-y-6">
      <DiagnosticStep />
      <SubjectsCard title="2. Pick what to practise" description="Choose a subject to see its topics and your mastery." />
      <Card title="3. Learn with a course">
        <p className="text-sm text-fg-secondary">Video courses with notes, quizzes and a certificate.</p>
        <div className="mt-3 flex flex-wrap gap-2">
          <LinkButton href="/app/learning" variant="secondary">
            My learning
          </LinkButton>
          <LinkButton href="/app/courses" variant="ghost">
            Browse courses
          </LinkButton>
        </div>
      </Card>
      <p className="text-[0.8125rem] text-fg-muted">Saving a target role, companies and exam date isn&apos;t available yet. Your recommendations come from your practice and test results.</p>
    </div>
  );
}

/** STU-003 diagnostic launcher → TST-001/TST-002. */
export function DiagnosticLauncher() {
  return (
    <TestsCard
      title="Diagnostic tests"
      kinds={["diagnostic"]}
      empty={{
        title: "No diagnostic test is open right now",
        description: "When one is published for you, it appears here. Meanwhile, practise by subject to see your mastery by topic.",
        icon: "chart",
        action: (
          <LinkButton href="/app/practice" variant="secondary" size="sm">
            Go to practice
          </LinkButton>
        ),
      }}
    />
  );
}

/** STU-015 interview prep hub. */
export function InterviewPrep() {
  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-3">
        {[
          { href: "/app/mentoring", title: "Mock interviews", text: "Book a 1:1 session with a mentor and read their feedback." },
          { href: "/app/resume", title: "Résumé", text: "Build an ATS-friendly résumé and ask for a review." },
          { href: "/app/companies", title: "Company paths", text: "Practise for a specific company's pattern." },
        ].map((c) => (
          <Link
            key={c.href}
            href={c.href}
            className="group flex flex-col rounded-xl border border-line bg-surface p-4 shadow-xs hover:border-brand/40 hover:bg-surface-hover focus-visible:shadow-focus focus-visible:outline-none"
          >
            <span className="font-display font-bold text-fg-heading">{c.title}</span>
            <span className="mt-1 flex-1 text-sm text-fg-secondary">{c.text}</span>
            <span aria-hidden="true" className="mt-3 text-sm font-semibold text-fg-link group-hover:underline">
              Open →
            </span>
          </Link>
        ))}
      </div>
      <TestsCard title="Mock tests" kinds={["mock", "company_mock", "drive"]} empty={{ title: "No mock tests for you yet", description: "Mock and company tests assigned to you or published for free appear here.", icon: "calendar" }} />
    </div>
  );
}

/** STU-006 learning path: continue learning + recommendations (PLC-26). */
export function LearningPath() {
  const dash = useResource<DashboardDto>("me/dashboard");
  const recs = useResource<RecommendationsResponse>("me/recommendations");
  const subjects = useResource<SubjectsResponse>("placement/subjects");
  const tree = useMemo(() => subjects.data?.items ?? [], [subjects.data]);
  const topicName = (id: string) => {
    const byId = new Map<string, TaxonomyNode>();
    const walk = (ns: TaxonomyNode[]) => ns.forEach((n) => (byId.set(n.id, n), walk(n.children ?? [])));
    walk(tree);
    return byId.get(id)?.name;
  };
  const cont = dash.data?.continue_learning ?? [];
  return (
    <div className="space-y-6">
      <Card title="Continue learning">
        {dash.error ? (
          <ErrorState error={dash.error} onRetry={dash.reload} />
        ) : dash.loading && !dash.data ? (
          <Loading label="Loading…" />
        ) : cont.length === 0 ? (
          <EmptyState
            variant="inline"
            icon="book"
            title="No courses in progress"
            action={
              <LinkButton href="/app/courses" variant="secondary" size="sm">
                Browse courses
              </LinkButton>
            }
          />
        ) : (
          <ul className="divide-y divide-line text-sm">
            {cont.map((c) => (
              <li key={c.id} className="flex items-center justify-between gap-3 py-2">
                <span className="font-medium text-fg">{c.course_title}</span>
                <span className="flex items-center gap-3">
                  <span className="text-fg-muted">{Math.round(c.progress_pct)}%</span>
                  <LinkButton href={c.course_slug ? `/app/courses/${enc(c.course_slug)}` : "/app/learning"} variant="secondary" size="sm" aria-label={`Resume ${c.course_title ?? "course"}`}>
                    Resume
                  </LinkButton>
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Card title="Recommended next">
        {recs.error ? (
          <ErrorState error={recs.error} onRetry={recs.reload} />
        ) : recs.loading && !recs.data ? (
          <Loading label="Loading recommendations…" />
        ) : (recs.data?.items ?? []).length === 0 ? (
          <EmptyState
            variant="inline"
            icon="chart"
            title="No recommendations yet"
            description={
              recs.data && !recs.data.personalised ? (
                <>
                  Personalised suggestions are off.{" "}
                  <Link href="/app/settings/privacy" className="text-fg-link underline">
                    Turn on personalisation
                  </Link>{" "}
                  to get them.
                </>
              ) : (
                "Answer a few practice sets and take the diagnostic, and we'll suggest what to work on next."
              )
            }
          />
        ) : (
          <ul className="space-y-3">
            {recs.data!.items.map((r) => {
              const subject = r.target_type === "topic" ? subjectOf(r.target_id, tree) : undefined;
              return (
                <li key={r.id} className="rounded-lg border border-line p-3 text-sm">
                  <p className="font-medium text-fg">{(r.target_type === "topic" && topicName(r.target_id)) || "Practise a weak topic"}</p>
                  <p className="mt-0.5 text-fg-muted">Why: {r.why_recommended}</p>
                  <div className="mt-2">
                    <LinkButton href={subject ? `/app/practice/${enc(subject.slug)}` : "/app/practice"} variant="secondary" size="sm">
                      Practise
                    </LinkButton>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </Card>
    </div>
  );
}
