"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { Card, ErrorState, FormField, PageHeader, Select, Skeleton, StatTile, Table, type Column } from "@/components/ui";
import { formatDuration, formatPercent } from "@/features/assessment/lib/format";
import { useLoader } from "@/features/assessment/lib/use-resource";
import { indexTopics, practiceApi } from "@/features/practice/lib/api";
import { MasteryChip } from "@/features/practice/components/shared";
import type { MasteryTopic } from "@/features/practice/lib/types";
import { BROWSER_CAVEAT, periodTotals, progressApi, rangeForDays, TIME_METRICS } from "../lib/metrics";
import type { AnalyticsSummary, TimeMetricKey } from "../lib/types";
import { LearningTimeChart } from "./LearningTimeChart";

const PERIODS = [
  { value: "7", label: "Last 7 days" },
  { value: "28", label: "Last 4 weeks" },
  { value: "56", label: "Last 8 weeks" },
];

function MeasurementNote({ version }: { version: string }) {
  return (
    <details className="mt-3 rounded-md border border-line bg-surface-subtle p-3 text-sm">
      <summary className="cursor-pointer font-medium text-fg-link">How we measure time</summary>
      <p className="mt-2 text-fg-secondary">{BROWSER_CAVEAT}</p>
      <ul className="mt-2 space-y-2">
        {TIME_METRICS.map((m) => (
          <li key={m.key}>
            <span className="font-medium text-fg">{m.label}</span> — {m.description} <span className="text-fg-muted">{m.isNot}</span>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-fg-muted">
        Measurement version {version}. Numbers are only comparable within the same version, and not with other platforms.{" "}
        <Link className="underline" href="/help/how-we-measure-time">
          Read more
        </Link>
      </p>
    </details>
  );
}

function TimeMetricsTable({ totals, periodLabel }: { totals: Record<TimeMetricKey, number | null>; periodLabel: string }) {
  return (
    <Card title={`Time, ${periodLabel.toLowerCase()}`}>
      <p className="mb-3 rounded-md border-l-4 border-info-border bg-info-subtle p-2 text-xs text-info-fg">
        <strong>Browser-measured estimate.</strong> Not proof of attention; offline time may be missing.
      </p>
      <table className="w-full text-sm">
        <caption className="sr-only">Five time measures for the {periodLabel.toLowerCase()}</caption>
        <thead className="text-left text-xs uppercase text-fg-muted">
          <tr>
            <th scope="col" className="py-1">Measure</th>
            <th scope="col" className="py-1 text-right">Time</th>
          </tr>
        </thead>
        <tbody>
          {TIME_METRICS.map((m) => {
            const v = totals[m.key];
            return (
              <tr key={m.key} className="border-t border-line align-top">
                <th scope="row" className="py-2 pr-2 text-left font-normal">
                  <span className={m.key === "m5" ? "font-semibold text-fg" : "text-fg"}>{m.label}</span>
                  <span className="block text-xs text-fg-muted">{m.isNot}</span>
                </th>
                <td className="py-2 text-right tabular-nums">{v === null ? "Not reported yet" : formatDuration(v)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </Card>
  );
}

type TopicRow = AnalyticsSummary["accuracy_by_topic"][number];

/** STU-011-style self analytics for /app/progress: skill mastery + time-spent views (ANL-04/05, PLC-25). */
export function ProgressDashboard() {
  const [period, setPeriod] = useState("28");
  const summary = useLoader("summary", () => progressApi.summary());
  const mastery = useLoader("mastery", () => practiceApi.mastery());
  const days = Number(period);
  const { from, to } = rangeForDays(days);
  const grain = days > 28 ? "week" : "day";
  const series = useLoader(`lt:${from}:${to}:${grain}`, () => progressApi.learningTime(from, to, grain));
  const subjects = useLoader("subjects", () => practiceApi.subjects());
  const topics = useMemo(() => indexTopics(subjects.data ?? []), [subjects.data]);
  const periodLabel = PERIODS.find((p) => p.value === period)?.label ?? "";
  const totals = periodTotals(series.data?.points);

  const s = summary.data;
  const codingRate = s && s.coding.submissions > 0 ? (s.coding.accepted / s.coding.submissions) * 100 : null;
  const topicCols: Column<TopicRow>[] = [
    { key: "topic", header: "Topic", cell: (r) => topics.get(r.topic_id)?.name ?? "Topic" },
    { key: "n", header: "Answered", align: "right", cell: (r) => r.answered },
    { key: "acc", header: "Accuracy", align: "right", cell: (r) => formatPercent(r.accuracy === null ? null : r.accuracy * 100) },
    { key: "time", header: "Learning time", align: "right", cell: (r) => formatDuration(r.learning_s) },
  ];
  const masteryCols: Column<MasteryTopic>[] = [
    { key: "topic", header: "Topic", cell: (r) => r.name ?? topics.get(r.topic_id)?.name ?? "Topic" },
    { key: "band", header: "Mastery", cell: (r) => <MasteryChip band={r.band} /> },
    { key: "acc", header: "Weighted accuracy", align: "right", cell: (r) => formatPercent(r.weighted_accuracy * 100) },
    { key: "n", header: "Answers (n)", align: "right", cell: (r) => r.answered },
  ];

  return (
    <div>
      <PageHeader
        title="Progress"
        description="Your skills and the time you've spent learning."
        actions={
          <FormField label="Period">
            {(p) => <Select {...p} value={period} onChange={(e) => setPeriod(e.target.value)} options={PERIODS} />}
          </FormField>
        }
      />

      {summary.error ? (
        <ErrorState error={summary.error} onRetry={() => void summary.reload()} />
      ) : !s ? (
        <div aria-busy="true" className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-24 w-full" />
          ))}
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <StatTile label="Learning time today" value={formatDuration(s.learning_time.today_s)} hint="Browser-measured estimate" />
            <StatTile label="Learning time this week" value={formatDuration(s.learning_time.this_week_s)} hint="Browser-measured estimate" />
            {s.active_days_streak !== undefined && s.active_days_streak !== null ? (
              <StatTile label="Active days streak" value={s.active_days_streak} hint="Days with 10+ min learning time" />
            ) : (
              <StatTile label="Active days (last 30)" value={s.active_days_last_30} hint="Days with 10+ min learning time" />
            )}
            <StatTile
              label="Coding acceptance"
              value={codingRate !== null ? formatPercent(codingRate) : null}
              hint={`${s.coding.accepted} of ${s.coding.submissions} submissions accepted`}
            />
          </div>
          <p className="mt-2 text-xs text-fg-muted">Measurement {s.how_we_measure.measurement_version}</p>
        </>
      )}

      <div className="mt-6 grid gap-6 lg:grid-cols-[3fr_2fr]">
        <Card>
          {series.error ? (
            <ErrorState error={series.error} onRetry={() => void series.reload()} />
          ) : !series.data ? (
            <Skeleton className="h-72 w-full" />
          ) : (
            <>
              <LearningTimeChart
                points={series.data.points.map((b) => ({ date: b.period_start, m5_s: b.learning_s }))}
                title={`How much learning time did you log ${grain === "week" ? "per week" : "per day"}?`}
                caption={`Learning time (M5), minutes, ${periodLabel.toLowerCase()} · browser-measured estimate · ${series.data.measurement_version}`}
              />
            </>
          )}
          <MeasurementNote version={s?.how_we_measure.measurement_version ?? series.data?.measurement_version ?? "tm-1.0"} />
        </Card>
        {series.data ? <TimeMetricsTable totals={totals} periodLabel={periodLabel} /> : <Skeleton className="h-72 w-full" />}
      </div>

      <section className="mt-8" aria-labelledby="mastery-h">
        <h2 id="mastery-h" className="mb-3 font-display text-lg font-semibold">
          Topic mastery
        </h2>
        <Table
          caption="Topic mastery bands"
          columns={masteryCols}
          rows={mastery.data?.topics}
          rowKey={(r) => r.topic_id}
          loading={mastery.loading}
          error={mastery.error}
          onRetry={() => void mastery.reload()}
          empty={{ title: "No mastery data yet", description: "Practise a topic to see your band.", action: <Link className="text-sm text-fg-link underline" href="/app/practice">Start practising</Link> }}
        />
        <p className="mt-2 text-xs text-fg-muted">
          Bands: beginner (below 40%), developing (40–60%), proficient (60–80%), mastered (80%+); fewer than 5 answers is insufficient data.{" "}
          {mastery.data?.method_note ?? ""} Time is not an input to mastery.
        </p>
      </section>

      {s?.accuracy_by_topic.length ? (
        <section className="mt-8" aria-labelledby="acc-h">
          <h2 id="acc-h" className="mb-3 font-display text-lg font-semibold">
            Accuracy and learning time per topic
          </h2>
          <Table caption="Accuracy and learning time by topic" columns={topicCols} rows={s.accuracy_by_topic} rowKey={(r) => r.topic_id} />
        </section>
      ) : null}
    </div>
  );
}
