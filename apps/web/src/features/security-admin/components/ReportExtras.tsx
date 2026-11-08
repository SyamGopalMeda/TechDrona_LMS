"use client";

import type { ReactNode } from "react";
import { Card, Table, type Column } from "@/components/ui";
import { JsonBlock, KeyValueList } from "@/features/admin/components/console-ui";
import { cellText, humanize } from "@/features/admin/lib/console";
import { REPORT_ENVELOPE_KEYS } from "../lib/catalogue";
import type { ReportResult } from "../lib/types";

type Plain = Record<string, unknown>;

const isObj = (v: unknown): v is Plain => typeof v === "object" && v !== null && !Array.isArray(v);
const isScalar = (v: unknown) => v === null || v === undefined || typeof v !== "object";

/** Rows of objects → a table whose columns are the union of keys. */
function ObjectTable({ title, rows }: { title: string; rows: Plain[] }) {
  const keys = Array.from(new Set(rows.flatMap((r) => Object.keys(r)).filter((k) => k !== "suppressed")));
  const cols: Column<Plain>[] = keys.map((k) => ({
    key: k,
    header: humanize(k),
    cell: (r) => (r.suppressed === true && (r[k] === null || r[k] === undefined) ? <span title="Fewer than the k-minimum subjects">&lt;k suppressed</span> : cellText(r[k])),
  }));
  return <Table caption={title} columns={cols} rows={rows} rowKey={(r) => JSON.stringify(r)} empty={{ title: "None" }} />;
}

/** One secondary value rendered by shape: scalar map, list of objects, list of scalars, nested map. */
function ExtraValue({ name, value, depth }: { name: string; value: unknown; depth: number }) {
  const title = humanize(name);
  if (Array.isArray(value)) {
    if (value.length === 0) return <p className="text-sm text-fg-muted">None</p>;
    if (value.every(isObj)) return <ObjectTable title={title} rows={value} />;
    return <p className="text-sm text-fg">{cellText(value)}</p>;
  }
  if (isObj(value)) {
    const entries = Object.entries(value);
    if (entries.length === 0) return <p className="text-sm text-fg-muted">None</p>;
    if (entries.every(([, v]) => isScalar(v))) return <KeyValueList items={entries.map(([k, v]) => ({ label: humanize(k), value: v === null ? "—" : cellText(v) }))} />;
    if (depth >= 2) return <JsonBlock label={title} value={value} />;
    return (
      <div className="space-y-3">
        {entries.map(([k, v]) => (
          <section key={k} aria-label={humanize(k)}>
            <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-fg-muted">{humanize(k)}</h4>
            <ExtraValue name={k} value={v} depth={depth + 1} />
          </section>
        ))}
      </div>
    );
  }
  return <p className="text-sm text-fg">{cellText(value)}</p>;
}

/** H8 alert codes (reports.py `_h8`) in words. */
export const H8_ALERT_LABELS: Record<string, string> = {
  l3_fp_rate_above_10pct: "L3 false-positive rate above 10 %",
  rule_fp_cases_per_week_above_3: "More than 3 false-positive cases for one rule in a week",
};

/** Secondary keys with a dedicated label (ADM-07); the rest are humanized. */
const EXTRA_LABELS: Record<string, string> = {
  granularity: "Granularity",
  scope: "Scope",
  students_at_session_cap: "Students at the session cap",
  student_session_cap: "Student session cap",
  student_sessions_per_user: "Active student sessions per user",
  alerts: "Alerts",
  k_min: "Minimum group size (k)",
};
const label = (k: string) => EXTRA_LABELS[k] ?? humanize(k);
const SUPPRESSED = <span title="Fewer than the k-minimum subjects">&lt;k suppressed</span>;

/** H11 `scope`: "platform" (single company). */
function scopeText(v: unknown): ReactNode {
  if (v === "platform") return "Whole platform";
  return cellText(v);
}

function scalarValue(k: string, v: unknown): ReactNode {
  if (k === "students_at_session_cap" && v === null) return SUPPRESSED;
  if (k === "granularity" && typeof v === "string") return humanize(v);
  return v === null ? "—" : cellText(v);
}

/** H10 `student_sessions_per_user`: {"<sessions>": users | null (suppressed)}. */
function SessionsPerUser({ value }: { value: Plain }) {
  const rows = Object.entries(value).map(([n, users]) => ({ n, users }));
  const cols: Column<{ n: string; users: unknown }>[] = [
    { key: "n", header: "Active sessions", cell: (r) => r.n },
    { key: "users", header: "Students", align: "right", cell: (r) => (r.users === null ? SUPPRESSED : cellText(r.users)) },
  ];
  return <Table caption={label("student_sessions_per_user")} columns={cols} rows={rows} rowKey={(r) => r.n} empty={{ title: "No active student sessions" }} />;
}

/** H8 `alerts`: one row per raised alert, with the alert code in words. */
function Alerts({ rows }: { rows: Plain[] }) {
  if (rows.length === 0) return <p className="text-sm text-fg-muted">No alerts raised for this period.</p>;
  return <ObjectTable title={label("alerts")} rows={rows.map((r) => ({ ...r, alert: typeof r.alert === "string" ? (H8_ALERT_LABELS[r.alert] ?? humanize(r.alert)) : r.alert }))} />;
}

/**
 * ADM-07: everything a Section H runner returns outside `rows` (ENG fields, H1
 * `highest_scores_without_case`, H6 `counts`, H8 `circuit_breakers` / labelled `alerts`, H4
 * `flagged_sources`, H10 sessions per user and students at the cap, H11 granularity and scope,
 * notes), so no data is hidden.
 */
export function ReportExtras({ result }: { result: ReportResult }) {
  const extras = Object.entries(result).filter(([k]) => !REPORT_ENVELOPE_KEYS.has(k));
  if (extras.length === 0) return null;
  const isDetail = ([k, v]: [string, unknown]) => isScalar(v) || k === "scope";
  const scalars = extras.filter(isDetail);
  const structured = extras.filter((e) => !isDetail(e));
  return (
    <div className="mt-6 space-y-4">
      {scalars.length ? (
        <Card title="Report details">
          <KeyValueList items={scalars.map(([k, v]) => ({ label: label(k), value: k === "scope" ? scopeText(v) : scalarValue(k, v) }))} />
        </Card>
      ) : null}
      {structured.map(([k, v]) => (
        <Card key={k} title={label(k)}>
          {k === "student_sessions_per_user" && isObj(v) ? <SessionsPerUser value={v} /> : k === "alerts" && Array.isArray(v) && v.every(isObj) ? <Alerts rows={v} /> : <ExtraValue name={k} value={v} depth={0} />}
        </Card>
      ))}
    </div>
  );
}
