"use client";

import { Button, Card, EmptyState, ErrorState, LinkButton, PageHeader, Skeleton } from "@/components/ui";
import { formatPercent } from "@/features/assessment/lib/format";
import { useLoader } from "@/features/assessment/lib/use-resource";
import { practiceApi } from "../lib/api";
import { TopicPicker, useStartPractice } from "./PracticeHub";
import { isEntitlementError, MasteryChip, PaywallCard } from "./shared";

/** PRC-002 Topics & mastery for one subject (PLC-01 + PLC-25). */
export function SubjectTopics({ subject: subjectKey }: { subject: string }) {
  const subjects = useLoader("subjects", () => practiceApi.subjects());
  const mastery = useLoader("mastery", () => practiceApi.mastery());
  const { start, starting, error } = useStartPractice();

  if (subjects.error) return <ErrorState error={subjects.error} onRetry={() => void subjects.reload()} />;
  if (!subjects.data) return <Skeleton className="h-64 w-full" />;
  const subject = subjects.data.find((s) => s.slug === subjectKey || s.id === subjectKey);
  if (!subject)
    return (
      <EmptyState
        icon="search"
        title="Subject not found"
        action={
          <LinkButton href="/app/practice" variant="secondary" size="sm">
            Back to practice
          </LinkButton>
        }
      />
    );

  const byTopic = new Map((mastery.data?.topics ?? []).map((t) => [t.topic_id, t]));

  return (
    <div>
      <PageHeader breadcrumbs={[{ label: "Practice", href: "/app/practice" }, { label: subject.name }]} title={subject.name} description="Pick a topic to practise. Your mastery updates as you answer." />
      <Card title="Start a set" className="mb-6">
        <TopicPicker subjects={subjects.data} initialSubjectId={subject.id} />
      </Card>
      {error ? <div className="mb-4">{isEntitlementError(error) ? <PaywallCard error={error} /> : <ErrorState error={error} />}</div> : null}
      <Card title="Topics and mastery">
        {mastery.error ? <p className="mb-2 text-sm text-fg-muted">Mastery couldn&apos;t be loaded right now; topics are still available.</p> : null}
        <ul className="divide-y divide-line">
          {subject.children.map((t) => {
            const m = byTopic.get(t.id);
            return (
              <li key={t.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                <div>
                  <p className="font-medium text-fg">{t.name}</p>
                  <p className="mt-0.5 flex items-center gap-2 text-sm text-fg-muted">
                    <MasteryChip band={m?.band ?? "insufficient_data"} />
                    {m ? `${formatPercent(m.weighted_accuracy * 100)} weighted accuracy · ${m.answered} answers` : null}
                  </p>
                </div>
                <Button size="sm" variant="secondary" loading={starting} onClick={() => void start({ mode: "topic_set", topic_id: t.id })}>
                  Practise {t.name}
                </Button>
              </li>
            );
          })}
        </ul>
      </Card>
    </div>
  );
}
