"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Button, Card, Checkbox, FormField, Input, PageHeader, Pagination, Select, Table, useToast, type Column } from "@/components/ui";
import { api } from "@/lib/api/client";
import { ActionDialog, ApprovalPendingNotice, FilterBar, InlineProblem, KeyValueList, StateBadge, TextArea, textLink, ValueSummary } from "@/features/admin/components/console-ui";
import { cleanQuery, formatDateTime, humanize, shortRef, toOutcome, useCursorList } from "@/features/admin/lib/console";
import type { ApprovalPending } from "@/lib/api/client";
import { FAMILY_OPTIONS, LEVEL_OPTIONS, SOURCE_OPTIONS, sourceLabel } from "../lib/catalogue";
import type { BulkLiftStatus as BulkLiftStatusData, Restriction } from "../lib/types";
import { RiskBadge } from "./RiskLevel";

/** SEC-005 restrictions (H5, SEC-19) with manual L1/L2 apply/lift and the bulk false-positive lift. */
export function Restrictions() {
  const toast = useToast();
  const [level, setLevel] = useState("");
  const [family, setFamily] = useState("");
  const [source, setSource] = useState("");
  const [state, setState] = useState("active");
  const [lift, setLift] = useState<Restriction | null>(null);
  const [applyOpen, setApplyOpen] = useState(false);
  const [userId, setUserId] = useState("");
  const [applyLevel, setApplyLevel] = useState("1");
  const [reason, setReason] = useState("");
  // verified: api_review.py list_restrictions accepts only `active` (bool) and `level` (single int), max 200 rows;
  // family / source / state are filtered on the loaded rows.
  const list = useCursorList<Restriction>("security/restrictions", cleanQuery({ level, active: state === "active" || state === "lift_pending" ? "true" : "false" }));
  const rows = list.rows?.filter((r) => (!family || r.family === family) && (!source || r.source === source) && (!state || r.state === state));
  // Family, source and "lift pending" are applied to the loaded page only; say so instead of a false "no match".
  const clientFiltered = !!family || !!source || state === "lift_pending";

  const cols: Column<Restriction>[] = [
    {
      key: "who",
      header: "Account",
      cell: (r) => (
        <Link className={`${textLink} inline-flex min-h-6 items-center`} href={`/security/users/${r.user_id}/timeline`} aria-label={`Security timeline for user ${shortRef(r.user_id)}`}>
          User {shortRef(r.user_id)}
        </Link>
      ),
    },
    { key: "level", header: "Level", cell: (r) => <RiskBadge level={r.level} /> },
    { key: "family", header: "Family", priority: "secondary", cell: (r) => humanize(r.family) },
    { key: "state", header: "State", cell: (r) => <StateBadge state={r.state} /> },
    { key: "since", header: "Since", cell: (r) => formatDateTime(r.starts_at) },
    { key: "ends", header: "Ends", cell: (r) => (r.ends_at ? formatDateTime(r.ends_at) : "—") },
    { key: "deferred", header: "Deferred until", priority: "secondary", cell: (r) => (r.deferred_until ? formatDateTime(r.deferred_until) : "—") },
    { key: "source", header: "Applied by", priority: "secondary", cell: (r) => sourceLabel(r.source) },
    {
      key: "case",
      header: "Case",
      cell: (r) =>
        r.case_id ? (
          <Link className={`${textLink} font-mono`} href={`/security/cases/${r.case_id}`}>
            {r.case_ref ?? "Open"}
          </Link>
        ) : (
          "—"
        ),
    },
    {
      key: "act",
      header: <span className="sr-only">Actions</span>,
      cell: (r) =>
        r.level <= 2 && r.state !== "ended" ? (
          <Button size="sm" variant="secondary" onClick={() => setLift(r)} aria-label={`Lift L${r.level} restriction on user ${shortRef(r.user_id)}`}>
            Lift
          </Button>
        ) : null,
    },
  ];

  return (
    <div>
      <PageHeader
        breadcrumbs={[{ label: "Security", href: "/security" }, { label: "Restrictions" }]}
        title="Restrictions"
        description="Accounts limited by the risk engine or a reviewer. Notices (L1) and verification (L2) can be applied and lifted here; L3/L4 change only through a case decision or an approved bulk lift."
        actions={<Button onClick={() => setApplyOpen(true)}>Apply notice or verification</Button>}
      />
      <FilterBar label="Restriction filters">
        <FormField label="Level">{(f) => <Select {...f} value={level} onChange={(e) => setLevel(e.target.value)} options={LEVEL_OPTIONS.filter((o) => !o.value.includes(","))} />}</FormField>
        <FormField label="Family" hint="Within this page">{(f) => <Select {...f} value={family} onChange={(e) => setFamily(e.target.value)} options={FAMILY_OPTIONS} />}</FormField>
        <FormField label="Applied by" hint="Within this page">
          {(f) => (
            <Select {...f} value={source} onChange={(e) => setSource(e.target.value)} options={SOURCE_OPTIONS} />
          )}
        </FormField>
        <FormField label="State">
          {(f) => (
            <Select
              {...f}
              value={state}
              onChange={(e) => setState(e.target.value)}
              options={[
                { value: "active", label: "Active" },
                { value: "lift_pending", label: "Lift pending" },
                { value: "ended", label: "Ended" },
                { value: "", label: "All" },
              ]}
            />
          )}
        </FormField>
      </FilterBar>
      {clientFiltered ? (
        <p role="status" className="mb-3 text-xs text-fg-muted">
          Family, “Applied by” and “Lift pending” filter only the restrictions loaded on this page. Use Next page to check further results.
        </p>
      ) : null}
      <Table
        caption="Restrictions"
        columns={cols}
        rows={rows}
        rowKey={(r) => r.restriction_id}
        loading={list.loading}
        error={list.error}
        onRetry={() => void list.reload()}
        empty={{ title: clientFiltered ? "No matches on this page" : "No restrictions match these filters", description: clientFiltered ? "Try the next page, or set Family and Applied by to “Any”." : "Try “All” states or “Any level”." }}
        footer={<Pagination hasMore={list.hasMore} hasPrevious={list.hasPrevious} onNext={list.next} onPrevious={list.previous} loading={list.loading} />}
      />

      <BulkLift />

      <ActionDialog
        open={lift !== null}
        onClose={() => setLift(null)}
        onOpen={() => setReason("")}
        title={`Lift L${lift?.level ?? ""} restriction?`}
        description={lift ? `User ${shortRef(lift.user_id)} · applied ${formatDateTime(lift.starts_at)}` : undefined}
        submitLabel="Lift"
        validate={() => (reason.trim().length < 3 ? "Give a reason." : null)}
        onSubmit={async () => toOutcome(await api.post(`security/restrictions/${lift!.restriction_id}/lift`, { reason: reason.trim() }, { idempotencyKey: true }))}
        onDone={() => {
          setReason("");
          toast.show({ title: "Restriction lifted.", tone: "success" });
          void list.reload();
        }}
      >
        <FormField label="Reason" required>
          {(f) => <TextArea {...f} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={1000} />}
        </FormField>
      </ActionDialog>

      <ActionDialog
        open={applyOpen}
        onClose={() => setApplyOpen(false)}
        onOpen={() => {
          setUserId("");
          setApplyLevel("1");
          setReason("");
        }}
        title="Apply a notice or verification"
        description="Temporary restrictions (L3) and suspensions (L4) are applied from a case."
        submitLabel="Apply"
        validate={() => (!userId.trim() ? "Enter the user id." : reason.trim().length < 3 ? "Give a rationale." : null)}
        onSubmit={async () => toOutcome(await api.post("security/restrictions", { user_id: userId.trim(), level: Number(applyLevel), family: "sharing", rationale: reason.trim(), ends_at: null }, { idempotencyKey: true }))}
        onDone={() => {
          setUserId("");
          setReason("");
          void list.reload();
        }}
      >
        <FormField label="User id" required hint="Copy it from the user's page under Admin › Users.">
          {(f) => <Input {...f} className="font-mono" spellCheck={false} value={userId} onChange={(e) => setUserId(e.target.value)} />}
        </FormField>
        <FormField label="Level" required>
          {(f) => (
            <Select
              {...f}
              value={applyLevel}
              onChange={(e) => setApplyLevel(e.target.value)}
              options={[
                { value: "1", label: "L1 · Notice" },
                { value: "2", label: "L2 · Verify" },
              ]}
            />
          )}
        </FormField>
        <FormField label="Rationale" required>
          {(f) => <TextArea {...f} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={4000} />}
        </FormField>
      </ActionDialog>
    </div>
  );
}

