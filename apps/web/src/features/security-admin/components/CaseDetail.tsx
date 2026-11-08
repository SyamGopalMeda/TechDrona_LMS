"use client";

import Link from "next/link";
import { useCallback, useMemo, useState } from "react";
import { Badge, Button, Card, ErrorState, FormField, Input, PageHeader, Select, Skeleton, Tabs, useToast } from "@/components/ui";
import { api } from "@/lib/api/client";
import { ActionDialog, KeyValueList, ReasonGate, StateBadge, TextArea, textLink, type ReasonChoice } from "@/features/admin/components/console-ui";
import { formatCountdown, formatDateTime, humanize, ifMatchFor, toOutcome, useVersioned } from "@/features/admin/lib/console";
import type { CaseDetail as CaseDetailDto } from "../lib/types";
import { DecidedPanel, DecisionPanel, PendingApprovalPanel } from "./DecisionPanel";
import { ConcurrencyTab, DeviceGraphTab, ExplanationTab, HistoryTab, NotesTab, SubmissionTab, TimelineTab, type EvidenceContext } from "./EvidenceTabs";
import { RiskBadge } from "./RiskLevel";

/** SEC-003 case detail. Asks for a reason code first (SEC-04 requires it; audited). */
export function CaseDetail({ caseId }: { caseId: string }) {
  return (
    <ReasonGate title="Open case" description="Case views show personal security data and are recorded in the audit log. Choose why you are opening this case.">
      {(choice) => <CaseView caseId={caseId} reason={choice} />}
    </ReasonGate>
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
  if (!res.data) {
    return (
      <div aria-busy="true" className="space-y-3">
        <span className="sr-only">Loading case…</span>
        <Skeleton className="h-8 w-1/2" />
        <Skeleton className="h-32 w-full" />
      </div>
    );
  }

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
      label: `Timeline (H12)${viewed.timeline ? " ✓" : ""}`,
      content: userId ? <TimelineTab userId={userId} ctx={ctx} onViewed={markTimeline} /> : <p className="text-sm text-fg-muted">The subject is not available for this case.</p>,
    },
    { id: "concurrency", label: "Concurrency (H3)", content: userId ? <ConcurrencyTab userId={userId} ctx={ctx} isMinor={c.subject?.is_minor} /> : null },
    { id: "graph", label: "Devices graph (H2)", content: userId ? <DeviceGraphTab userId={userId} ctx={ctx} isMinor={c.subject?.is_minor} /> : null },
    { id: "submission", label: "Submission", content: <SubmissionTab reference={c.unblock_request?.reference} ctx={ctx} onChanged={reload} /> },
    { id: "history", label: "History", content: <HistoryTab detail={c} userId={userId} ctx={ctx} /> },
    { id: "notes", label: "Notes", content: <NotesTab caseId={caseId} notes={c.notes} onAdded={reload} /> },
  ];

  return (
    <div>
      <PageHeader
        eyebrow="SEC-003"
        title={c.case_ref}
        description={c.subject?.name ? `Subject: ${c.subject.name}` : undefined}
        actions={
          <>
            {!c.assignee_id ? <Button onClick={() => void claim()}>Claim</Button> : null}
            <Button variant="secondary" onClick={() => setDialog("assign")}>
              Assign
            </Button>
            {userId ? (
              <Link className="inline-flex h-10 items-center rounded-md border border-line-control bg-surface px-4 text-sm font-medium text-fg hover:bg-surface-hover focus-visible:shadow-focus focus-visible:outline-none" href={`/security/users/${userId}/timeline`}>
                Full timeline
              </Link>
            ) : null}
          </>
        }
      />

      <Card className="mb-4">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <RiskBadge level={c.restriction?.level ?? c.level} />
          {c.family ? <Badge>{humanize(c.family)}</Badge> : null}
          <StateBadge state={c.status} />
          {c.is_high_risk ? <Badge tone="warning">⚑ High-risk</Badge> : <Badge>High-risk: no</Badge>}
          {c.repeat_count ? <Badge>↺ Repeat ×{c.repeat_count}</Badge> : null}
          {c.subject?.is_minor ? <Badge tone="info">Minor</Badge> : null}
        </div>
        <KeyValueList
          items={[
            { label: "Assignee", value: c.assignee_id ? <span className="font-mono">{c.assignee_id}</span> : "Unassigned" },
            { label: "Recommended level", value: typeof c.recommended_level === "number" ? `L${c.recommended_level}` : "—" },
            { label: "Restriction since", value: formatDateTime(c.restriction?.starts_at) },
            { label: "Ends", value: c.restriction?.ends_at ? formatDateTime(c.restriction.ends_at) : c.restriction ? "No end date" : "—" },
            ...(c.restriction?.deferred_until ? [{ label: "Deferred until", value: formatDateTime(c.restriction.deferred_until) }] : []),
            { label: "Source", value: humanize(c.restriction?.source) },
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

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="min-w-0">
          <Tabs label="Case evidence" items={tabs} />
        </div>
        <aside className="space-y-4 xl:sticky xl:top-20 xl:self-start" aria-label="Decision and controls">
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
                See <Link className={textLink} href="/security/restrictions">Restrictions</Link> to lift L1/L2. L3/L4 change only through a decision.
              </p>
            </Card>
          ) : null}
        </aside>
      </div>

      <ActionDialog
        open={dialog === "assign"}
        onClose={() => setDialog(null)}
        title="Assign reviewer"
        description="A conflict-of-interest check runs on the new assignee."
        submitLabel="Assign"
        validate={() => (assignee.trim() ? null : "Enter the reviewer's user id.")}
        onSubmit={async () => toOutcome(await api.post(`security/cases/${caseId}/assign`, { assignee_id: assignee.trim() }, { ifMatch }))}
        onDone={() => {
          setAssignee("");
          reload();
        }}
      >
        <FormField label="Reviewer user id" required>
          {(f) => <Input {...f} value={assignee} onChange={(e) => setAssignee(e.target.value)} />}
        </FormField>
      </ActionDialog>

      <ActionDialog
        open={dialog === "revoke"}
        onClose={() => setDialog(null)}
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
        title="Apply restriction"
        description="L3/L4 are linked to this case. L4 needs a rationale and revokes all sessions; on a staff account it needs a second reviewer."
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
