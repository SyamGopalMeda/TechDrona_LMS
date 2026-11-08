"use client";

import Link from "next/link";
import { Card, EmptyState, ErrorState, Table } from "@/components/ui";
import type { Batch } from "@/features/batches/lib/types";
import { useTrainerBatches } from "../lib/batches";
import { seg } from "../shared/use-api";
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

/** TRN-001 trainer dashboard (PRD §8.2, wireframe §14). */
export function TrainerDashboard() {
  const { batches, error, loading, reload } = useTrainerBatches();

  if (error) return <ErrorState error={error} onRetry={() => void reload()} />;
  if (loading || !batches)
    return <LoadingBlock rows={4} label="Loading your batches" />;
  if (batches.length === 0)
    return (
      <EmptyState
        title="You haven't been assigned a batch yet"
        description="A Tech Drona admin assigns batches. Once they do, your students and tests appear here."
      />
    );

  const options = batches.map((b) => ({ value: b.id, label: b.name }));

  return (
    <div className="space-y-6">
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
            cell: (b) =>
              `${formatDate(b.starts_on)} – ${formatDate(b.ends_on)}`,
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
      <div className="grid gap-4 md:grid-cols-2">
        <Card
          title="Grading queue"
          actions={
            <Link
              className="text-sm text-fg-link underline"
              href="/trainer/grading"
            >
              Grade
            </Link>
          }
        >
          <GradingBacklog />
        </Card>
        <Card
          title="Integrity review"
          actions={
            <Link
              className="text-sm text-fg-link underline"
              href="/trainer/integrity"
            >
              Review
            </Link>
          }
        >
          <OpenFlags />
        </Card>
      </div>
      <section aria-labelledby="live-h" className="space-y-3">
        <h2
          id="live-h"
          className="font-display text-base font-semibold text-fg"
        >
          Live tests
        </h2>
        <LiveTests batches={batches} />
      </section>
      <section aria-labelledby="tests-h" className="space-y-3">
        <h2
          id="tests-h"
          className="font-display text-base font-semibold text-fg"
        >
          Tests
        </h2>
        <TestsList batches={options} basePath="/trainer" />
      </section>
    </div>
  );
}

/** TRN-005 tests page: same list, with the trainer's batches for assigning. */
export function TrainerTests() {
  const { batches, error, loading, reload } = useTrainerBatches();
  if (error) return <ErrorState error={error} onRetry={() => void reload()} />;
  if (loading || !batches) return <LoadingBlock rows={4} />;
  return (
    <TestsList
      batches={batches.map((b) => ({ value: b.id, label: b.name }))}
      basePath="/trainer"
    />
  );
}
