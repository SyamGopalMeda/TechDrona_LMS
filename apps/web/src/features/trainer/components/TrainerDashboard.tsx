"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { Card, DashboardHero, EmptyState, ErrorState, PageHeader, QuickActions, Reveal, SectionHeader, StatGrid, StatTile, Table, ViewAllLink, type QuickAction } from "@/components/ui";
import type { Page } from "@/lib/api/client";
import type { AssignmentSummary } from "../lib/types";
import type { Batch } from "@/features/batches/lib/types";
import { useTeachingQuery, useTrainerBatches } from "../lib/batches";
import { seg, useApi } from "../shared/use-api";
import { LoadingBlock, StatusBadge, formatDate } from "../shared/ui";
import { GradingBacklog, LiveTests } from "./Insights";
import { useOpenFlagCount } from "./Integrity";
import { TestsList } from "./TestsList";

/** Advisory flags tile (ASM-19, status=open). Hidden counts when the trainer lacks integrity.flag.read. */
function OpenFlags() {
  const { count, more, error } = useOpenFlagCount();
  if (error)
    return (
      <p className="text-sm text-fg-secondary">
        Advisory integrity flags couldn&apos;t be loaded.
      </p>
    );
  if (count === null)
    return <p className="text-sm text-fg-muted">Loading flags…</p>;
  if (count === 0)
    return (
      <p className="text-sm text-fg-secondary">No attempts need review.</p>
    );
  return (
    <p className="text-sm text-fg-secondary">
      <span className="font-display text-2xl font-bold tabular-nums text-fg">
        {more ? `${count}+` : count}
      </span>{" "}
      attempt{count === 1 && !more ? "" : "s"} with advisory signals to review.
    </p>
  );
}

/** "1 Nov 2026 – 30 Apr 2027"; one side when only one is set; "No dates set" when neither is. */
export function batchDates(b: Pick<Batch, "starts_on" | "ends_on">): string {
  if (!b.starts_on && !b.ends_on) return "No dates set";
  if (!b.ends_on) return `From ${formatDate(b.starts_on)}`;
  if (!b.starts_on) return `Until ${formatDate(b.ends_on)}`;
  return `${formatDate(b.starts_on)} – ${formatDate(b.ends_on)}`;
}

const HERO = { title: "Trainer dashboard", description: "Your batches, what's waiting to be graded or reviewed, and your tests." };

/** The trainer's most frequent jobs, one click from the dashboard. */
function trainerActions(firstBatchId: string | null): QuickAction[] {
  return [
    { href: "/trainer/grading", label: "Grade submissions", hint: "Mark work and give feedback", icon: "check" },
    { href: "/trainer/tests", label: "Create or assign a test", hint: "Schedule tests for your batches", icon: "hourglass" },
    { href: "/trainer/courses", label: "Course materials", hint: "Lessons, files and videos", icon: "book" },
    { href: "/trainer/engage/new", label: "Start a live activity", hint: "Polls and quizzes in class", icon: "megaphone" },
    firstBatchId
      ? { href: `/trainer/batches/${seg(firstBatchId)}`, label: "Message students", hint: "Send an announcement to a batch", icon: "chat" }
      : { href: "/trainer/integrity", label: "Integrity flags", hint: "Review flagged attempts", icon: "shield" },
    { href: "/trainer/paths", label: "Learning paths", hint: "Assign a guided path", icon: "map" },
  ];
}

/** Summary tiles: batches, submissions waiting, advisory flags (each links to its page). */
function TrainerStats({ batches }: { batches: Batch[] }) {
  const work = useApi<Page<AssignmentSummary>>("assignments", { scope: "mine", limit: 100, ...useTeachingQuery() });
  const flags = useOpenFlagCount();
  const waiting = work.data ? work.data.data.reduce((n, a) => n + a.pending_count, 0) : null;
  const active = batches.filter((b) => b.status === "active").length;
  return (
    <StatGrid columns={3}>
      <StatTile icon="layers" tone="highlight" label="My batches" value={batches.length} hint={`${active} active`} href={batches[0] ? `/trainer/batches/${seg(batches[0].id)}` : undefined} />
      <StatTile icon="check" label="Waiting to grade" value={waiting === null ? "—" : `${waiting}${work.data?.page.has_more ? "+" : ""}`} hint="Submitted work" href="/trainer/grading" tone={waiting ? "warning" : "brand"} />
      <StatTile icon="shield" label="Integrity flags" value={flags.count === null ? "—" : `${flags.count}${flags.more ? "+" : ""}`} hint="Attempts to review" href="/trainer/integrity" tone={flags.count ? "warning" : "brand"} />
    </StatGrid>
  );
}

