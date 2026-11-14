"use client";

import { useState } from "react";
import { Badge, Button, Card, Table, useToast, type Column } from "@/components/ui";
import { ApiError } from "@/lib/api/errors";
import { StateBadge } from "@/features/admin/components/console-ui";
import { formatDateTime, shortRef } from "@/features/admin/lib/console";
import { useResource } from "@/features/account/lib/use-resource";
import { reportByKey } from "../lib/catalogue";
import { downloadCsv } from "../lib/download";
import type { SecurityExportJob } from "../lib/types";

/** A job requested in this browser session, shown even when the list endpoint is unavailable. */
export interface TrackedExport {
  export_job_id: string;
  report_key: string;
}

const TRACK_KEY = "td.security.exports";

/** Session-scoped memory of just-requested job ids (a convenience only; the api list is the source). */
export function readTrackedExports(): TrackedExport[] {
  try {
    const raw = sessionStorage.getItem(TRACK_KEY);
    const v: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(v) ? (v as TrackedExport[]).filter((x) => typeof x?.export_job_id === "string" && x.export_job_id) : [];
  } catch {
    return [];
  }
}

export function trackExport(job: TrackedExport): TrackedExport[] {
  const next = [job, ...readTrackedExports().filter((x) => x.export_job_id !== job.export_job_id)].slice(0, 20);
  try {
    sessionStorage.setItem(TRACK_KEY, JSON.stringify(next));
  } catch {
    /* storage unavailable: the in-memory list still shows it */
  }
  return next;
}

type Row = SecurityExportJob & { tracked_only?: boolean };

/**
 * ADM-05 / INV-11 "My exports": the caller's own Section H export jobs (GET
 * /security/reports/exports) with a download for completed ones (SEC-47 returns the CSV).
 * Jobs requested in this session stay visible even if the list endpoint is unavailable.
 */
export function MyExports({ tracked, reportKey }: { tracked: TrackedExport[]; reportKey?: string }) {
  const toast = useToast();
  const list = useResource<{ data: SecurityExportJob[] }>("security/reports/exports");
  const [busy, setBusy] = useState<string | null>(null);
  const [states, setStates] = useState<Record<string, string>>({});
  const listUnavailable = list.error instanceof ApiError && (list.error.status === 404 || list.error.status === 405);

  const fromApi = (list.data?.data ?? []).filter((j) => !reportKey || j.report_key === reportKey);
  const known = new Set(fromApi.map((j) => j.export_job_id));
  const extra: Row[] = tracked
    .filter((t) => !known.has(t.export_job_id) && (!reportKey || t.report_key === reportKey))
    .map((t) => ({
      export_job_id: t.export_job_id,
      report_key: t.report_key,
      status: states[t.export_job_id] ?? "unknown",
      contains_pii: false,
      approval_request_id: null,
      created_at: null,
      completed_at: null,
      download_expires_at: null,
      tracked_only: true,
    }));
  const rows: Row[] = [...extra, ...fromApi.map((j) => ({ ...j, status: states[j.export_job_id] ?? j.status }))];

  const download = async (j: Row) => {
    setBusy(j.export_job_id);
    try {
      // The list gives the download route as `download_path` (api_engine._export_out); tracked-only
      // rows (not yet listed) fall back to SEC-47 by id.
      const path = j.download_path ? j.download_path.replace(/^\/+/, "") : `security/reports/exports/${encodeURIComponent(j.export_job_id)}`;
      await downloadCsv(path, `${j.report_key}-${j.export_job_id}.csv`);
      setStates((s) => ({ ...s, [j.export_job_id]: "completed" }));
    } catch (err) {
      const e = err instanceof ApiError ? err : null;
      const current = typeof e?.problem?.current_state === "string" ? e.problem.current_state : null;
      if (e?.code === "invalid_state_transition" && current) {
        setStates((s) => ({ ...s, [j.export_job_id]: current }));
        toast.show({ title: "Not ready for download", description: `This export is ${current.replace(/_/g, " ")}.`, tone: "info" });
      } else {
        toast.show({ title: e?.title ?? "Download failed", description: e?.detail ?? "Please try again.", tone: "danger", requestId: e?.requestId ?? null });
      }
    } finally {
      setBusy(null);
    }
  };

  const cols: Column<Row>[] = [
    { key: "report", header: "Report", cell: (j) => reportByKey(j.report_key)?.title ?? j.report_key },
    { key: "job", header: "Reference", priority: "secondary", cell: (j) => shortRef(j.export_job_id) },
    {
      key: "status",
      header: "Status",
      cell: (j) => (
        <span className="flex flex-wrap items-center gap-1">
          {j.status === "unknown" ? <span className="text-fg-muted">Not checked</span> : <StateBadge state={j.status} />}
          {j.contains_pii ? <Badge tone="warning">Personal data</Badge> : null}
        </span>
      ),
    },
    { key: "at", header: "Requested", cell: (j) => formatDateTime(j.created_at) },
    { key: "until", header: "Download until", cell: (j) => formatDateTime(j.download_expires_at) },
    {
      key: "dl",
      header: <span className="sr-only">Download</span>,
      cell: (j) =>
        j.tracked_only || j.download_path || (j.status === "completed" && j.download_path === undefined) ? (
          <Button size="sm" variant="secondary" loading={busy === j.export_job_id} onClick={() => void download(j)} aria-label={`Download export ${shortRef(j.export_job_id)}`}>
            {j.tracked_only && j.status !== "completed" ? "Check and download" : "Download CSV"}
          </Button>
        ) : null,
    },
  ];

  return (
    <Card title="My exports" className="mt-6">
      <p className="mb-3 text-sm text-fg-muted">
        Only you can download your exports, for 24 h after they are ready. Per-user exports become available after a second security reviewer approves them; you are emailed when that happens.
      </p>
      {listUnavailable ? (
        <p role="status" className="mb-3 text-sm text-fg-muted">
          The export list is not available on this server. Exports requested in this browser session are shown below.
        </p>
      ) : null}
      <div className="mb-2 flex justify-end">
        <Button size="sm" variant="secondary" onClick={() => void list.reload()}>
          Refresh
        </Button>
      </div>
      <Table
        caption="My security report exports"
        columns={cols}
        rows={list.data || listUnavailable || extra.length ? rows : undefined}
        rowKey={(j) => j.export_job_id}
        loading={list.loading}
        error={listUnavailable ? null : list.error}
        onRetry={() => void list.reload()}
        empty={{ title: "No exports yet", description: "Open a report and use “Request export” to create a CSV." }}
      />
    </Card>
  );
}
