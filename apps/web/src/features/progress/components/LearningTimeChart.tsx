"use client";

import dynamic from "next/dynamic";
import { useState } from "react";
import { Button, Skeleton } from "@/components/ui";
import { formatDuration, formatIstShortDate } from "@/features/assessment/lib/format";
import type { LearningTimePoint } from "../lib/types";
import type { Row } from "./LearningTimeChartPlot";

// recharts is only needed once the chart is on screen: load it as a separate chunk
// (keeps it out of /app/progress first-load JS). The table view never loads it.
const LearningTimeChartPlot = dynamic(() => import("./LearningTimeChartPlot"), {
  ssr: false,
  loading: () => <Skeleton className="h-full w-full" />,
});

/**
 * Learning time (M5) over time — design-system §6: one series, one y-axis, line for ≥ 6 points
 * else bars, hairline grid, hover tooltip, no load animation, and a "View as table" path.
 */
export function LearningTimeChart({ points, title, caption }: { points: LearningTimePoint[]; title: string; caption: string }) {
  const [asTable, setAsTable] = useState(false);
  const rows: Row[] = points.map((p) => ({
    label: formatIstShortDate(p.date),
    seconds: p.m5_s,
    minutes: p.m5_s === null ? null : Math.round(p.m5_s / 6) / 10,
  }));
  const useLine = rows.length >= 6;
  const total = points.reduce((a, p) => a + (p.m5_s ?? 0), 0);

  return (
    <figure className="m-0">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <figcaption>
          <p className="font-display text-base font-semibold text-fg">{title}</p>
          <p className="text-xs text-fg-muted">{caption}</p>
        </figcaption>
        <Button size="sm" variant="secondary" aria-pressed={asTable} onClick={() => setAsTable((t) => !t)}>
          {asTable ? "View as chart" : "View as table"}
        </Button>
      </div>
      {asTable ? (
        <div className="mt-3 max-h-80 overflow-auto rounded-lg border border-line">
          <table className="w-full text-sm">
            <caption className="sr-only">{title}</caption>
            <thead className="bg-surface-subtle text-left text-xs uppercase text-fg-muted">
              <tr>
                <th scope="col" className="px-3 py-2">Date</th>
                <th scope="col" className="px-3 py-2 text-right">Learning time</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} className="border-t border-line">
                  <td className="px-3 py-2">{r.label}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{r.seconds === null ? "No data" : formatDuration(r.seconds)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="mt-3 h-64" role="img" aria-label={`${title}. Total ${formatDuration(total)} over ${rows.length} periods. Use "View as table" for exact values.`}>
          <LearningTimeChartPlot rows={rows} useLine={useLine} />
        </div>
      )}
    </figure>
  );
}
