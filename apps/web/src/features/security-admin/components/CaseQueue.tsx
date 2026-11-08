"use client";

import Link from "next/link";
import { useState } from "react";
import { Badge, Button, FormField, Input, PageHeader, Pagination, Select, StatTile, Table, useToast, type Column } from "@/components/ui";
import { api } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { FilterBar, linkButton, StateBadge, textLink } from "@/features/admin/components/console-ui";
import { cleanQuery, formatCountdown, humanize, ifMatchFor, useCursorList } from "@/features/admin/lib/console";
import { ASSIGNEE_OPTIONS, CASE_STATUS_OPTIONS, FAMILY_OPTIONS, LEVEL_OPTIONS, SLA_OPTIONS } from "../lib/catalogue";
import type { CaseSummary } from "../lib/types";
import { RiskBadge } from "./RiskLevel";

function SlaCell({ row }: { row: CaseSummary }) {
  const due = row.sla_decision_due ?? row.sla_first_response_due;
  // verified: app/modules/security/cases.py sla_state → "on_track" | "breaching" (≥ 80 %) | "breached" | "n/a"
  if (row.sla_state === "n/a") return <span className="text-fg-muted">—</span>;
  const breached = row.sla_state === "breached";
  const atRisk = row.sla_state === "breaching";
  return (
    <span className={breached ? "font-semibold text-danger-fg" : atRisk ? "text-warning-fg" : "text-fg"}>
      <span aria-hidden="true">{breached ? "⚠ " : atRisk ? "◔ " : "✓ "}</span>
      {breached ? "Breached" : atRisk ? "At risk" : "On track"}
      {due ? <span className="block text-xs text-fg-muted">due {formatCountdown(due)}</span> : null}
    </span>
  );
}

