"use client";

import { Badge, Card, ErrorState, PageHeader, StatGrid, StatTile } from "@/components/ui";
import { seg, useApi } from "@/features/trainer/shared/use-api";
import { formatWhen, plural, TYPE_LABEL } from "../lib/labels";
import type { PresenterState } from "../lib/types";
import { Leaderboard, Loading, QuestionHeading, QuestionResults, StatusBadge } from "./parts";
import { useEngageScope } from "../lib/scope";

/** TRN-022 run results summary. */
export function RunResults({ runId }: { runId: string }) {
  const { base } = useEngageScope();
  const res = useApi<PresenterState>(`engage/runs/${seg(runId)}/results`);
  if (res.loading && !res.data) return <Loading label="Loading results" />;
  if (res.error || !res.data) return <ErrorState error={res.error} onRetry={() => void res.reload()} />;
  const s = res.data;
  const quiz = s.activity.activity_type === "quiz";
  return (
    <div className="space-y-6">
      <PageHeader
        breadcrumbs={[
          { label: "Engage", href: base },
          { label: s.activity.title, href: `${base}/${seg(s.activity.id)}` },
          { label: `Run ${s.run.run_no} results` },
        ]}
        title={s.activity.title}
        meta={
          <>
            <StatusBadge status={s.run.status} />
            {s.run.results_published ? <Badge tone="success">Results published</Badge> : <Badge>Results not published</Badge>}
          </>
        }
        description={`${TYPE_LABEL[s.activity.activity_type]} · Run ${s.run.run_no} · started ${formatWhen(s.run.opened_at)}`}
      />
      <StatGrid columns={3}>
        <StatTile label="Joined" value={s.joined} />
        <StatTile label="Voted" value={s.voted} />
        <StatTile label="Total votes" value={s.total_votes} />
      </StatGrid>
      {quiz ? (
        <Card title="Leaderboard">
          <Leaderboard rows={s.leaderboard} />
        </Card>
      ) : null}
      <ol className="space-y-4">
        {s.questions.map((q) => (
          <li key={q.id}>
            <Card>
              <QuestionHeading question={q} total={s.questions.length}>
                <Badge>{plural(q.answered, "response")}</Badge>
              </QuestionHeading>
              <QuestionResults question={q} showCorrect={quiz} texts={q.texts} winner={q.winner} />
            </Card>
          </li>
        ))}
      </ol>
    </div>
  );
}
