"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { Badge, Button, Card, EmptyState, ErrorState, FormField, Input, PageHeader, Select, Skeleton, Table, type Column } from "@/components/ui";
import { api } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { useResource } from "@/features/account/lib/use-resource";
import { ApprovalPendingNotice, InlineProblem, SECURITY_REASON_CODES, StateBadge, TextArea, textLink } from "@/features/admin/components/console-ui";
import { cellText, cleanQuery, formatDateTime, humanize, useVersioned } from "@/features/admin/lib/console";
import { defaultReportDays, REPORT_FILTER_DEFS, REPORT_FILTERS, REQUIRED_REPORT_FILTERS, reportByKey, SECTION_H_REPORTS, type ReportFilterDef } from "../lib/catalogue";
import type { ExportResponse, ReportCatalogueEntry, ReportResult } from "../lib/types";
import { MyExports, readTrackedExports, trackExport, type TrackedExport } from "./MyExports";
import { ReportExtras } from "./ReportExtras";

/** Report catalogue (SEC-30) merged with the static H1–H12 + ENG list. */
export function ReportsIndex() {
  // verified: api_engine.py report_catalogue → {data: [{report_key, id, title, per_user, accessible, export_approval}]}
  const res = useResource<{ data: ReportCatalogueEntry[] }>("security/reports");
  const byKey = new Map((res.data?.data ?? []).map((r) => [r.report_key, r]));
  // Show only the reports the api marks accessible for this caller when it answered; else the static list.
  const items = res.data ? SECTION_H_REPORTS.filter((r) => byKey.get(r.key)?.accessible) : SECTION_H_REPORTS;
  return (
    <div>
      <PageHeader eyebrow="SEC-001 · Section H" title="Security reports" description="H1–H12 and engine health. Exports need step-up; exports with per-user rows also need a second security reviewer." />
      {res.error ? <ErrorState error={res.error} onRetry={() => void res.reload()} /> : null}
      <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" aria-busy={res.loading || undefined}>
        {items.map((r) => {
          const api = byKey.get(r.key);
          return (
            <li key={r.key} className="rounded-xl border border-line bg-surface p-4">
              <p className="text-xs font-semibold uppercase tracking-wide text-fg-muted">{r.code}</p>
              <Link href={`/security/reports/${r.key}`} className={`${textLink} font-display text-base`}>
                {api?.title ?? r.title}
              </Link>
              <p className="mt-2 flex flex-wrap gap-1">
                {(api?.per_user ?? r.perUser) ? <Badge tone="info">Per-user rows</Badge> : <Badge>Aggregate</Badge>}
              </p>
            </li>
          );
        })}
      </ul>
      {res.data && items.length === 0 ? <EmptyState title="No reports available for your role" /> : null}
      <MyExportsFromSession />
    </div>
  );
}

/** "My exports" on the reports index, including jobs requested earlier in this browser session. */
function MyExportsFromSession() {
  const [tracked] = useState<TrackedExport[]>(() => readTrackedExports());
  return <MyExports tracked={tracked} />;
}

const IST_DAY = (d: Date) => new Date(d.getTime() + 5.5 * 3_600_000).toISOString().slice(0, 10);

/** Initial filter values: a dated report starts `defaultReportDays` back (H3 ≤ 14 days), granularity day. */
function initialFilters(reportKey: string, names: string[]): Record<string, string> {
  const out: Record<string, string> = {};
  if (names.includes("from")) out.from = IST_DAY(new Date(Date.now() - (defaultReportDays(reportKey) - 1) * 86_400_000));
  if (names.includes("granularity")) out.granularity = "day";
  return out;
}

function FilterInput({ def, value, required, error, onChange }: { def: ReportFilterDef; value: string; required: boolean; error?: string; onChange: (v: string) => void }) {
  return (
    <FormField label={def.label} required={required} hint={def.hint} error={error}>
      {(f) =>
        def.kind === "select" ? (
          <Select {...f} value={value} onChange={(e) => onChange(e.target.value)} options={def.options ?? []} />
        ) : (
          <Input
            {...f}
            type={def.kind === "date" ? "date" : def.kind === "int" ? "number" : "text"}
            inputMode={def.kind === "int" ? "numeric" : undefined}
            spellCheck={def.kind === "uuid" ? false : undefined}
            className={def.kind === "uuid" ? "font-mono" : undefined}
            value={value}
            onChange={(e) => onChange(e.target.value)}
          />
        )
      }
    </FormField>
  );
}

