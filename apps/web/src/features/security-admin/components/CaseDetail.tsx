"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Badge, Button, Card, ErrorState, FormField, Input, LinkButton, LoadingBlock, PageHeader, Select, Tabs, useToast, type Crumb } from "@/components/ui";
import { api } from "@/lib/api/client";
import { ActionDialog, KeyValueList, ReasonGate, StateBadge, TextArea, textLink, type ReasonChoice } from "@/features/admin/components/console-ui";
import { formatCountdown, formatDateTime, humanize, ifMatchFor, toOutcome, useVersioned } from "@/features/admin/lib/console";
import { sourceLabel } from "../lib/catalogue";
import { staffRef } from "../lib/ids";
import type { CaseDetail as CaseDetailDto } from "../lib/types";
import { DecidedPanel, DecisionPanel, PendingApprovalPanel } from "./DecisionPanel";
import { ConcurrencyTab, DeviceGraphTab, ExplanationTab, HistoryTab, NotesTab, SubmissionTab, TimelineTab, type EvidenceContext } from "./EvidenceTabs";
import { RiskBadge, STAFF_LEVEL_LABEL, toLevel } from "./RiskLevel";

const CASES_CRUMBS: Crumb[] = [
  { label: "Security", href: "/security" },
  { label: "Cases", href: "/security/cases" },
];

/** Hands the gate's choice up to CaseDetail so the gate's page header is replaced by the case's. */
function ChoiceCommit({ choice, onChoice }: { choice: ReasonChoice; onChoice: (c: ReasonChoice) => void }) {
  useEffect(() => onChoice(choice), [choice, onChoice]);
  return <LoadingBlock label="Opening case…" rows={2} size="card" />;
}

/** Case detail. Asks for a reason code first (SEC-04 requires it; audited). */
export function CaseDetail({ caseId }: { caseId: string }) {
  const [choice, setChoice] = useState<ReasonChoice | null>(null);
  if (choice) return <CaseView caseId={caseId} reason={choice} />;
  return (
    <div>
      <PageHeader breadcrumbs={[...CASES_CRUMBS, { label: "Open case" }]} title="Open case" description="Case views show personal security data and are recorded in the audit log." />
      <ReasonGate title="Why are you opening this case?" description="Choose a reason. It is saved with your view in the audit log.">
        {(c) => <ChoiceCommit choice={c} onChoice={setChoice} />}
      </ReasonGate>
    </div>
  );
}

const DECIDED = new Set(["decided", "closed"]);