/** SEC-002 suspicious-activity queue (H1, SEC-03) with filters, counts and claim. */
export function CaseQueue() {
  const toast = useToast();
  const [status, setStatus] = useState("open,under_review,escalated");
  const [level, setLevel] = useState("");
  const [family, setFamily] = useState("");
  const [sla, setSla] = useState("");
  const [assignee, setAssignee] = useState("");
  const [highRisk, setHighRisk] = useState("");
  const [rule, setRule] = useState("");
  const [claiming, setClaiming] = useState<string | null>(null);

  const list = useCursorList<CaseSummary>("security/cases", cleanQuery({ status, level, family, sla_state: sla, assignee, high_risk: highRisk, rule: rule.trim(), limit: 50 }));
  const counts = list.envelope?.counts;

  const claim = async (row: CaseSummary) => {
    setClaiming(row.case_id);
    try {
      await api.post(`security/cases/${row.case_id}/claim`, {}, { ifMatch: ifMatchFor(null, row.version) });
      toast.show({ title: `You claimed ${row.case_ref}.`, tone: "success" });
      await list.reload();
    } catch (err) {
      const e = err instanceof ApiError ? err : null;
      toast.show({
        title: e?.code === "conflict_of_interest" ? "You can't take this case" : (e?.title ?? "Could not claim the case"),
        description: e?.code === "conflict_of_interest" ? "You applied this restriction or have a conflict, so another reviewer must take it." : e?.detail,
        tone: "danger",
        requestId: e?.requestId,
      });
    } finally {
      setClaiming(null);
    }
  };

  const columns: Column<CaseSummary>[] = [
    {
      key: "case",
      header: "Case",
      cell: (r) => (
        <Link href={`/security/cases/${r.case_id}`} className={`${textLink} font-mono`}>
          {r.case_ref}
        </Link>
      ),
    },
    { key: "level", header: "Level", cell: (r) => <RiskBadge level={r.level} compact /> },
    { key: "score", header: "Score", align: "right", cell: (r) => (typeof r.score === "number" ? r.score.toFixed(1) : "—") },
    { key: "hc", header: "HC rule", cell: (r) => r.hc_rule ?? "—" },
    { key: "status", header: "Status", cell: (r) => <StateBadge state={r.status} /> },
    { key: "age", header: "Age", align: "right", cell: (r) => (typeof r.age_hours === "number" ? (r.age_hours < 48 ? `${r.age_hours} h` : `${Math.round(r.age_hours / 24)} d`) : "—") },
    { key: "sla", header: "SLA", cell: (r) => <SlaCell row={r} /> },
    {
      key: "assignee",
      header: "Assignee",
      cell: (r) =>
        r.assignee_id ? (
          <span className="font-mono text-xs">{r.assignee_id}</span>
        ) : (
          <Button size="sm" variant="secondary" loading={claiming === r.case_id} onClick={() => void claim(r)} aria-label={`Claim ${r.case_ref}`}>
            Claim
          </Button>
        ),
    },
    {
      key: "flags",
      header: "Flags",
      cell: (r) => (
        <span className="flex flex-wrap gap-1">
          {r.is_high_risk ? <Badge tone="warning">⚑ High-risk</Badge> : null}
          {r.repeat_count ? <Badge tone="neutral">↺ Repeat ×{r.repeat_count}</Badge> : null}
          {r.unblock_request?.reference ? <Badge tone="info">{r.unblock_request.reference}</Badge> : null}
        </span>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        eyebrow="SEC-002 · H1"
        title="Suspicious-activity queue"
        description="Open cases by priority, then SLA. Students are shown by internal id only; names appear inside a case after you give a reason."
        actions={
          <Link href="/security/reports/top-suspicious-accounts" className={linkButton}>
            High score, no case (H1 tab 2)
          </Link>
        }
      />
      {counts ? (
        <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
          {Object.entries(counts).map(([k, v]) => (
            <StatTile key={k} label={humanize(k)} value={v.toLocaleString("en-IN")} />
          ))}
        </div>
      ) : null}
      <FilterBar label="Case filters">
        <FormField label="Status">{(f) => <Select {...f} value={status} onChange={(e) => setStatus(e.target.value)} options={CASE_STATUS_OPTIONS} />}</FormField>
        <FormField label="Level">{(f) => <Select {...f} value={level} onChange={(e) => setLevel(e.target.value)} options={LEVEL_OPTIONS} />}</FormField>
        <FormField label="Family">{(f) => <Select {...f} value={family} onChange={(e) => setFamily(e.target.value)} options={FAMILY_OPTIONS} />}</FormField>
        <FormField label="SLA">{(f) => <Select {...f} value={sla} onChange={(e) => setSla(e.target.value)} options={SLA_OPTIONS} />}</FormField>
        <FormField label="Assignee">{(f) => <Select {...f} value={assignee} onChange={(e) => setAssignee(e.target.value)} options={ASSIGNEE_OPTIONS} />}</FormField>
        <FormField label="High-risk">
          {(f) => (
            <Select
              {...f}
              value={highRisk}
              onChange={(e) => setHighRisk(e.target.value)}
              options={[
                { value: "", label: "Any" },
                { value: "true", label: "High-risk only" },
              ]}
            />
          )}
        </FormField>
        <FormField label="Rule" hint="e.g. SH-01 or HC-01">
          {(f) => <Input {...f} value={rule} onChange={(e) => setRule(e.target.value)} />}
        </FormField>
      </FilterBar>
      <Table
        caption="Security cases"
        columns={columns}
        rows={list.rows}
        rowKey={(r) => r.case_id}
        loading={list.loading}
        error={list.error}
        onRetry={() => void list.reload()}
        empty={{ title: "No cases match these filters", description: "Try widening the status or level filters." }}
        footer={<Pagination hasMore={list.hasMore} hasPrevious={list.hasPrevious} onNext={list.next} onPrevious={list.previous} loading={list.loading} label="Case pages" />}
      />
      <p className="mt-3 text-xs text-fg-muted lg:hidden">Decisions are made on a larger screen (≥ 1024 px). This list is read-only on phones.</p>
    </div>
  );
}