/** TRN-001 trainer dashboard (PRD §8.2, wireframe §14). */
export function TrainerDashboard() {
  const { batches, error, loading, reload } = useTrainerBatches();

  if (error)
    return (
      <>
        <DashboardHero {...HERO} />
        <ErrorState error={error} onRetry={() => void reload()} />
      </>
    );
  if (loading || !batches)
    return (
      <>
        <DashboardHero {...HERO} />
        <LoadingBlock rows={4} label="Loading your batches" />
      </>
    );
  if (batches.length === 0)
    return (
      <>
        <DashboardHero {...HERO} />
        <EmptyState
          title="You haven't been assigned a batch yet"
          description="A Tech Drona admin assigns batches. Once they do, your students and tests appear here."
        />
      </>
    );

  const options = batches.map((b) => ({ value: b.id, label: b.name }));

  return (
    <div className="space-y-6">
      <DashboardHero {...HERO}>
        <TrainerStats batches={batches} />
      </DashboardHero>
      <Reveal>
        <Card title="Quick actions" icon="bolt">
          <QuickActions items={trainerActions(batches[0]?.id ?? null)} columns={3} />
        </Card>
      </Reveal>
      <Table
        caption="My batches"
        showCaption
        columns={[
          {
            key: "n",
            header: "Batch",
            cell: (b: Batch) => (
              <Link
                className="text-fg-link underline"
                href={`/trainer/batches/${seg(b.id)}`}
              >
                {b.name}
              </Link>
            ),
          },
          { key: "c", header: "Code", cell: (b) => b.code },
          {
            key: "d",
            header: "Dates",
            priority: "secondary",
            cell: (b) => batchDates(b),
          },
          {
            key: "s",
            header: "Status",
            cell: (b) => <StatusBadge status={b.status} />,
          },
        ]}
        rows={batches}
        rowKey={(b) => b.id}
      />
      <Reveal stagger className="grid gap-4 md:grid-cols-2 [&>*]:min-w-0">
        <Card title="Grading queue" icon="check" actions={<ViewAllLink href="/trainer/grading">Open grading</ViewAllLink>}>
          <GradingBacklog />
        </Card>
        <Card title="Integrity review" icon="shield" actions={<ViewAllLink href="/trainer/integrity">Review flags</ViewAllLink>}>
          <OpenFlags />
        </Card>
      </Reveal>
      <Reveal as="section" aria-labelledby="live-h">
        <SectionHeader id="live-h" kicker="Right now" title="Live tests" description="Tests open for your batches right now." />
        <LiveTests batches={batches} />
      </Reveal>
      <section aria-labelledby="tests-h">
        <TestsList
          batches={options}
          basePath="/trainer"
          header={(create) => <SectionHeader id="tests-h" title="Tests" actions={create} />}
        />
      </section>
    </div>
  );
}

/** TRN-005 tests page: same list, with the trainer's batches for assigning; "New test" in the header. */
export function TrainerTests() {
  const { batches, error, loading, reload } = useTrainerBatches();
  const head = (actions?: ReactNode) => (
    <PageHeader
      title="Tests"
      eyebrow="TRN-005"
      description="Assign tests to your batches, grant overrides and follow attempts."
      actions={actions}
    />
  );
  if (error)
    return (
      <>
        {head()}
        <ErrorState error={error} onRetry={() => void reload()} />
      </>
    );
  if (loading || !batches)
    return (
      <>
        {head()}
        <LoadingBlock rows={4} />
      </>
    );
  return (
    <TestsList
      batches={batches.map((b) => ({ value: b.id, label: b.name }))}
      basePath="/trainer"
      header={(create) => head(create)}
    />
  );
}