export function CaseView({ caseId, reason }: { caseId: string; reason: ReasonChoice }) {
  const toast = useToast();
  const query = useMemo(() => ({ reason_code: reason.reason_code }), [reason.reason_code]);
  const res = useVersioned<CaseDetailDto>(`security/cases/${caseId}`, query);
  const [viewed, setViewed] = useState({ explanation: false, timeline: false });
  const [dialog, setDialog] = useState<"assign" | "revoke" | "restrict" | null>(null);
  const [assignee, setAssignee] = useState("");
  const [note, setNote] = useState("");
  const [level, setLevel] = useState("1");
  const markExplanation = useCallback(() => setViewed((v) => ({ ...v, explanation: true })), []);
  const markTimeline = useCallback(() => setViewed((v) => ({ ...v, timeline: true })), []);

  if (res.error && !res.data) return <ErrorState error={res.error} onRetry={() => void res.reload()} />;
  if (!res.data) return <LoadingBlock label="Loading case…" rows={3} size="card" />;

  const c = res.data;
  const ifMatch = ifMatchFor(res.etag, c.version);
  const ctx: EvidenceContext = { reasonCode: reason.reason_code, caseRef: c.case_ref };
  const userId = c.subject?.user_id;
  const reload = () => void res.reload();
  const decided = DECIDED.has(c.status) || (!!c.decisions.length && !c.pending_approval);

  const claim = async () => {
    try {
      await api.post(`security/cases/${caseId}/claim`, {}, { ifMatch });
      toast.show({ title: "You claimed this case.", tone: "success" });
      reload();
    } catch (err) {
      const e = err as { code?: string; title?: string; detail?: string; requestId?: string | null };
      toast.show({
        title: e.code === "conflict_of_interest" ? "You can't take this case" : (e.title ?? "Could not claim"),
        description: e.code === "conflict_of_interest" ? "You applied this restriction or have a conflict, so another reviewer must take it." : e.detail,
        tone: "danger",
        requestId: e.requestId,
      });
    }
  };

  const tabs = [
    { id: "explanation", label: `Explanation${viewed.explanation ? " ✓" : ""}`, content: <ExplanationTab caseId={caseId} ctx={ctx} onViewed={markExplanation} /> },
    {
      id: "timeline",
      label: `Timeline${viewed.timeline ? " ✓" : ""}`,
      content: userId ? <TimelineTab userId={userId} ctx={ctx} onViewed={markTimeline} /> : <p className="text-sm text-fg-muted">The subject is not available for this case.</p>,
    },
    { id: "concurrency", label: "Overlapping use", content: userId ? <ConcurrencyTab userId={userId} ctx={ctx} isMinor={c.subject?.is_minor} /> : null },
    { id: "graph", label: "Shared devices", content: userId ? <DeviceGraphTab userId={userId} ctx={ctx} isMinor={c.subject?.is_minor} /> : null },
    { id: "submission", label: "Submission", content: <SubmissionTab reference={c.unblock_request?.reference} ctx={ctx} onChanged={reload} /> },
    { id: "history", label: "History", content: <HistoryTab detail={c} userId={userId} ctx={ctx} /> },
    { id: "notes", label: "Notes", content: <NotesTab caseId={caseId} notes={c.notes} onAdded={reload} /> },
  ];

  return (
    <div>
      <PageHeader
        breadcrumbs={[...CASES_CRUMBS, { label: c.case_ref }]}
        title={c.subject?.name ? c.subject.name : `Case ${c.case_ref}`}
        meta={<StateBadge state={c.status} />}
        description={c.subject?.name ? `Case ${c.case_ref} · ${humanize(c.family)} review` : `${humanize(c.family)} review. The student's name is not available for this case.`}
        actions={
          <>
            {!c.assignee_id ? <Button onClick={() => void claim()}>Claim</Button> : null}
            <Button variant="secondary" onClick={() => setDialog("assign")}>
              Assign
            </Button>
            {userId ? (
              <LinkButton variant="secondary" href={`/security/users/${userId}/timeline`}>
                Full timeline
              </LinkButton>
            ) : null}
          </>
        }
      />

      <Card className="mb-4">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <RiskBadge level={c.restriction?.level ?? c.level} />
          {c.family ? <Badge>{humanize(c.family)}</Badge> : null}
          {c.is_high_risk ? <Badge tone="warning">⚑ High-risk</Badge> : null}
          {c.repeat_count ? <Badge>↺ Repeat ×{c.repeat_count}</Badge> : null}
          {c.subject?.is_minor ? <Badge tone="info">Minor</Badge> : null}
        </div>
        <KeyValueList
          items={[
            { label: "Assignee", value: c.assignee_id ? staffRef(c.assignee_id, "Reviewer") : "Unassigned" },
            { label: "Recommended level", value: (() => { const lv = toLevel(c.recommended_level); return lv === null ? "—" : STAFF_LEVEL_LABEL[lv]; })() },
            { label: "Restriction since", value: formatDateTime(c.restriction?.starts_at) },
            { label: "Ends", value: c.restriction?.ends_at ? formatDateTime(c.restriction.ends_at) : c.restriction ? "No end date" : "—" },
            ...(c.restriction?.deferred_until ? [{ label: "Deferred until", value: formatDateTime(c.restriction.deferred_until) }] : []),
            { label: "Applied by", value: sourceLabel(c.restriction?.source) },
            { label: "First response due", value: c.sla_first_response_due ? `${formatDateTime(c.sla_first_response_due)} (${formatCountdown(c.sla_first_response_due)})` : "—" },
            { label: "Decision due", value: c.sla_decision_due ? `${formatDateTime(c.sla_decision_due)} (${formatCountdown(c.sla_decision_due)})` : "—" },
            {
              label: "Linked request",
              value: c.unblock_request?.reference ? (
                <span>
                  <span className="font-mono">{c.unblock_request.reference}</span> · <StateBadge state={c.unblock_request.state} />
                </span>
              ) : (
                "None"
              ),
            },
          ]}
        />
        {c.high_risk_reasons?.length ? (
          <ul className="mt-3 list-disc pl-5 text-sm text-fg-secondary" aria-label="High-risk reasons">
            {c.high_risk_reasons.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        ) : null}
      </Card>

      {/* Two columns from lg (1024 px), where the decision panel becomes available, so it never drops below the evidence. */}
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem] xl:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="min-w-0">
          <Tabs label="Case evidence" items={tabs} />
        </div>
        <aside className="space-y-4 lg:sticky lg:top-20 lg:max-h-[calc(100dvh-6rem)] lg:self-start lg:overflow-y-auto lg:pb-1" aria-label="Decision and controls">
          {c.pending_approval && c.pending_approval.status !== "cancelled" && c.pending_approval.status !== "rejected" ? (
            <PendingApprovalPanel detail={c} approval={c.pending_approval} ifMatch={ifMatch} onChanged={reload} />
          ) : c.status === "escalated" && !c.pending_approval && !decided ? (
            // The earlier proposal was sent back, withdrawn or replaced: a reviewer proposes again.
            <div className="space-y-2">
              <p role="status" className="rounded-lg border border-info-border bg-info-subtle p-3 text-sm text-info-fg">
                No proposal is waiting for a second approver. Propose a new decision below.
              </p>
              <div className="hidden lg:block">
                <DecisionPanel detail={c} ifMatch={ifMatch} viewed={viewed} onChanged={reload} />
              </div>
            </div>
          ) : decided ? (
            <DecidedPanel detail={c} />
          ) : (
            <div className="hidden lg:block">
              <DecisionPanel detail={c} ifMatch={ifMatch} viewed={viewed} onChanged={reload} />
            </div>
          )}
          {!decided && !c.pending_approval ? <p className="text-xs text-fg-muted lg:hidden">Open this case on a larger screen (≥ 1024 px) to decide.</p> : null}
          {userId ? (
            <Card title="Sessions and restrictions">
              <div className="flex flex-wrap gap-2">
                <Button variant="secondary" onClick={() => setDialog("revoke")}>
                  Revoke all sessions
                </Button>
                <Button variant="secondary" onClick={() => setDialog("restrict")}>
                  Apply restriction
                </Button>
              </div>
              <p className="mt-2 text-xs text-fg-muted">
                Lift a notice (L1) or verification (L2) under <Link className={textLink} href="/security/restrictions">Restrictions</Link>. Temporary restrictions and suspensions (L3/L4) change only through a decision.
              </p>
            </Card>
          ) : null}
        </aside>
      </div>

      <ActionDialog
        open={dialog === "assign"}
        onClose={() => setDialog(null)}
        onOpen={() => setAssignee("")}
        title="Assign reviewer"
        description="A conflict-of-interest check runs on the new assignee."
        submitLabel="Assign"
        validate={() => (assignee.trim() ? null : "Enter the reviewer's user id (from Users in the Admin portal).")}
        onSubmit={async () => toOutcome(await api.post(`security/cases/${caseId}/assign`, { assignee_id: assignee.trim() }, { ifMatch }))}
        onDone={() => {
          setAssignee("");
          reload();
        }}
      >
        <FormField label="Reviewer user id" required hint="Copy it from the reviewer's page under Admin › Users.">
          {(f) => <Input {...f} value={assignee} onChange={(e) => setAssignee(e.target.value)} />}
        </FormField>
      </ActionDialog>

      <ActionDialog
        open={dialog === "revoke"}
        onClose={() => setDialog(null)}
        onOpen={() => setNote("")}
        title="Revoke all sessions?"
        description="The user is signed out everywhere. Any in-progress test keeps its autosaved answers."
        submitLabel="Revoke sessions"
        danger
        validate={() => (note.trim().length < 5 ? "Give a reason." : null)}
        onSubmit={async () => toOutcome(await api.post<{ revoked: number }>(`users/${userId}/sessions/revoke`, { session_id: null, all: true, reason_code: "case", reason: `${c.case_ref}: ${note.trim()}` }, { idempotencyKey: true }))}
        onDone={(o) => {
          setNote("");
          if (o.kind === "ok") toast.show({ title: `Revoked ${o.data.revoked} session${o.data.revoked === 1 ? "" : "s"}.`, tone: "success" });
        }}
      >
        <FormField label="Reason" required>
          {(f) => <TextArea {...f} value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} />}
        </FormField>
      </ActionDialog>

      <ActionDialog
        open={dialog === "restrict"}
        onClose={() => setDialog(null)}
        onOpen={() => {
          setNote("");
          setLevel("1");
        }}
        title="Apply restriction"
        description="Temporary restrictions (L3) and suspensions (L4) are linked to this case. A suspension needs a rationale and signs the user out everywhere; on a staff account it needs a second reviewer."
        submitLabel="Apply"
        danger
        validate={() => (level === "4" && note.trim().length < 20 ? "L4 needs a documented rationale (20+ characters)." : note.trim().length < 3 ? "Add a rationale." : null)}
        onSubmit={async () =>
          toOutcome(
            await api.post(
              "security/restrictions",
              { user_id: userId, level: Number(level), family: c.family ?? "sharing", case_id: Number(level) >= 3 ? caseId : undefined, rationale: note.trim(), ends_at: null },
              { idempotencyKey: true },
            ),
          )
        }
        onDone={() => {
          setNote("");
          reload();
        }}
      >
        <FormField label="Level" required>
          {(f) => (
            <Select
              {...f}
              value={level}
              onChange={(e) => setLevel(e.target.value)}
              options={[
                { value: "1", label: "L1 · Notice" },
                { value: "2", label: "L2 · Verify" },
                { value: "3", label: "L3 · Temporary restriction" },
                { value: "4", label: "L4 · Suspended" },
              ]}
            />
          )}
        </FormField>
        <FormField label="Rationale" required>{(f) => <TextArea {...f} value={note} onChange={(e) => setNote(e.target.value)} maxLength={4000} />}</FormField>
      </ActionDialog>
    </div>
  );
}
