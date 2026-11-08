"use client";

import { useState } from "react";
import { Button, Card, FormField, Input, PageHeader, Pagination, Select, Table, Tabs, useToast, type Column } from "@/components/ui";
import { api } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { ActionDialog, FilterBar, InlineProblem, JsonBlock, StateBadge, TextArea } from "@/features/admin/components/console-ui";
import { cleanQuery, formatDateTime, humanize, toOutcome, useCursorList } from "@/features/admin/lib/console";
import type { RuleRow, RuleVersion } from "../lib/types";

const SHADOW_DAYS = 14;

function shadowDays(v: RuleVersion): number | null {
  if (!v.shadow_started_at) return null;
  const t = Date.parse(v.shadow_started_at);
  return Number.isNaN(t) ? null : Math.floor((Date.now() - t) / 86_400_000);
}


/** SEC-006 rule catalogue (SEC-22) and versions (SEC-23..29): propose, simulate, shadow, activate (Dual). */
export function RuleVersions() {
  return (
    <div>
      <PageHeader eyebrow="SEC-006" title="Risk rules" description="Rule catalogue and versions. New versions run in shadow for at least 14 days before activation, which a super admin approves." />
      <Tabs
        label="Rules"
        items={[
          { id: "versions", label: "Versions", content: <VersionsList /> },
          { id: "catalogue", label: "Catalogue", content: <RuleCatalogue /> },
        ]}
      />
    </div>
  );
}

function RuleCatalogue() {
  // verified: api_engine.py rules → {data: [...]} (not paginated)
  const list = useCursorList<RuleRow>("security/rules");
  const cols: Column<RuleRow>[] = [
    { key: "key", header: "Rule", cell: (r) => <span className="font-mono">{r.key}</span> },
    { key: "family", header: "Family", cell: (r) => humanize(r.family) },
    { key: "cat", header: "Category", cell: (r) => humanize(r.category) },
    { key: "desc", header: "Description", cell: (r) => r.description ?? "—" },
    {
      key: "active",
      header: "Active version",
      cell: (r) =>
        r.active_version ? (
          <span className="flex items-center gap-2">
            {r.active_version.semver ? <span className="font-mono">v{r.active_version.semver}</span> : null}
            <StateBadge state={r.active_version.status} />
          </span>
        ) : (
          "—"
        ),
    },
  ];
  return <Table caption="Rule catalogue" columns={cols} rows={list.rows} rowKey={(r) => r.key} loading={list.loading} error={list.error} onRetry={() => void list.reload()} footer={<Pagination hasMore={list.hasMore} hasPrevious={list.hasPrevious} onNext={list.next} onPrevious={list.previous} />} />;
}

