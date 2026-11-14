"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Badge, Button, Card, EmptyState, ErrorState, FormField, Select, LoadingBlock, Table, type Column } from "@/components/ui";
import { api } from "@/lib/api/client";
import { ActionDialog, ConfirmDialog, InlineProblem, KeyValueList, StateBadge, TextArea, ValueSummary } from "@/features/admin/components/console-ui";
import { cellText, formatDateTime, humanize, ifMatchFor, toOutcome, useVersioned, type Query } from "@/features/admin/lib/console";
import { INFO_TEMPLATES_FALLBACK } from "../lib/catalogue";
import { staffRef } from "../lib/ids";
import { outcomeLabel } from "./DecisionPanel";
import type { CaseDetail, CaseExplanation, Concurrency, ContributingSignal, DeviceGraph, ReviewUnblockDetail, ReviewUnblockRow, Timeline, TimelineEvent } from "../lib/types";

export interface EvidenceContext {
  reasonCode: string;
  caseRef: string;
}

function Loading({ label }: { label: string }) {
  return <LoadingBlock label={label} rows={2} size="card" />;
}

const isScalarValue = (v: unknown) => v === null || v === undefined || typeof v !== "object";

/**
 * Evidence attached to a signal or timeline event, in words: simple fields inline
 * ("Devices: 2 · Network: 49.36.112.0/24"), nested data behind "More detail" (audit 1.11).
 */
export function EvidenceSummary({ evidence }: { evidence: unknown }) {
  if (!evidence || typeof evidence !== "object") return evidence === null || evidence === undefined ? <span className="text-fg-muted">—</span> : <>{cellText(evidence)}</>;
  const entries = Array.isArray(evidence) ? [] : Object.entries(evidence as Record<string, unknown>);
  const simple = entries.filter(([, v]) => isScalarValue(v) && v !== null && v !== "");
  const nested = Array.isArray(evidence) || entries.some(([, v]) => !isScalarValue(v));
  return (
    <div className="space-y-1 text-xs text-fg-secondary">
      {simple.length ? <p>{simple.map(([k, v]) => `${humanize(k)}: ${cellText(v)}`).join(" · ")}</p> : null}
      {nested ? (
        <details>
          <summary className="inline-flex min-h-6 cursor-pointer items-center font-medium text-fg-secondary hover:text-fg focus-visible:shadow-focus focus-visible:outline-none">More detail</summary>
          <div className="mt-1">
            <ValueSummary label="Evidence" value={evidence} />
          </div>
        </details>
      ) : null}
    </div>
  );
}

/** Calls `onLoaded` once after the first successful load (used for "opened before deciding"). */
function useOnce(flag: boolean, cb: () => void) {
  const done = useRef(false);
  const fn = useRef(cb);
  fn.current = cb;
  useEffect(() => {
    if (flag && !done.current) {
      done.current = true;
      fn.current();
    }
  }, [flag]);
}

/* ------------------------------------------------------------ Explanation */

