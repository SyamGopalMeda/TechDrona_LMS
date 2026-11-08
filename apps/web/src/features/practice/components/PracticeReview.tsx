"use client";

import Link from "next/link";
import { useMemo } from "react";
import { Badge, Button, EmptyState, ErrorState, PageHeader, Skeleton } from "@/components/ui";
import { formatIstDateTime } from "@/features/assessment/lib/format";
import { useLoader } from "@/features/assessment/lib/use-resource";
import { indexTopics, practiceApi } from "../lib/api";
import { useStartPractice } from "./PracticeHub";
import { isEntitlementError, PaywallCard } from "./shared";

/**
 * PRC-004 Review incorrect (PLC-24: latest 50 questions whose last answer was wrong, not paginated).
 * The endpoint returns ids only (no stem, no bookmarks), so rows show the topic and re-practise it.
 */
export function PracticeReview() {
  const res = useLoader("review", () => practiceApi.review());
  const subjects = useLoader("subjects", () => practiceApi.subjects());
  const topics = useMemo(() => indexTopics(subjects.data ?? []), [subjects.data]);
  const { start, starting, error } = useStartPractice();

  return (
    <div>
      <PageHeader
        eyebrow="Practice"
        title="Review"
        description="Questions you got wrong. Re-practise their topics to lift your mastery."
        actions={<Link className="text-sm text-fg-link underline" href="/app/practice">Back to practice</Link>}
      />
      {error ? <div className="mb-4">{isEntitlementError(error) ? <PaywallCard error={error} /> : <ErrorState error={error} />}</div> : null}
      {res.error ? (
        <ErrorState error={res.error} onRetry={() => void res.reload()} />
      ) : !res.data ? (
        <Skeleton className="h-40 w-full" />
      ) : res.data.length === 0 ? (
        <EmptyState title="Nothing to review" description="Questions you answer incorrectly appear here." action={<Link className="text-sm text-fg-link underline" href="/app/practice">Start practising</Link>} />
      ) : (
        <ul className="space-y-3">
          {res.data.map((q) => (
            <li key={q.question_version_id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line bg-surface p-4">
              <div className="flex flex-wrap items-center gap-2 text-sm text-fg-muted">
                <Badge tone="danger">✕ Incorrect</Badge>
                <span className="font-medium text-fg">{topics.get(q.topic_id)?.name ?? "Topic"}</span>
                <span>
                  · {q.attempts} attempt{q.attempts === 1 ? "" : "s"} · {formatIstDateTime(q.last_answered_at)}
                </span>
              </div>
              <Button size="sm" variant="secondary" loading={starting} onClick={() => void start({ mode: "topic_set", topic_id: q.topic_id })}>
                Practise topic
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