function VersionsList() {
  const toast = useToast();
  const [status, setStatus] = useState("");
  const [family, setFamily] = useState("");
  const list = useCursorList<RuleVersion>("security/rule-versions", cleanQuery({ status, family }));
  const [dialog, setDialog] = useState<{ kind: "propose" | "activate" | "rollback"; version?: RuleVersion } | null>(null);
  const [report, setReport] = useState<{ version: RuleVersion; data?: unknown; error?: unknown } | null>(null);
  const [ruleKey, setRuleKey] = useState("");
  const [semver, setSemver] = useState("");
  const [definition, setDefinition] = useState("{\n  \n}");
  const [reason, setReason] = useState("");
  const [effective, setEffective] = useState("");

  const simple = async (v: RuleVersion, action: "simulate" | "start-shadow") => {
    try {
      const res = await api.post(`security/rule-versions/${v.version_id}/${action}`, {}, { idempotencyKey: true });
      // verified: api_engine.py simulate returns the shadow report synchronously (controls.py shadow_report).
      if (action === "simulate" && res.kind === "ok") setReport({ version: v, data: res.data });
      toast.show({ title: action === "simulate" ? "Simulation complete (last 30 days)." : "Version moved to shadow.", tone: "success" });
      void list.reload();
    } catch (err) {
      const e = err instanceof ApiError ? err : null;
      toast.show({ title: e?.title ?? "Action failed", description: e?.detail, tone: "danger", requestId: e?.requestId });
    }
  };

  const openReport = async (v: RuleVersion) => {
    setReport({ version: v });
    try {
      const data = await api.get(`security/rule-versions/${v.version_id}/shadow-report`);
      setReport({ version: v, data });
    } catch (err) {
      setReport({ version: v, error: err });
    }
  };

  const cols: Column<RuleVersion>[] = [
    { key: "rule", header: "Rule / ruleset", cell: (v) => <span className="font-mono">{v.rule_key ?? v.ruleset_version ?? v.family}</span> },
    { key: "ver", header: "Version", cell: (v) => <span className="font-mono">v{v.semver}</span> },
    {
      key: "status",
      header: "Status",
      cell: (v) => (
        <span className="flex flex-col gap-1">
          <StateBadge state={v.status} />
          {v.status_change_reason ? <span className="text-xs text-fg-muted">{humanize(v.status_change_reason)}</span> : null}
        </span>
      ),
    },
    {
      key: "shadow",
      header: "Shadow",
      cell: (v) => {
        const d = shadowDays(v);
        return d === null ? "—" : `${d} of ${SHADOW_DAYS} days`;
      },
    },
    { key: "by", header: "Proposed by", cell: (v) => <span className="font-mono text-xs">{v.proposed_by}</span> },
    { key: "eligible", header: "Eligible from", cell: (v) => formatDateTime(v.eligible_at) },
    {
      key: "act",
      header: <span className="sr-only">Actions</span>,
      cell: (v) => {
        const d = shadowDays(v);
        return (
          <span className="flex flex-wrap gap-1">
            {v.status === "draft" ? (
              <>
                <Button size="sm" variant="secondary" onClick={() => void simple(v, "simulate")}>
                  Simulate
                </Button>
                <Button size="sm" variant="secondary" onClick={() => void simple(v, "start-shadow")}>
                  Start shadow
                </Button>
              </>
            ) : null}
            {v.status === "shadow" ? (
              <>
                <Button size="sm" variant="secondary" onClick={() => void openReport(v)}>
                  Shadow report
                </Button>
                <Button size="sm" disabled={d === null || d < SHADOW_DAYS} onClick={() => setDialog({ kind: "activate", version: v })} title={d !== null && d < SHADOW_DAYS ? `Shadow period incomplete (${d}/${SHADOW_DAYS} days)` : undefined}>
                  Request activation
                </Button>
              </>
            ) : null}
            {v.status === "retired" ? (
              <Button size="sm" variant="secondary" onClick={() => setDialog({ kind: "rollback", version: v })}>
                Request rollback
              </Button>
            ) : null}
          </span>
        );
      },
    },
  ];

  return (
    <div>
      <div className="mb-3 flex justify-end">
        <Button onClick={() => setDialog({ kind: "propose" })}>Propose new version</Button>
      </div>
      <FilterBar label="Version filters">
        <FormField label="Status">
          {(f) => (
            <Select
              {...f}
              value={status}
              onChange={(e) => setStatus(e.target.value)}
              options={[{ value: "", label: "Any" }, ...["draft", "shadow", "active", "retired"].map((s) => ({ value: s, label: humanize(s) }))]}
            />
          )}
        </FormField>
        <FormField label="Family">
          {(f) => (
            <Select
              {...f}
              value={family}
              onChange={(e) => setFamily(e.target.value)}
              options={[
                { value: "", label: "Any" },
                { value: "sharing", label: "Sharing" },
                { value: "takeover", label: "Takeover" },
                { value: "abuse", label: "Abuse" },
                { value: "integrity", label: "Integrity" },
              ]}
            />
          )}
        </FormField>
      </FilterBar>
      <Table caption="Rule versions" columns={cols} rows={list.rows} rowKey={(v) => v.version_id} loading={list.loading} error={list.error} onRetry={() => void list.reload()} empty={{ title: "No versions" }} footer={<Pagination hasMore={list.hasMore} hasPrevious={list.hasPrevious} onNext={list.next} onPrevious={list.previous} />} />

      {report ? (
        <Card title={`Shadow report · v${report.version.semver}`} className="mt-4" actions={<Button size="sm" variant="ghost" onClick={() => setReport(null)}>Close</Button>}>
          {report.error ? <InlineProblem error={report.error} /> : report.data ? <JsonBlock label="Shadow report" value={report.data} /> : <p className="text-sm text-fg-muted">Loading…</p>}
        </Card>
      ) : null}

      <ActionDialog
        open={dialog?.kind === "propose"}
        onClose={() => setDialog(null)}
        title="Propose a rule version"
        description="Creates a draft. Simulate it, then run it in shadow for 14 days before requesting activation."
        submitLabel="Create draft"
        validate={() => {
          if (!ruleKey.trim() || !/^\d+\.\d+\.\d+$/.test(semver.trim())) return "Enter the rule key and a semantic version (e.g. 1.1.0).";
          try {
            const parsed: unknown = JSON.parse(definition);
            if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return "The definition must be a JSON object.";
          } catch {
            return "The definition must be valid JSON.";
          }
          return null;
        }}
        onSubmit={async () => toOutcome(await api.post("security/rule-versions", { rule_key: ruleKey.trim(), semver: semver.trim(), definition: JSON.parse(definition) as Record<string, unknown> }, { idempotencyKey: true }))}
        onDone={() => void list.reload()}
      >
        <FormField label="Rule key" required>{(f) => <Input {...f} value={ruleKey} onChange={(e) => setRuleKey(e.target.value)} placeholder="SH-01" />}</FormField>
        <FormField label="Version" required>{(f) => <Input {...f} value={semver} onChange={(e) => setSemver(e.target.value)} placeholder="1.1.0" />}</FormField>
        <FormField label="Definition (JSON)" required>{(f) => <TextArea {...f} className="font-mono" value={definition} onChange={(e) => setDefinition(e.target.value)} />}</FormField>
      </ActionDialog>

      <ActionDialog
        open={dialog?.kind === "activate" || dialog?.kind === "rollback"}
        onClose={() => setDialog(null)}
        title={dialog?.kind === "rollback" ? `Request rollback to v${dialog.version?.semver ?? ""}` : `Request activation of v${dialog?.version?.semver ?? ""}`}
        description="A super admin (not you) must approve. Restrictions already in force are not changed retroactively."
        submitLabel="Request approval"
        validate={() => (reason.trim().length < 10 ? "Explain why (10+ characters)." : null)}
        onSubmit={async () =>
          toOutcome(
            await api.post(
              `security/rule-versions/${dialog!.version!.version_id}/${dialog!.kind === "rollback" ? "rollback-requests" : "activation-requests"}`,
              { reason: reason.trim(), effective_from: effective ? new Date(effective).toISOString() : undefined },
              { idempotencyKey: true },
            ),
          )
        }
        onDone={() => {
          setReason("");
          void list.reload();
        }}
      >
        <FormField label="Reason" required>{(f) => <TextArea {...f} value={reason} onChange={(e) => setReason(e.target.value)} />}</FormField>
        <FormField label="Effective from" hint="Optional; defaults to on approval">{(f) => <Input {...f} type="datetime-local" value={effective} onChange={(e) => setEffective(e.target.value)} />}</FormField>
      </ActionDialog>
    </div>
  );
}
