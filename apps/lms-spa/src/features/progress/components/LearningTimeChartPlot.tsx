"use client";

import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { formatDuration } from "@/features/assessment/lib/format";

/** One chart row; shared with the lazy-loading shell in LearningTimeChart. */
export interface Row {
  label: string;
  minutes: number | null;
  seconds: number | null;
}

const AXIS = { stroke: "var(--td-chart-axis)", fontSize: 12, fill: "var(--td-chart-label)" };

function ChartTooltip({ active, payload }: { active?: boolean; payload?: { payload: Row }[] }) {
  const row = active ? payload?.[0]?.payload : undefined;
  if (!row) return null;
  return (
    <div className="rounded-md border border-line bg-surface-raised px-3 py-2 text-xs text-fg shadow-md">
      <p className="font-semibold">{row.label}</p>
      <p>Learning time: {row.seconds === null ? "No data" : formatDuration(row.seconds)}</p>
    </div>
  );
}

/**
 * Recharts plot for LearningTimeChart. Kept in its own module so recharts (~120 kB) is a
 * separate chunk loaded with next/dynamic after the page renders.
 */
export default function LearningTimeChartPlot({ rows, useLine }: { rows: Row[]; useLine: boolean }) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      {useLine ? (
        <LineChart data={rows} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="var(--td-chart-grid)" strokeWidth={1} vertical={false} />
          <XAxis dataKey="label" tick={AXIS} tickLine={false} axisLine={{ stroke: "var(--td-chart-axis)" }} minTickGap={16} />
          <YAxis tick={AXIS} tickLine={false} axisLine={false} width={44} unit=" m" allowDecimals={false} />
          <Tooltip content={<ChartTooltip />} cursor={{ stroke: "var(--td-chart-axis)", strokeWidth: 1 }} />
          <Line
            type="monotone"
            dataKey="minutes"
            name="Learning time"
            stroke="var(--td-chart-1)"
            strokeWidth={2}
            dot={{ r: 4, strokeWidth: 2, stroke: "var(--td-surface)", fill: "var(--td-chart-1)" }}
            activeDot={{ r: 5 }}
            connectNulls={false}
            isAnimationActive={false}
          />
        </LineChart>
      ) : (
        <BarChart data={rows} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="var(--td-chart-grid)" strokeWidth={1} vertical={false} />
          <XAxis dataKey="label" tick={AXIS} tickLine={false} axisLine={{ stroke: "var(--td-chart-axis)" }} />
          <YAxis tick={AXIS} tickLine={false} axisLine={false} width={44} unit=" m" allowDecimals={false} />
          <Tooltip content={<ChartTooltip />} cursor={{ fill: "var(--td-surface-hover)" }} />
          <Bar dataKey="minutes" name="Learning time" fill="var(--td-chart-1)" radius={[4, 4, 0, 0]} maxBarSize={32} isAnimationActive={false} />
        </BarChart>
      )}
    </ResponsiveContainer>
  );
}