/** Field messages from a 422 `validation_failed` problem, keyed by filter name. */
export function filterErrors(error: unknown): Record<string, string> {
  const out: Record<string, string> = {};
  if (!(error instanceof ApiError) || error.status !== 422) return out;
  for (const e of error.problem?.errors ?? []) {
    const field = (e.field || "").replace(/^(query|filters)\./, "");
    if (field && !out[field]) out[field] = e.message || "Check this value.";
  }
  return out;
}

/** SEC-31 runner for one Section H report with its documented filters (ADM-06), secondary data (ADM-07) and exports (ADM-05). */
export function ReportView({ reportKey }: { reportKey: string }) {
  const def = reportByKey(reportKey);
  // verified: api_engine.py report_catalogue returns reports.py REPORTS[*] incl. `filters`.
  const catalogue = useResource<{ data: ReportCatalogueEntry[] }>("security/reports");
  const apiFilters = catalogue.data?.data.find((r) => r.report_key === reportKey)?.filters;
  const namesKey = (apiFilters ?? REPORT_FILTERS[reportKey] ?? []).filter((n) => n in REPORT_FILTER_DEFS).join(",");
  const names = useMemo(() => (namesKey ? namesKey.split(",") : []), [namesKey]);
  const required = REQUIRED_REPORT_FILTERS[reportKey] ?? [];
  const [draft, setDraft] = useState<Record<string, string>>(() => initialFilters(reportKey, REPORT_FILTERS[reportKey] ?? []));
  const [applied, setApplied] = useState<Record<string, string>>(draft);
  const [reason, setReason] = useState("case_review");
  const [tracked, setTracked] = useState<TrackedExport[]>(() => readTrackedExports());

  const sent = useMemo(() => {
    const out: Record<string, string> = {};
    for (const n of names) {
      const v = applied[n]?.trim();
      if (v) out[n] = v;
    }
    return out;
  }, [applied, names]);
  const missing = required.filter((n) => !sent[n]);
  const query = useMemo(() => cleanQuery({ ...sent, reason_code: def?.perUser ? reason : "" }), [sent, def?.perUser, reason]);
  const res = useVersioned<ReportResult>(def && missing.length === 0 ? `security/reports/${reportKey}` : null, query);
  // 422 validation_failed names the filter (e.g. H12 `user_id` required/unknown): show it on that input.
  const fieldErrors = useMemo(() => filterErrors(res.error), [res.error]);

  if (!def) return <EmptyState title="Unknown report" description={`There is no Section H report with the key “${reportKey}”.`} />;

  const rows = res.data?.rows ?? [];
  const keys = Array.from(new Set(rows.flatMap((r) => Object.keys(r)).filter((k) => k !== "suppressed")));
  const cols: Column<Record<string, unknown>>[] = keys.map((k) => ({
    key: k,
    header: humanize(k),
    cell: (r) => (r.suppressed === true && (r[k] === null || r[k] === undefined) ? <span title="Fewer than the k-minimum subjects">&lt;k suppressed</span> : cellText(r[k])),
  }));

  return (
    <div>
      <PageHeader eyebrow={def.code} title={def.title} description={`Report key ${def.key}`} actions={<Link href="/security/reports" className={textLink}>All reports</Link>} />
      <form
        role="search"
        aria-label="Report filters"
        onSubmit={(e) => {
          e.preventDefault();
          setApplied(draft);
        }}
        className="mb-4 rounded-xl border border-line bg-surface p-4"
      >
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {names.map((n) => (
            <FilterInput key={n} def={REPORT_FILTER_DEFS[n]!} value={draft[n] ?? ""} required={required.includes(n)} error={fieldErrors[n]} onChange={(v) => setDraft((d) => ({ ...d, [n]: v }))} />
          ))}
          {def.perUser ? <FormField label="Reason" hint="Per-user report; viewing is audited">{(f) => <Select {...f} value={reason} onChange={(e) => setReason(e.target.value)} options={SECURITY_REASON_CODES} />}</FormField> : null}
        </div>
        <div className="mt-3">
          <Button type="submit" size="sm">
            Apply filters
          </Button>
        </div>
      </form>
      {missing.length ? (
        <p role="status" className="mb-3 rounded-lg border border-info-border bg-info-subtle p-3 text-sm text-info-fg">
          Enter {missing.map((n) => REPORT_FILTER_DEFS[n]?.label.toLowerCase() ?? n).join(", ")} and apply the filters to run this report.
        </p>
      ) : null}
      <div className="mb-3 flex items-center justify-between gap-3">
        <p className="text-xs text-fg-muted">
          {res.data?.generated_at ? `Generated ${formatDateTime(res.data.generated_at)} · ${formatDateTime(res.data.period.from)} to ${formatDateTime(res.data.period.to)}` : null}
          {typeof res.data?.k_min === "number" ? ` · cells under ${res.data.k_min} subjects are suppressed` : null}
        </p>
        <Button size="sm" variant="secondary" disabled={missing.length > 0} onClick={() => void res.reload()}>
          Refresh
        </Button>
      </div>
      {missing.length ? null : res.loading && !res.data ? (
        <Skeleton className="h-40 w-full" />
      ) : (
        <Table caption={`${def.code} ${def.title}`} columns={cols} rows={res.data ? rows : undefined} rowKey={(r) => JSON.stringify(r)} loading={res.loading} error={res.error} onRetry={() => void res.reload()} empty={{ title: "No rows for this period" }} />
      )}
      {res.data && !missing.length ? <ReportExtras result={res.data} /> : null}
      <ExportRequest key={JSON.stringify(sent)} reportKey={reportKey} perUserAllowed={def.perUser} filters={sent} onRequested={(job) => setTracked(trackExport(job))} />
      <MyExports tracked={tracked} reportKey={reportKey} />
    </div>
  );
}

