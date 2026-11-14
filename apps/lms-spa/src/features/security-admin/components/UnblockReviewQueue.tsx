"use client";

import { useState } from "react";
import { Badge, Button, FormField, PageHeader, Pagination, Select, Table, useToast, type Column } from "@/components/ui";
import { api } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { FilterBar, StateBadge } from "@/features/admin/components/console-ui";
import { formatDateTime, ifMatchFor, useCursorList } from "@/features/admin/lib/console";
import { staffRef } from "../lib/ids";
import { LEVEL_OPTIONS, SLA_OPTIONS, UNBLOCK_STATE_OPTIONS } from "../lib/catalogue";
import type { ReviewUnblockRow } from "../lib/types";
import { SlaCell } from "./CaseQueue";
import { RiskBadge } from "./RiskLevel";

/** Reviewer queue for unblock requests and appeals (UNB-10) with claim (UNB-12). */
export function UnblockReviewQueue() {
  const toast = useToast();
  const [state, setState] = useState(UNBLOCK_STATE_OPTIONS[0]!.value);
  const [level, setLevel] = useState("");
  const [sla, setSla] = useState("");
  const [second, setSecond] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  // verified: api_review.py review_queue filters only by `state`; level / SLA / second approval are filtered on the loaded rows.
  const list = useCursorList<ReviewUnblockRow>("security/review/unblock-requests", { state });
  const rows = list.rows?.filter((r) => (!level || level.split(",").includes(String(r.level))) && (!sla || r.sla_state === sla) && (!second || r.requires_second_approval));
  const clientFiltered = !!level || !!sla || !!second;

  const claim = async (r: ReviewUnblockRow) => {
    setBusy(r.request_id);
    try {
      await api.post(`security/review/unblock-requests/${r.request_id}/claim`, {}, { ifMatch: ifMatchFor(null, r.version) });
      toast.show({ title: `Claimed ${r.reference}.`, tone: "success" });
      await list.reload();
    } catch (err) {
      const e = err instanceof ApiError ? err : null;
      toast.show({ title: e?.code === "conflict_of_interest" ? "You can't take this request" : (e?.title ?? "Could not claim"), description: e?.detail, tone: "danger", requestId: e?.requestId });
    } finally {
      setBusy(null);
    }
  };

  const cols: Column<ReviewUnblockRow>[] = [
    { key: "ref", header: "Request", cell: (r) => <span className="font-mono">{r.reference}</span> },
    { key: "case", header: "Case", cell: (r) => <span className="font-mono">{r.case_ref ?? "—"}</span> },
    { key: "level", header: "Level", cell: (r) => <RiskBadge level={r.level} compact /> },
    {
      key: "state",
      header: "State",
      cell: (r) => (
        <span className="flex flex-wrap gap-1">
          <StateBadge state={r.state} label={r.state_label} />
          {r.is_second_level_appeal ? <Badge tone="info">Appeal</Badge> : null}
        </span>
      ),
    },
    { key: "second", header: "Second approval", priority: "secondary", cell: (r) => (r.requires_second_approval ? <Badge tone="warning">⇄ Pending</Badge> : "—") },
    { key: "submitted", header: "Submitted", cell: (r) => formatDateTime(r.submitted_at) },
    { key: "sla", header: "Response time", cell: (r) => <SlaCell row={r} /> },
    {
      key: "assignee",
      header: "Assignee",
      cell: (r) =>
        r.assignee ? (
          <span className="text-sm">{staffRef(r.assignee, "Reviewer")}</span>
        ) : r.state === "submitted" || r.state === "escalated" ? (
          <Button size="sm" variant="secondary" loading={busy === r.request_id} onClick={() => void claim(r)} aria-label={`Claim ${r.reference}`}>
            Claim
          </Button>
        ) : (
          "—"
        ),
    },
  ];

  return (
    <div>
      <PageHeader
        breadcrumbs={[{ label: "Security", href: "/security" }, { label: "Unblock reviews" }]}
        title="Unblock reviews"
        description="Students asking for a restriction to be lifted, and their appeals. Claim one, then decide it on the linked case."
      />
      <FilterBar label="Unblock request filters">
        <FormField label="State">{(f) => <Select {...f} value={state} onChange={(e) => setState(e.target.value)} options={UNBLOCK_STATE_OPTIONS} />}</FormField>
        <FormField label="Level" hint="Within this page">{(f) => <Select {...f} value={level} onChange={(e) => setLevel(e.target.value)} options={LEVEL_OPTIONS} />}</FormField>
        <FormField label="Response time" hint="Within this page">{(f) => <Select {...f} value={sla} onChange={(e) => setSla(e.target.value)} options={SLA_OPTIONS} />}</FormField>
        <FormField label="Second approval" hint="Within this page">
          {(f) => (
            <Select
              {...f}
              value={second}
              onChange={(e) => setSecond(e.target.value)}
              options={[
                { value: "", label: "Any" },
                { value: "true", label: "Pending second approval" },
              ]}
            />
          )}
        </FormField>
      </FilterBar>
      {clientFiltered ? (
        <p role="status" className="mb-3 text-xs text-fg-muted">
          Level, response time and second approval filter only the requests loaded on this page. Use Next page to check further results.
        </p>
      ) : null}
      <Table
        caption="Unblock requests"
        columns={cols}
        rows={rows}
        rowKey={(r) => r.request_id}
        loading={list.loading}
        error={list.error}
        onRetry={() => void list.reload()}
        empty={{
          title: clientFiltered ? "No matches on this page" : "No requests waiting",
          description: clientFiltered ? "Try the next page, or clear the Level, Response time and Second approval filters." : "New unblock requests and appeals appear here as students submit them.",
        }}
        footer={<Pagination hasMore={list.hasMore} hasPrevious={list.hasPrevious} onNext={list.next} onPrevious={list.previous} loading={list.loading} />}
      />
    </div>
  );
}
