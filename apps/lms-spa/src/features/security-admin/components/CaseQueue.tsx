"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Badge, Button, FormField, Input, LinkButton, PageHeader, Pagination, Select, StatGrid, StatTile, statusLabel, Table, useToast, type Column } from "@/components/ui";
import { api } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { FilterBar, StateBadge, textLink } from "@/features/admin/components/console-ui";
import { cleanQuery, ifMatchFor, useCursorList } from "@/features/admin/lib/console";
import { staffRef } from "../lib/ids";
import { ASSIGNEE_OPTIONS, CASE_STATUS_OPTIONS, FAMILY_OPTIONS, LEVEL_OPTIONS, SLA_OPTIONS } from "../lib/catalogue";
import type { CaseSummary } from "../lib/types";
import { RiskBadge } from "./RiskLevel";
import { formatTimeUntil } from "@/lib/format";

/** Response-time (SLA) cell shared by the case and unblock queues: icon + word + due time, never colour alone. */
export function SlaCell({ row }: { row: { sla_state: string; sla_decision_due?: string | null; sla_first_response_due?: string | null } }) {
  const due = row.sla_decision_due ?? row.sla_first_response_due;
  // verified: app/modules/security/cases.py sla_state → "on_track" | "breaching" (≥ 80 %) | "breached" | "n/a"
  if (row.sla_state === "n/a") return <span className="text-fg-muted">—</span>;
  const breached = row.sla_state === "breached";
  const atRisk = row.sla_state === "breaching";
  return (
    <span className={breached ? "font-semibold text-danger-fg" : atRisk ? "text-warning-fg" : "text-fg"}>
      <span aria-hidden="true">{breached ? "⚠ " : atRisk ? "◔ " : "✓ "}</span>
      {breached ? "Breached" : atRisk ? "At risk" : "On track"}
      {due ? <span className="block text-xs text-fg-muted">due {formatTimeUntil(due)}</span> : null}
    </span>
  );
}

/** Case age in words ("5 h", "3 days"). */
function ageText(hours: number): string {
  if (hours < 48) return `${hours} h`;
  const days = Math.round(hours / 24);
  return `${days} days`;
}

/** Suspicious-activity case queue (SEC-03) with filters, counts and claim. */
export function CaseQueue() {
  const toast = useToast();
  const [status, setStatus] = useState("open,under_review,escalated");
  // Dashboard tiles link here with ?status=…; read it once on the client (no Suspense boundary needed).
  useEffect(() => {
    const wanted = new URLSearchParams(window.location.search).get("status");
    if (wanted && /^[a-z_,]+$/.test(wanted)) setStatus(wanted);
  }, []);
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
    { key: "score", header: "Score", align: "right", priority: "secondary", cell: (r) => (typeof r.score === "number" ? r.score.toFixed(1) : "—") },
    { key: "hc", header: "Automatic rule", priority: "secondary", cell: (r) => r.hc_rule ?? "—" },
    { key: "status", header: "Status", cell: (r) => <StateBadge state={r.status} /> },
    { key: "age", header: "Age", align: "right", cell: (r) => (typeof r.age_hours === "number" ? ageText(r.age_hours) : "—") },
    { key: "sla", header: "SLA", cell: (r) => <SlaCell row={r} /> },
    {
      key: "assignee",
      header: "Assignee",
      cell: (r) =>
        r.assignee_id ? (
          <span className="text-sm">{staffRef(r.assignee_id, "Reviewer")}</span>
        ) : (
          <>
            <Button className="hidden lg:inline-flex" size="sm" variant="secondary" loading={claiming === r.case_id} onClick={() => void claim(r)} aria-label={`Claim ${r.case_ref}`}>
              Claim
            </Button>
            <span className="text-fg-muted lg:hidden">Unassigned</span>
          </>
        ),
    },
    {
      key: "flags",
      header: "Flags",
      priority: "secondary",
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
        breadcrumbs={[{ label: "Security", href: "/security" }, { label: "Cases" }]}
        title="Cases"
        description="Suspicious-activity cases, most urgent first. Student names appear inside a case after you give a reason for opening it."
        actions={
          <LinkButton href="/security/reports/top-suspicious-accounts" variant="secondary">
            High-risk accounts without a case
          </LinkButton>
        }
      />
      {counts ? (
        <StatGrid className="mb-4">
          {Object.entries(counts).map(([k, v]) => (
            <StatTile key={k} size="compact" label={statusLabel(k)} value={v.toLocaleString("en-IN")} tone={v > 0 && (k === "escalated" || k === "breached") ? "danger" : v > 0 && (k === "open" || k === "breaching") ? "warning" : "neutral"} />
          ))}
        </StatGrid>
      ) : null}
      <FilterBar label="Case filters">
        <FormField label="Status">{(f) => <Select {...f} value={status} onChange={(e) => setStatus(e.target.value)} options={CASE_STATUS_OPTIONS} />}</FormField>
        <FormField label="Level">{(f) => <Select {...f} value={level} onChange={(e) => setLevel(e.target.value)} options={LEVEL_OPTIONS} />}</FormField>
        <FormField label="Family">{(f) => <Select {...f} value={family} onChange={(e) => setFamily(e.target.value)} options={FAMILY_OPTIONS} />}</FormField>
        <FormField label="Response time">{(f) => <Select {...f} value={sla} onChange={(e) => setSla(e.target.value)} options={SLA_OPTIONS} />}</FormField>
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
        <FormField label="Rule" hint="Rule key, e.g. SH-01 or HC-01">
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
        empty={{ title: "No cases match these filters", description: "Try “All open” status and “Any level”." }}
        footer={<Pagination hasMore={list.hasMore} hasPrevious={list.hasPrevious} onNext={list.next} onPrevious={list.previous} loading={list.loading} label="Case pages" />}
      />
      <p className="mt-3 text-xs text-fg-muted lg:hidden">Claiming and deciding cases needs a larger screen (1024 px or wider). On this screen the queue is read-only.</p>
    </div>
  );
}