/** SEC-32 export request (api_engine.py export_report, 202). Per-user reports always need a second security reviewer (ADM-01). */
export function ExportRequest({
  reportKey,
  perUserAllowed,
  filters,
  onRequested,
}: {
  reportKey: string;
  perUserAllowed: boolean;
  filters: Record<string, string>;
  onRequested?: (job: TrackedExport) => void;
}) {
  const [reasonCode, setReasonCode] = useState("qa_sample");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [result, setResult] = useState<ExportResponse | null>(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await api.post<ExportResponse>(
        `security/reports/${reportKey}/exports`,
        { filters, include_per_user_rows: perUserAllowed, reason_code: perUserAllowed ? reasonCode : undefined, reason: reason.trim() || undefined },
        { idempotencyKey: true },
      );
      if (res.kind === "approval_pending") {
        setResult({ export_job_id: "", status: "awaiting_approval", approval_request_id: res.approval.approval_request_id, contains_pii: true });
      } else {
        setResult(res.data);
        if (res.data.export_job_id) onRequested?.({ export_job_id: res.data.export_job_id, report_key: reportKey });
      }
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="Export CSV" className="mt-6">
      <p className="mb-3 text-sm text-fg-muted">
        Exports use the filters applied above. Watermarked with your name and time; the download is valid for 24 h and only for you. Needs a fresh confirmation.
        {perUserAllowed ? " This report has per-user rows, so a second security reviewer must approve the export." : ""}
      </p>
      <div className="space-y-3">
        {perUserAllowed ? <FormField label="Reason code">{(f) => <Select {...f} value={reasonCode} onChange={(e) => setReasonCode(e.target.value)} options={SECURITY_REASON_CODES} />}</FormField> : null}
        <FormField label="Purpose">{(f) => <TextArea {...f} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={1000} />}</FormField>
        <InlineProblem error={error} />
        <Button loading={busy} onClick={() => void submit()} disabled={!!result}>
          Request export
        </Button>
        {result ? (
          result.status === "awaiting_approval" ? (
            <>
              <ApprovalPendingNotice
                title="Export waiting for a second security reviewer"
                approval={{ approval_request_id: result.approval_request_id ?? "—", required_approver_role: "security_reviewer" }}
              />
              <p className="text-sm text-fg-muted">You are emailed when a reviewer decides; the file then appears under My exports.</p>
            </>
          ) : (
            <p role="status" className="text-sm text-fg">
              Export <span className="font-mono">{result.export_job_id}</span> is <StateBadge state={result.status} />.{" "}
              {result.status === "completed" ? "Download it from My exports below." : "Check its status under My exports below."}
            </p>
          )
        ) : null}
      </div>
    </Card>
  );
}