/** SEC-07: score breakdown + contributing signals (rule id + version) + student preview. */
export function ExplanationTab({ caseId, ctx, onViewed }: { caseId: string; ctx: EvidenceContext; onViewed: () => void }) {
  const q = useMemo(() => ({ reason_code: ctx.reasonCode }), [ctx]);
  const res = useVersioned<CaseExplanation>(`security/cases/${caseId}/explanation`, q);
  useOnce(!!res.data, onViewed);
  if (res.error) return <ErrorState error={res.error} onRetry={() => void res.reload()} />;
  if (!res.data) return <Loading label="Loading explanation…" />;
  const e = res.data;
  const ev = e.evaluation;
  const signalCols: Column<ContributingSignal>[] = [
    { key: "rule", header: "Rule", cell: (s) => <span className="font-mono">{s.rule}</span> },
    { key: "ver", header: "Version", cell: (s) => (s.rule_version ? <span className="font-mono">v{s.rule_version}</span> : "—") },
    { key: "cat", header: "Category", cell: (s) => s.category ?? "—" },
    { key: "pts", header: "Points", align: "right", cell: (s) => cellText(s.base_points) },
    { key: "dec", header: "Decayed", align: "right", cell: (s) => cellText(s.decayed_points) },
    { key: "ev", header: "Evidence", cell: (s) => (s.evidence ? <EvidenceSummary evidence={s.evidence} /> : "—") },
  ];
  const subtotals = Object.entries(ev?.subtotals ?? {});
  return (
    <div className="space-y-4">
      <KeyValueList
        items={[
          { label: "Ruleset version", value: ev?.ruleset_version ? <span className="font-mono">v{ev.ruleset_version}</span> : "—" },
          { label: "Score", value: typeof ev?.score === "number" ? ev.score.toFixed(1) : "—" },
          { label: "Level", value: ev ? `L${ev.level_before} → L${ev.level_after}` : "—" },
          { label: "High-confidence rule", value: e.hc_rule ?? "None" },
        ]}
      />
      {!ev ? <p className="text-sm text-fg-muted">No risk evaluation is linked to this case.</p> : null}
      {subtotals.length ? (
        <div>
          <h3 className="text-sm font-semibold text-fg">Category breakdown</h3>
          <ul className="mt-1 flex flex-wrap gap-2 text-sm">
            {subtotals.map(([category, points]) => (
              <li key={category} className="rounded-md border border-line px-2 py-1">
                {humanize(category)} <span className="font-semibold tabular-nums">{cellText(points)}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <Table caption="Contributing signals" showCaption columns={signalCols} rows={ev?.signals ?? []} rowKey={(s) => `${s.signal_id ?? s.rule}-${s.occurred_at ?? ""}`} empty={{ title: "No contributing signals returned" }} />
      {e.student_explanation_preview?.length ? (
        <div className="rounded-lg border border-line bg-surface-subtle p-3 text-sm">
          <p className="font-semibold text-fg">The student sees</p>
          <ul className="mt-1 list-disc pl-5 text-fg-secondary">
            {e.student_explanation_preview.map((x, i) => (
              <li key={`${i}-${x}`}>{x}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

/* -------------------------------------------------------------- Reveal IP */

/** verified: api_review.py RevealIn {evidence_ref, field, reason_code, case_ref} → pii_reveal {field, value, revealed_at}. */
interface RevealResult {
  field: string;
  value: string;
  revealed_at: string;
}

function RevealIp({ evidenceRef, ctx }: { evidenceRef: string; ctx: EvidenceContext }) {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState<string | null>(null);
  if (value) return <span className="select-all font-mono text-xs">{value}</span>;
  return (
    <>
      <Button size="sm" variant="ghost" onClick={() => setOpen(true)} aria-label={`Reveal full IP for ${evidenceRef}`}>
        Reveal full IP
      </Button>
      <ActionDialog<RevealResult>
        open={open}
        onClose={() => setOpen(false)}
        title="Reveal full IP"
        description={`Each reveal is recorded in the audit log (reason: ${humanize(ctx.reasonCode)}, case ${ctx.caseRef}) and included in the QA sample.`}
        submitLabel="Reveal"
        onSubmit={async () => toOutcome(await api.post<RevealResult>("security/pii-reveals", { evidence_ref: evidenceRef, field: "ip", reason_code: ctx.reasonCode, case_ref: ctx.caseRef }, { idempotencyKey: true }))}
        onDone={(o) => {
          if (o.kind === "ok") setValue(o.data.value);
        }}
      />
    </>
  );
}

/* --------------------------------------------------------------- Timeline */

/** verified: app/modules/security/timeline.py timeline (`want` types). */
const TIMELINE_TYPES = ["login", "session", "network", "cap", "signal", "evaluation", "restriction", "otp", "case"];

function eventSummary(e: TimelineEvent): string {
  const skip = new Set(["at", "type", "evidence", "evidence_ref", "session_id", "evaluation_id"]);
  return Object.entries(e)
    .filter(([k, v]) => !skip.has(k) && v !== null && v !== undefined && v !== "" && (typeof v !== "object" || Array.isArray(v)))
    .map(([k, v]) => `${humanize(k)}: ${cellText(v)}`)
    .join(" · ");
}

/** SEC-13 (H12) timeline: logins, sessions (/24 nets), caps, signals, evaluations, OTP, case events. */
export function TimelineTab({ userId, ctx, onViewed }: { userId: string; ctx: EvidenceContext; onViewed?: () => void }) {
  const [type, setType] = useState("");
  const query: Query = useMemo(() => ({ reason_code: ctx.reasonCode, case_ref: ctx.caseRef || undefined, types: type || TIMELINE_TYPES.join(",") }), [ctx, type]);
  const res = useVersioned<Timeline>(`security/users/${userId}/timeline`, query);
  useOnce(!!res.data, () => onViewed?.());
  const cols: Column<TimelineEvent>[] = [
    { key: "at", header: "When", cell: (e) => <span className="whitespace-nowrap">{formatDateTime(e.at)}</span> },
    { key: "type", header: "Type", cell: (e) => <Badge tone={e.type === "signal" ? "warning" : e.type === "restriction" ? "info" : "neutral"}>{humanize(e.type)}</Badge> },
    {
      key: "what",
      header: "Details",
      cell: (e) => (
        <div className="space-y-1">
          <p className="text-xs text-fg-secondary">{eventSummary(e) || "—"}</p>
          {e.evidence && typeof e.evidence === "object" ? <EvidenceSummary evidence={e.evidence} /> : null}
        </div>
      ),
    },
    { key: "ip", header: "Network", cell: (e) => (typeof e.evidence_ref === "string" && ctx.caseRef ? <RevealIp evidenceRef={e.evidence_ref} ctx={ctx} /> : <span className="text-xs text-fg-muted">masked</span>) },
  ];
  return (
    <div className="space-y-3">
      {res.data?.subject?.is_minor ? (
        <p className="rounded-md border border-line bg-surface-subtle p-2 text-sm text-fg-secondary">Minor account: only deterministic cap and takeover events exist — by design.</p>
      ) : null}
      <div className="max-w-xs">
        <FormField label="Event type">
          {(f) => <Select {...f} value={type} onChange={(e) => setType(e.target.value)} options={[{ value: "", label: "All types" }, ...TIMELINE_TYPES.map((t) => ({ value: t, label: humanize(t) }))]} />}
        </FormField>
      </div>
      <Table caption="User security timeline" columns={cols} rows={res.data?.events} rowKey={(e) => `${e.at}-${e.type}-${String(e.session_id ?? e.rule ?? e.evidence_ref ?? e.evaluation_id ?? "")}`} loading={res.loading} error={res.error} onRetry={() => void res.reload()} empty={{ title: "No events in this period", description: "Try “All types”, or check the account's devices from the case." }} />
      {res.data?.page.has_more ? <p className="text-xs text-fg-muted">Showing the first 200 events of the last 30 days.</p> : null}
      <p className="text-xs text-fg-muted">IP addresses are shown as /24 (IPv4) or /48 (IPv6) networks. Full values are revealed one at a time and audited.</p>
    </div>
  );
}

/* ------------------------------------------------------------ Concurrency */

const MINOR_NOTICE = "No behavioural data for minor accounts — by design.";
const BUCKET_MS = 5 * 60_000;

function dayRange(days: number): { from: string; to: string } {
  const to = new Date();
  const from = new Date(to.getTime() - days * 86_400_000);
  return { from: from.toISOString(), to: to.toISOString() };
}

/** Overlaps are derived client-side: the same 5-minute engaged bucket on two or more devices. */
export function deriveOverlaps(buckets: Concurrency["buckets"]): { start: string; devices: string[] }[] {
  const byBucket = new Map<string, Set<string>>();
  for (const b of buckets) {
    const set = byBucket.get(b.bucket) ?? new Set<string>();
    set.add(b.device_id);
    byBucket.set(b.bucket, set);
  }
  return [...byBucket.entries()]
    .filter(([, d]) => d.size > 1)
    .map(([start, d]) => ({ start, devices: [...d] }))
    .sort((a, b) => Date.parse(a.start) - Date.parse(b.start));
}

/** SEC-14 (H3): engaged 5-minute buckets per device, with overlapping buckets highlighted. */
export function ConcurrencyTab({ userId, ctx, isMinor }: { userId: string; ctx: EvidenceContext; isMinor?: boolean }) {
  const [days, setDays] = useState("7");
  const query = useMemo(() => ({ reason_code: ctx.reasonCode, ...dayRange(Number(days)) }), [ctx, days]);
  const res = useVersioned<Concurrency>(isMinor ? null : `security/users/${userId}/concurrency`, query);
  if (isMinor) return <EmptyState variant="inline" icon="lock" title="Not available" description={MINOR_NOTICE} />;
  if (res.error) return <ErrorState error={res.error} onRetry={() => void res.reload()} />;
  if (!res.data) return <Loading label="Loading concurrency…" />;
  const c = res.data;
  if (!c.available) return <EmptyState variant="inline" icon="chart" title="Not available yet" description="Engaged-bucket data is not available from the api in this environment." />;
  const byDevice = new Map<string, number[]>();
  for (const b of c.buckets) byDevice.set(b.device_id, [...(byDevice.get(b.device_id) ?? []), Date.parse(b.bucket)]);
  const devices = [...byDevice.entries()];
  const overlaps = deriveOverlaps(c.buckets);
  const all = c.buckets.map((b) => Date.parse(b.bucket));
  const min = all.length ? Math.min(...all) : 0;
  const max = all.length ? Math.max(...all) + BUCKET_MS : 1;
  const pct = (t: number) => `${(((t - min) / Math.max(1, max - min)) * 100).toFixed(2)}%`;
  const width = (t: number) => `max(2px, calc(${pct(t + BUCKET_MS)} - ${pct(t)}))`;
  const overlapCols: Column<(typeof overlaps)[number]>[] = [
    { key: "start", header: "Start", cell: (o) => formatDateTime(o.start) },
    { key: "end", header: "End", cell: (o) => formatDateTime(new Date(Date.parse(o.start) + BUCKET_MS).toISOString()) },
    { key: "dev", header: "Devices", cell: (o) => <span className="font-mono text-xs">{o.devices.join(" + ")}</span> },
  ];
  return (
    <div className="space-y-4">
      <div className="max-w-xs">
        <FormField label="Period" hint="Maximum 14 days per request">
          {(f) => (
            <Select
              {...f}
              value={days}
              onChange={(e) => setDays(e.target.value)}
              options={[
                { value: "1", label: "Last 24 hours" },
                { value: "3", label: "Last 3 days" },
                { value: "7", label: "Last 7 days" },
                { value: "14", label: "Last 14 days" },
              ]}
            />
          )}
        </FormField>
      </div>
      {devices.length ? (
        <div aria-hidden="true" className="space-y-2 rounded-lg border border-line p-3">
          {devices.map(([deviceId, starts]) => (
            <div key={deviceId} className="flex items-center gap-2">
              <span className="w-40 shrink-0 truncate font-mono text-xs text-fg-secondary">{deviceId}</span>
              <div className="relative h-4 flex-1 rounded bg-surface-sunken">
                {starts.map((t) => (
                  <span key={t} className="absolute inset-y-0 rounded-sm bg-chart-1" style={{ left: pct(t), width: width(t) }} />
                ))}
                {overlaps.map((o) => (
                  <span key={`o-${o.start}`} className="absolute inset-y-0 border-x-2 border-warning-solid bg-warning-subtle/60" style={{ left: pct(Date.parse(o.start)), width: width(Date.parse(o.start)) }} />
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : null}
      <Table caption="Overlapping engaged use" showCaption columns={overlapCols} rows={overlaps} rowKey={(o) => o.start} empty={{ title: "No overlapping use in this period" }} />
      <p className="text-xs text-fg-muted">Separation class, networks and session-cap hits per overlap are not available yet from the api.</p>
    </div>
  );
}

/* ------------------------------------------------------------ Device graph */

/**
 * SEC-15 (H2): device ↔ account graph. A simple radial SVG (decorative summary) plus an
 * accessible table that carries all of the information. Linked accounts stay masked.
 */
export function DeviceGraphTab({ userId, ctx, isMinor }: { userId: string; ctx: EvidenceContext; isMinor?: boolean }) {
  const [hops, setHops] = useState("1");
  const [days, setDays] = useState("30");
  const query = useMemo(() => ({ reason_code: ctx.reasonCode, hops, days }), [ctx, hops, days]);
  const res = useVersioned<DeviceGraph>(isMinor ? null : `security/users/${userId}/device-graph`, query);
  if (isMinor) return <EmptyState variant="inline" icon="lock" title="Not available" description={MINOR_NOTICE} />;
  if (res.error) return <ErrorState error={res.error} onRetry={() => void res.reload()} />;
  if (!res.data) return <Loading label="Loading device graph…" />;
  const g = res.data;
  // The api omits the subject's own node; edges reference it as `acct_<first 8 chars of the user id>`.
  const subjectId = `acct_${g.subject.slice(0, 8)}`;
  const byId = new Map(g.nodes.map((n) => [n.id, n]));
  const devices = g.nodes.filter((n) => n.type === "device");
  const others = g.nodes.filter((n) => n.type === "account" && n.id !== subjectId);
  const W = 520;
  const H = 320;
  const cx = W / 2;
  const cy = H / 2;
  const pos = new Map<string, { x: number; y: number }>();
  pos.set(subjectId, { x: cx, y: cy });
  devices.forEach((d, i) => {
    const a = (2 * Math.PI * i) / Math.max(1, devices.length);
    pos.set(d.id, { x: cx + 90 * Math.cos(a), y: cy + 90 * Math.sin(a) });
  });
  others.forEach((o, i) => {
    const a = (2 * Math.PI * i) / Math.max(1, others.length) + 0.3;
    pos.set(o.id, { x: cx + 145 * Math.cos(a), y: cy + 130 * Math.sin(a) });
  });
  const deviceNode = (id: string) => {
    const n = byId.get(id);
    return n?.type === "device" ? n : undefined;
  };
  const rows = g.edges.map((e) => ({ ...e, key: `${e.device}-${e.account}` }));
  const cols: Column<(typeof rows)[number]>[] = [
    { key: "device", header: "Device", cell: (e) => deviceNode(e.device)?.label ?? <span className="font-mono text-xs">{e.device}</span> },
    { key: "account", header: "Account", cell: (e) => (e.account === subjectId ? "This user" : <span className="font-mono">{e.account} (masked)</span>) },
    {
      key: "restricted",
      header: "Linked account at L3+",
      cell: (e) => {
        if (e.account === subjectId) return "—";
        const n = byId.get(e.account);
        return n?.type === "account" ? n.restricted ? <Badge tone="warning">Yes</Badge> : "No" : "—";
      },
    },
  ];
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-3">
        <div className="w-40">
          <FormField label="Hops">{(f) => <Select {...f} value={hops} onChange={(e) => setHops(e.target.value)} options={[{ value: "1", label: "1 hop" }, { value: "2", label: "2 hops" }]} />}</FormField>
        </div>
        <div className="w-40">
          <FormField label="Period">{(f) => <Select {...f} value={days} onChange={(e) => setDays(e.target.value)} options={[{ value: "30", label: "30 days" }, { value: "90", label: "90 days" }]} />}</FormField>
        </div>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Device–account graph: ${devices.length} devices, ${others.length} other accounts. Details in the table below.`} className="h-auto w-full max-w-xl rounded-lg border border-line bg-surface">
        {g.edges.map((e) => {
          const a = pos.get(e.device);
          const b = pos.get(e.account);
          return a && b ? <line key={`${e.device}-${e.account}`} x1={a.x} y1={a.y} x2={b.x} y2={b.y} className="stroke-chart-axis" strokeWidth={1.5} /> : null;
        })}
        <circle cx={cx} cy={cy} r={13} className="fill-chart-1" />
        <text x={cx} y={cy + 24} textAnchor="middle" className="fill-fg text-[10px]">
          This user
        </text>
        {g.nodes.map((n) => {
          const p = pos.get(n.id);
          if (!p || n.id === subjectId) return null;
          return (
            <g key={n.id}>
              {n.type === "device" ? (
                <rect x={p.x - 9} y={p.y - 9} width={18} height={18} rx={3} className="fill-chart-2" />
              ) : (
                <circle cx={p.x} cy={p.y} r={10} className="fill-surface-sunken stroke-chart-axis" />
              )}
              <text x={p.x} y={p.y + 24} textAnchor="middle" className="fill-fg text-[10px]">
                {(n.type === "device" ? (n.label ?? n.id) : "•••").slice(0, 18)}
                {n.type === "account" && n.restricted ? " L3+" : ""}
              </text>
            </g>
          );
        })}
      </svg>
      <p className="text-xs text-fg-muted">Circles are accounts (filled = this user), squares are devices. Linked accounts stay masked.</p>
      <Table caption="Device–account associations" showCaption columns={cols} rows={rows} rowKey={(r) => r.key} empty={{ title: "No shared devices found" }} />
    </div>
  );
}

/* ------------------------------------------------------------- Submission */

const ALL_UNBLOCK_STATES = "draft,submitted,under_review,info_requested,escalated,approved,rejected,closed";

/** verified: api_review.py review_queue → {data, meta: {info_templates: {key: student text}}, page}. */
interface ReviewQueueEnvelope {
  data: ReviewUnblockRow[];
  meta?: { info_templates?: Record<string, string> };
}

/**
 * UNB-11 student submission + reviewer actions (UNB-13 request info, UNB-14 escalate). The case
 * exposes only the request reference, so the request id is resolved through the review queue.
 */
export function SubmissionTab({ reference, ctx, onChanged }: { reference: string | null | undefined; ctx: EvidenceContext; onChanged: () => void }) {
  const queue = useVersioned<ReviewQueueEnvelope>(reference ? "security/review/unblock-requests" : null, { state: ALL_UNBLOCK_STATES });
  const row = queue.data?.data.find((r) => r.reference === reference && (!r.case_ref || r.case_ref === ctx.caseRef));
  const requestId = row?.request_id;
  const res = useVersioned<ReviewUnblockDetail>(requestId ? `security/review/unblock-requests/${requestId}` : null, { reason_code: ctx.reasonCode });
  const [dialog, setDialog] = useState<"info" | "escalate" | null>(null);
  const [template, setTemplate] = useState(INFO_TEMPLATES_FALLBACK[0]!.key);
  const [message, setMessage] = useState("");
  if (!reference) return <EmptyState variant="inline" icon="document" title="No unblock request" description="The student has not submitted a request for this case." />;
  if (queue.error) return <ErrorState error={queue.error} onRetry={() => void queue.reload()} />;
  if (!queue.data) return <Loading label="Loading submission…" />;
  if (!requestId) return <EmptyState variant="inline" icon="search" title="Request not found" description={`Request ${reference} is not in the review queue.`} />;
  if (res.error) return <ErrorState error={res.error} onRetry={() => void res.reload()} />;
  if (!res.data) return <Loading label="Loading submission…" />;
  const r = res.data;
  const apiTemplates = queue.data.meta?.info_templates;
  const templates = apiTemplates ? Object.keys(apiTemplates).map((key) => ({ key, label: INFO_TEMPLATES_FALLBACK.find((t) => t.key === key)?.label ?? humanize(key) })) : INFO_TEMPLATES_FALLBACK;
  const ifMatch = ifMatchFor(res.etag, r.version);
  const done = () => {
    setMessage("");
    void res.reload();
    void queue.reload();
    onChanged();
  };
  return (
    <div className="space-y-4">
      <KeyValueList
        items={[
          { label: "Reference", value: <span className="font-mono">{r.reference}</span> },
          { label: "State", value: <StateBadge state={r.state} label={r.state_label} /> },
          { label: "Submitted", value: formatDateTime(r.submitted_at) },
          { label: "Preferred contact", value: humanize(r.preferred_contact) },
          { label: "What happened", value: r.what_happened?.map(humanize).join(", ") || "—" },
          { label: "Second-level appeal", value: r.is_second_level_appeal ? "Yes" : "No" },
        ]}
      />
      {r.explanation ? <blockquote className="whitespace-pre-wrap rounded-md border-l-4 border-line-strong bg-surface-subtle p-3 text-sm text-fg">{r.explanation}</blockquote> : null}
      {r.recognised_device_ids.length || r.unrecognised_device_ids.length ? (
        <ul aria-label="Devices the student identified" className="space-y-1 text-sm">
          {r.recognised_device_ids.map((d) => (
            <li key={`r-${d}`}>
              <span aria-hidden="true">✓ </span>
              <span className="font-mono">{d}</span> — recognised
            </li>
          ))}
          {r.unrecognised_device_ids.map((d) => (
            <li key={`u-${d}`}>
              <span aria-hidden="true">✗ </span>
              <span className="font-mono">{d}</span> — not recognised
            </li>
          ))}
        </ul>
      ) : null}
      {r.attachments?.length ? <p className="text-sm text-fg-secondary">Attachments: {r.attachments.length} (viewer not available yet)</p> : null}
      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" onClick={() => setDialog("info")} disabled={r.state !== "under_review"}>
          Request information
        </Button>
        <Button variant="secondary" onClick={() => setDialog("escalate")} disabled={!["under_review", "submitted"].includes(r.state)}>
          Escalate
        </Button>
      </div>
      <ActionDialog
        open={dialog === "info"}
        onClose={() => setDialog(null)}
        onOpen={() => {
          setMessage("");
          setTemplate(templates[0]?.key ?? INFO_TEMPLATES_FALLBACK[0]!.key);
        }}
        title="Request more information"
        description="The SLA clock pauses. Reminders go out after 72 h and 6 days; the request closes after 7 days without a reply."
        submitLabel="Send request"
        validate={() => (template === "other" && message.trim().length < 10 ? "Write the question for the student." : null)}
        onSubmit={async () => toOutcome(await api.post(`security/review/unblock-requests/${requestId}/request-info`, { template_key: template, message: message.trim() || undefined }, { ifMatch }))}
        onDone={done}
      >
        <FormField label="Question template" required>
          {(f) => <Select {...f} value={template} onChange={(e) => setTemplate(e.target.value)} options={templates.map((t) => ({ value: t.key, label: t.label }))} />}
        </FormField>
        <FormField label="Message to the student" hint="Never ask for passwords, OTPs, Aadhaar, PAN or payment details.">
          {(f) => <TextArea {...f} value={message} onChange={(e) => setMessage(e.target.value)} maxLength={1000} />}
        </FormField>
      </ActionDialog>
      <ActionDialog
        open={dialog === "escalate"}
        onClose={() => setDialog(null)}
        onOpen={() => setMessage("")}
        title="Escalate to a senior reviewer"
        submitLabel="Escalate"
        validate={() => (message.trim().length < 3 ? "Add a reason for the senior reviewer." : null)}
        onSubmit={async () => toOutcome(await api.post(`security/review/unblock-requests/${requestId}/escalate`, { reason: message.trim() }, { ifMatch }))}
        onDone={done}
      >
        <FormField label="Reason" required>
          {(f) => <TextArea {...f} value={message} onChange={(e) => setMessage(e.target.value)} maxLength={1000} />}
        </FormField>
      </ActionDialog>
    </div>
  );
}

/* ---------------------------------------------------------------- History */

interface PriorCase {
  caseRef: string;
  openedAt: string | null;
  openedReason: string | null;
  outcomes: { at: string; outcome: string }[];
}

/** Groups SEC-13 `case` events (timeline.py: opened / decision per case, all time) into one row per other case. */
export function priorCasesFrom(events: TimelineEvent[], currentRef: string): PriorCase[] {
  const by = new Map<string, PriorCase>();
  for (const e of events) {
    if (e.type !== "case" || typeof e.case_ref !== "string" || e.case_ref === currentRef) continue;
    const c = by.get(e.case_ref) ?? { caseRef: e.case_ref, openedAt: null, openedReason: null, outcomes: [] };
    if (e.event === "opened") {
      c.openedAt = e.at;
      c.openedReason = typeof e.opened_reason === "string" ? e.opened_reason : null;
    } else if (e.event === "decision" && typeof e.outcome === "string") c.outcomes.push({ at: e.at, outcome: e.outcome });
    by.set(e.case_ref, c);
  }
  return [...by.values()].sort((a, b) => (b.openedAt ?? "").localeCompare(a.openedAt ?? ""));
}

/** Previous incidents = the subject's other security cases, from the audited SEC-13 timeline (`types=case`). */
function PreviousIncidents({ userId, ctx, detail }: { userId: string; ctx: EvidenceContext; detail: CaseDetail }) {
  const query: Query = useMemo(() => ({ reason_code: ctx.reasonCode, types: "case" }), [ctx.reasonCode]);
  const res = useVersioned<Timeline>(`security/users/${userId}/timeline`, query);
  if (res.error) return <ErrorState error={res.error} title="Could not load previous incidents" onRetry={() => void res.reload()} />;
  if (!res.data) return <Loading label="Loading previous incidents" />;
  const prior = priorCasesFrom(res.data.events, detail.case_ref);
  return (
    <div className="space-y-2 text-sm">
      {detail.repeat_count ? <p className="text-fg-muted">Repeat count: {detail.repeat_count}.</p> : null}
      {prior.length ? (
        <ul className="space-y-2">
          {prior.map((c) => (
            <li key={c.caseRef}>
              <span className="font-mono">{c.caseRef}</span> · opened {formatDateTime(c.openedAt)}
              {c.openedReason ? ` (${humanize(c.openedReason)})` : ""}
              {c.outcomes.length ? ` · ${c.outcomes.map((o) => `${humanize(o.outcome)} ${formatDateTime(o.at)}`).join("; ")}` : " · no decision"}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-fg-muted">No other security cases for this account.</p>
      )}
    </div>
  );
}

export function HistoryTab({ detail, userId, ctx }: { detail: CaseDetail; userId?: string | null; ctx?: EvidenceContext }) {
  return (
    <div className="space-y-4">
      <Card title="Previous incidents">
        {userId && ctx ? <PreviousIncidents userId={userId} ctx={ctx} detail={detail} /> : <p className="text-sm text-fg-muted">The subject is not available for this case.</p>}
      </Card>
      <Card title="Decisions">
        {detail.decisions?.length ? (
          <ul className="space-y-2 text-sm">
            {detail.decisions.map((d) => (
              <li key={d.decision_id}>
                <span className="font-semibold">{outcomeLabel(d.outcome)}</span> · {formatDateTime(d.at)} · by {staffRef(d.decided_by, "Reviewer")}
                {d.approved_by ? (
                  <>
                    {" "}
                    · approved by {staffRef(d.approved_by, "Reviewer")}
                  </>
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-fg-muted">No final decisions yet.</p>
        )}
      </Card>
    </div>
  );
}

/* ------------------------------------------------------------------ Notes */

/** Internal and student-visible notes (SEC-08: ≤ 4,000 characters; visibility "internal" | "student"). */
export function NotesTab({ caseId, notes, onAdded }: { caseId: string; notes: CaseDetail["notes"]; onAdded: () => void }) {
  const [body, setBody] = useState("");
  const [visibility, setVisibility] = useState("internal");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [confirmStudent, setConfirmStudent] = useState(false);
  const post = async () => {
    await api.post(`security/cases/${caseId}/notes`, { visibility, body: body.trim() }, { idempotencyKey: true });
    setBody("");
    onAdded();
  };
  const submit = async () => {
    if (!body.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await post();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="space-y-4">
      <ul className="space-y-3" aria-label="Case notes">
        {(notes ?? []).map((n, i) => (
          <li key={`${n.at}-${i}`} className="rounded-lg border border-line p-3 text-sm">
            <p className="text-xs text-fg-muted">
              {formatDateTime(n.at)} · {n.author_id ? staffRef(n.author_id, "Reviewer") : "System"} · <Badge tone={n.visibility === "internal" ? "neutral" : "info"}>{n.visibility === "internal" ? "Internal" : "Visible to student"}</Badge>
            </p>
            <p className="mt-1 whitespace-pre-wrap text-fg">{n.body}</p>
          </li>
        ))}
        {!notes?.length ? <li className="text-sm text-fg-muted">No notes yet.</li> : null}
      </ul>
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (!body.trim()) return;
          // A student-visible note cannot be taken back: confirm first (audit 0.7).
          if (visibility === "student") setConfirmStudent(true);
          else void submit();
        }}
      >
        <FormField label="Visibility">
          {(f) => (
            <Select
              {...f}
              value={visibility}
              onChange={(e) => setVisibility(e.target.value)}
              options={[
                { value: "internal", label: "Internal (reviewers only)" },
                { value: "student", label: "Visible to the student" },
              ]}
            />
          )}
        </FormField>
        <FormField label="Note" hint={`${body.length}/4000`}>
          {(f) => <TextArea {...f} value={body} onChange={(e) => setBody(e.target.value)} maxLength={4000} />}
        </FormField>
        <InlineProblem error={error} />
        <Button type="submit" loading={busy} disabled={!body.trim()}>
          {visibility === "student" ? "Add note for student" : "Add note"}
        </Button>
      </form>
      <ConfirmDialog
        open={confirmStudent}
        onClose={() => setConfirmStudent(false)}
        title="Show this note to the student?"
        description="The student will see this note on their case. Notes cannot be edited or removed after they are added."
        confirmLabel="Add visible note"
        cancelLabel="Back to editing"
        onConfirm={post}
      >
        <blockquote className="max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-md border border-line bg-surface-sunken p-3 text-sm text-fg">{body.trim()}</blockquote>
      </ConfirmDialog>
    </div>
  );
}