/** Bulk-lift selector fields in words. */
const SELECTOR_LABELS: Record<string, string> = {
  ruleset_version: "Ruleset version",
  rule_key: "Rule",
  applied_from: "Applied from",
  applied_to: "Applied to",
  network_cidr: "Network",
  asn: "Network operator (ASN)",
};

/** verified: app/modules/security/controls.py bulk_lift_request (dry run, 200). */
interface DryRunResult {
  matched: number;
  excluded_by_reason?: Record<string, number>;
  sample?: Record<string, unknown>[];
}

/**
 * Bulk false-positive lift (SEC-44, RE §5.8). Dry run first; execution is Dual
 * (`security.restriction.bulk_lift`) and returns 202 approval_pending.
 */
export function BulkLift() {
  const [ruleset, setRuleset] = useState("");
  const [rule, setRule] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [reason, setReason] = useState("");
  const [credit, setCredit] = useState(true);
  const [dry, setDry] = useState<DryRunResult | null>(null);
  const [pending, setPending] = useState<ApprovalPending | null>(null);
  const [bulkId, setBulkId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const selector = {
    ruleset_version: ruleset.trim() || null,
    rule_key: rule.trim() || null,
    applied_from: from ? new Date(`${from}T00:00:00+05:30`).toISOString() : null,
    applied_to: to ? new Date(`${to}T00:00:00+05:30`).toISOString() : null,
    network_cidr: null,
    asn: null,
  };

  const run = async (dryRun: boolean) => {
    if (reason.trim().length < 10) {
      setError(new Error("reason"));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await api.post<DryRunResult>("security/restrictions/bulk-lift-requests", { selector, dry_run: dryRun, reason: reason.trim(), extension_credit: credit }, { idempotencyKey: true });
      if (res.kind === "approval_pending") {
        setPending(res.approval);
        // verified: controls.py bulk_lift_request 202 = {...pending_response, bulk_lift_id, matched}.
        const id = (res.approval as ApprovalPending & { bulk_lift_id?: unknown }).bulk_lift_id;
        if (typeof id === "string") setBulkId(id);
      } else if (dryRun) setDry(res.data);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="Bulk false-positive lift" className="mt-6">
      <p className="mb-3 text-sm text-fg-muted">
        Lifts many wrong temporary restrictions at once, e.g. after a rule misfired. Only restrictions the risk engine applied (L3) match; suspensions, high-risk, takeover and reviewer-applied restrictions are always left alone. Up to 5,000 per request. Check the matches first; a second approver must agree.
      </p>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <FormField label="Ruleset version">{(f) => <Input {...f} value={ruleset} onChange={(e) => setRuleset(e.target.value)} placeholder="2.1.0" />}</FormField>
        <FormField label="Rule key" hint="e.g. HC-01">{(f) => <Input {...f} value={rule} onChange={(e) => setRule(e.target.value)} placeholder="HC-01" />}</FormField>
        <FormField label="Applied from">{(f) => <Input {...f} type="date" value={from} onChange={(e) => setFrom(e.target.value)} />}</FormField>
        <FormField label="Applied to">{(f) => <Input {...f} type="date" value={to} onChange={(e) => setTo(e.target.value)} />}</FormField>
      </div>
      <div className="mt-3 space-y-3">
        <FormField label="Reason" required error={error instanceof Error && error.message === "reason" ? "Describe the false-positive event (10+ characters)." : undefined}>
          {(f) => <TextArea {...f} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={1000} />}
        </FormField>
        <Checkbox label="Credit the restricted days (extension credit)" checked={credit} onChange={(e) => setCredit(e.target.checked)} />
        {error && !(error instanceof Error && error.message === "reason") ? <InlineProblem error={error} /> : null}
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" loading={busy} onClick={() => void run(true)}>
            Check matches (dry run)
          </Button>
          <Button loading={busy} disabled={!dry || dry.matched === 0 || !!pending} onClick={() => void run(false)}>
            Request bulk lift
          </Button>
        </div>
        {dry ? (
          <div className="space-y-2" role="status">
            <KeyValueList
              items={[
                { label: "Matched", value: dry.matched.toLocaleString("en-IN") },
                ...Object.entries(dry.excluded_by_reason ?? {}).map(([k, v]) => ({ label: `Excluded: ${humanize(k)}`, value: v.toLocaleString("en-IN") })),
              ]}
            />
            {dry.sample?.length ? (
              <details>
                <summary className="inline-flex min-h-6 cursor-pointer items-center text-sm font-medium text-fg-secondary hover:text-fg focus-visible:shadow-focus focus-visible:outline-none">
                  Sample of matched restrictions ({Math.min(dry.sample.length, 50)}, personal data masked)
                </summary>
                <div className="mt-2">
                  <ValueSummary label="Sample (masked)" value={dry.sample.slice(0, 50)} />
                </div>
              </details>
            ) : null}
          </div>
        ) : null}
        {pending ? <ApprovalPendingNotice approval={pending} /> : null}
      </div>
      <BulkLiftStatus key={bulkId ?? "none"} initialId={bulkId} />
    </Card>
  );
}

/**
 * ADM-11: bulk-lift status (`GET /security/restrictions/bulk-lift-requests/{id}`). Shows the request
 * made here, or any bulk lift by id (there is no list endpoint).
 */
export function BulkLiftStatus({ initialId }: { initialId: string | null }) {
  const [id, setId] = useState(initialId ?? "");
  const [data, setData] = useState<BulkLiftStatusData | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const check = useCallback(async (value: string) => {
    const v = value.trim();
    if (!v) return;
    setBusy(true);
    setError(null);
    try {
      setData(await api.get<BulkLiftStatusData>(`security/restrictions/bulk-lift-requests/${encodeURIComponent(v)}`));
    } catch (err) {
      setData(null);
      setError(err);
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    if (initialId) void check(initialId);
  }, [initialId, check]);

  return (
    <section aria-labelledby="bulk-status-h" className="mt-6 border-t border-line pt-4">
      <h3 id="bulk-status-h" className="mb-2 font-display text-sm font-semibold text-fg">
        Bulk-lift status
      </h3>
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void check(id);
        }}
      >
        <FormField label="Bulk lift id">{(f) => <Input {...f} className="font-mono" value={id} onChange={(e) => setId(e.target.value)} />}</FormField>
        <Button type="submit" variant="secondary" loading={busy} disabled={!id.trim()}>
          Check status
        </Button>
      </form>
      <div className="mt-3 space-y-2">
        <InlineProblem error={error} />
        {data ? (
          <div role="status" className="space-y-2">
            <KeyValueList
              items={[
                { label: "Status", value: <StateBadge state={data.status} /> },
                { label: "Matched", value: data.matched.toLocaleString("en-IN") },
                ...Object.entries(data.progress ?? {}).map(([k, v]) => ({ label: humanize(k), value: typeof v === "number" ? v.toLocaleString("en-IN") : String(v ?? "—") })),
                { label: "Approval request", value: data.approval_request_id ? shortRef(data.approval_request_id) : "—" },
              ]}
            />
            <h4 className="text-xs font-semibold uppercase tracking-wide text-fg-muted">Which restrictions it covers</h4>
            <ValueSummary label="Selector" value={data.selector} labels={SELECTOR_LABELS} />
          </div>
        ) : null}
      </div>
    </section>
  );
}
