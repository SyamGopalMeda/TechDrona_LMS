"use client";

import { useState } from "react";
import { Button, Dialog, FormField, Input, LoadingBlock, PageHeader, Pagination, Select, Table, Tabs, useToast, type Column } from "@/components/ui";
import { api } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { ActionDialog, ConfirmDialog, FilterBar, InlineProblem, StateBadge, TextArea, ValueSummary } from "@/features/admin/components/console-ui";
import { cleanQuery, humanize, toOutcome, useCursorList } from "@/features/admin/lib/console";
import { staffRef } from "../lib/ids";
import type { RuleRow, RuleVersion } from "../lib/types";
import { formatDateTime } from "@/lib/format";
import { istLocalToIso } from "@/lib/time";

const SHADOW_DAYS = 14;

function shadowDays(v: RuleVersion): number | null {
  if (!v.shadow_started_at) return null;
  const t = Date.parse(v.shadow_started_at);
  return Number.isNaN(t) ? null : Math.floor((Date.now() - t) / 86_400_000);
}

/** Rule catalogue (SEC-22) and versions (SEC-23..29): propose, simulate, shadow, activate (two-person approval). */
export function RuleVersions() {
  return (
    <div>
      <PageHeader
        breadcrumbs={[{ label: "Security", href: "/security" }, { label: "Risk rules" }]}
        title="Risk rules"
        description="The rules that score suspicious activity. A new version first runs in watch-only (shadow) mode for 14 days; then a super admin approves activating it."
      />
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
  return <Table caption="Rule catalogue" columns={cols} rows={list.rows} rowKey={(r) => r.key} empty={{ title: "No rules yet", description: "Rules are added with a new version under the Versions tab." }} loading={list.loading} error={list.error} onRetry={() => void list.reload()} footer={<Pagination hasMore={list.hasMore} hasPrevious={list.hasPrevious} onNext={list.next} onPrevious={list.previous} />} />;
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
  const [shadowFor, setShadowFor] = useState<RuleVersion | null>(null);

  const startShadow = async (v: RuleVersion) => {
    await api.post(`security/rule-versions/${v.version_id}/start-shadow`, {}, { idempotencyKey: true });
    toast.show({ title: "Version moved to shadow.", tone: "success" });
    void list.reload();
  };

  const simple = async (v: RuleVersion, action: "simulate") => {
    try {
      const res = await api.post(`security/rule-versions/${v.version_id}/${action}`, {}, { idempotencyKey: true });
      // verified: api_engine.py simulate returns the shadow report synchronously (controls.py shadow_report).
      if (action === "simulate" && res.kind === "ok") setReport({ version: v, data: res.data });
      toast.show({ title: "Simulation complete (last 30 days).", tone: "success" });
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
    { key: "by", header: "Proposed by", priority: "secondary", cell: (v) => staffRef(v.proposed_by) },
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
                <Button size="sm" variant="secondary" onClick={() => setShadowFor(v)}>
                  Start shadow
                </Button>
              </>
            ) : null}
            {v.status === "shadow" ? (
              <>
                <Button size="sm" variant="secondary" onClick={() => void openReport(v)}>
                  Shadow report
                </Button>
                <Button
                  size="sm"
                  disabled={d === null || d < SHADOW_DAYS}
                  aria-describedby={d === null || d < SHADOW_DAYS ? `shadow-wait-${v.version_id}` : undefined}
                  onClick={() => setDialog({ kind: "activate", version: v })}
                >
                  Request activation
                </Button>
                {d === null || d < SHADOW_DAYS ? (
                  <span id={`shadow-wait-${v.version_id}`} className="basis-full text-xs text-fg-muted">
                    Available after {SHADOW_DAYS} days in shadow{d !== null ? ` (${d} of ${SHADOW_DAYS} so far)` : ""}.
                  </span>
                ) : null}
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
      <Table caption="Rule versions" columns={cols} rows={list.rows} rowKey={(v) => v.version_id} loading={list.loading} error={list.error} onRetry={() => void list.reload()} empty={{ title: "No versions match", description: "Set Status and Family to “Any”, or propose a new version." }} footer={<Pagination hasMore={list.hasMore} hasPrevious={list.hasPrevious} onNext={list.next} onPrevious={list.previous} />} />

      {/* Opens on top (bottom sheet on phones) instead of below a long table. */}
      <Dialog
        open={report !== null}
        onClose={() => setReport(null)}
        size="lg"
        title={report ? `Shadow report · ${report.version.rule_key ?? report.version.family} v${report.version.semver}` : "Shadow report"}
        description="What this version would have done compared with the active rules. Nobody was restricted by it."
      >
        {report?.error ? (
          <InlineProblem error={report.error} />
        ) : report?.data ? (
          <ValueSummary label="Shadow report" value={report.data} />
        ) : (
          <LoadingBlock label="Loading shadow report…" rows={3} />
        )}
      </Dialog>

      <ActionDialog
        open={dialog?.kind === "propose"}
        onClose={() => setDialog(null)}
        onOpen={() => {
          setRuleKey("");
          setSemver("");
          setDefinition("{\n  \n}");
        }}
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
        onOpen={() => {
          setReason("");
          setEffective("");
        }}
        title={dialog?.kind === "rollback" ? `Request rollback to v${dialog.version?.semver ?? ""}` : `Request activation of v${dialog?.version?.semver ?? ""}`}
        description="A super admin (not you) must approve. Restrictions already in force are not changed retroactively."
        submitLabel="Request approval"
        validate={() => (reason.trim().length < 10 ? "Explain why (10+ characters)." : effective && !istLocalToIso(effective) ? "Enter a valid date and time, or leave it empty." : null)}
        onSubmit={async () =>
          toOutcome(
            await api.post(
              `security/rule-versions/${dialog!.version!.version_id}/${dialog!.kind === "rollback" ? "rollback-requests" : "activation-requests"}`,
              { reason: reason.trim(), effective_from: effective ? (istLocalToIso(effective) ?? undefined) : undefined },
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
        <FormField label="Effective from (IST)" hint="Optional. India time; empty means as soon as it is approved.">{(f) => <Input {...f} type="datetime-local" value={effective} onChange={(e) => setEffective(e.target.value)} />}</FormField>
      </ActionDialog>

      <ConfirmDialog
        open={shadowFor !== null}
        onClose={() => setShadowFor(null)}
        title={`Start shadow for v${shadowFor?.semver ?? ""}?`}
        description={`The draft moves to shadow and cannot go back to draft. For the next ${SHADOW_DAYS} days it is compared against the active rules without restricting anyone; activation can only be requested once all ${SHADOW_DAYS} days are complete.`}
        confirmLabel="Start shadow"
        onConfirm={() => startShadow(shadowFor!)}
      />
    </div>
  );
}
