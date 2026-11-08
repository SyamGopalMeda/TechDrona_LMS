"use client";

import Link from "next/link";
import { Badge, Card, ErrorState, StatTile } from "@/components/ui";
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
      <div>
        <Link href={`${base}/${seg(s.activity.id)}`} className="text-sm text-fg-link hover:text-fg-link-hover">
          ← Control room
        </Link>
        <h1 className="mt-1 break-words font-display text-2xl font-bold text-fg">{s.activity.title}</h1>
        <p className="mt-1 flex flex-wrap items-center gap-2 text-sm text-fg-muted">
          {TYPE_LABEL[s.activity.activity_type]} · Run {s.run.run_no} · started {formatWhen(s.run.opened_at)}
          <StatusBadge status={s.run.status} />
          {s.run.results_published ? <Badge tone="success">Published</Badge> : <Badge>Not published</Badge>}
        </p>
      </div>
      <div className="grid grid-cols-3 gap-3">
        <StatTile label="Joined" value={s.joined} />
        <StatTile label="Voted" value={s.voted} />
        <StatTile label="Total votes" value={s.total_votes} />
      </div>
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
