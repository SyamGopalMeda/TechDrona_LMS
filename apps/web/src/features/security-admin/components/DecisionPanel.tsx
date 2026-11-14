"use client";

import { useState, type FormEvent } from "react";
import { Button, Checkbox, FormField, Input, Select, useToast } from "@/components/ui";
import { api } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { ActionDialog, InlineProblem, KeyValueList, TextArea } from "@/features/admin/components/console-ui";
import { formatCountdown, formatDateTime, humanize, problemFieldErrors, toOutcome } from "@/features/admin/lib/console";
import { staffRef } from "../lib/ids";
import { STAFF_LEVEL_LABEL, toLevel } from "./RiskLevel";
import { DECISION_OUTCOMES, outcomesFor } from "../lib/catalogue";
import type { CaseDetail, DecisionPayload, PendingCaseApproval } from "../lib/types";

const MIN_SUMMARY = 50;

/** Client-side hint only: the api computes `requires_second_approval` (UNB §5). */
export function predictSecondApproval(detail: CaseDetail, outcome: string): boolean {
  const level = detail.restriction?.level ?? detail.level ?? 0;
  if (level >= 4 && detail.is_high_risk && outcome.startsWith("lift")) return true;
  if (outcome === "lift_false_positive" && detail.recommended_level === 4 && (detail.score ?? 0) >= 90) return true;
  if (detail.high_risk_reasons?.includes("staff_account") && outcome === "convert_L4") return true;
  return false;
}

/** verified: app/modules/security/cases.py propose_decision (202) / finalize_decision (201). */
interface DecisionResponse {
  decision_id?: string;
  requires_second_approval?: boolean;
  approval_request_id?: string;
  expires_at?: string;
}

export interface DecisionPanelProps {
  detail: CaseDetail;
  ifMatch: string | undefined;
  viewed: { explanation: boolean; timeline: boolean };
  onChanged: () => void;
}

/**
 * SEC-003 decision panel (SEC-09). Disabled until Explanation and Timeline were opened (also
 * checked server-side: `explanation_not_viewed`). P5 step-up arrives as 401 and is handled
 * by the global step-up dialog, which retries with the same Idempotency-Key.
 */
export function DecisionPanel({ detail, ifMatch, viewed, onChanged }: DecisionPanelProps) {
  const toast = useToast();
  const restricted = !!detail.restriction;
  const outcomes = outcomesFor(restricted);
  const [outcome, setOutcome] = useState<string>(restricted ? "lift_with_warning" : "close_no_action");
  const closing = outcome === "close_no_action";
  const [rationale, setRationale] = useState("");
  const [summary, setSummary] = useState("");
  const [extension, setExtension] = useState(false);
  const [extensionDays, setExtensionDays] = useState("");
  const [fpRules, setFpRules] = useState("");
  const [exceptionKey, setExceptionKey] = useState("");
  const [exceptionValue, setExceptionValue] = useState("");
  const [exceptionExpiry, setExceptionExpiry] = useState("");
  const [preview, setPreview] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const def = DECISION_OUTCOMES.find((o) => o.value === outcome)!;
  const currentLevel = detail.restriction?.level ?? detail.level ?? 0;
  const resultingLevel = def.defaultLevel === -1 ? currentLevel : def.defaultLevel;
  const secondApproval = predictSecondApproval(detail, outcome);
  const ready = viewed.explanation && viewed.timeline;

  const validate = (): Record<string, string> => {
    const e: Record<string, string> = {};
    // Closing without action: the summary is optional (the learner may not know about the case).
    if (!(closing && !summary.trim()) && summary.trim().length < MIN_SUMMARY) e.student_summary = `Write at least ${MIN_SUMMARY} characters the student will read (${summary.trim().length} so far).`;
    if (outcome === "convert_L4" && rationale.trim().length < 20) e.rationale = "Converting to L4 needs a documented rationale.";
    if (!rationale.trim()) e.rationale = e.rationale ?? "Add the internal rationale.";
    if (extension && outcome !== "lift_false_positive") e.extension_days = "Extension credit only applies to a false-positive lift.";
    if (exceptionKey && (!exceptionValue || !exceptionExpiry)) e.conditions = "An exception needs a value and an expiry date.";
    return e;
  };

  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    const e = validate();
    setErrors(e);
    if (Object.keys(e).length) return;
    const body: DecisionPayload = {
      // unblock_request_id omitted: the case GET exposes only the reference; the api links the open request itself.
      outcome,
      ...(closing ? {} : { resulting_level: resultingLevel }),
      rationale: rationale.trim(),
      student_summary: summary.trim(),
      ...(exceptionKey && !closing
        ? { conditions: { user_exception: { setting_key: exceptionKey.trim(), value: Number.isNaN(Number(exceptionValue)) ? exceptionValue : Number(exceptionValue), expires_at: new Date(`${exceptionExpiry}T00:00:00+05:30`).toISOString() } } }
        : {}),
      ...(extension && extensionDays && outcome === "lift_false_positive" ? { extension_days: Number(extensionDays) } : {}),
      ...(outcome === "lift_false_positive" && fpRules.trim() ? { false_positive_rule_keys: fpRules.split(/[\s,]+/).filter(Boolean) } : {}),
    };
    setBusy(true);
    setError(null);
    try {
      const res = await api.post<DecisionResponse>(`security/cases/${detail.case_id}/decisions`, body, { idempotencyKey: true, ifMatch });
      const data = res.kind === "ok" ? res.data : undefined;
      if (res.kind === "approval_pending" || data?.requires_second_approval) {
        toast.show({ title: "Submitted for second approval", description: "Another reviewer (not you, not the person who applied the restriction) must approve within 72 h.", tone: "info" });
      } else {
        toast.show({ title: closing ? "Case closed — no action taken" : "Decision recorded", tone: "success", requestId: res.requestId });
      }
      onChanged();
    } catch (err) {
      setError(err);
      setErrors(problemFieldErrors(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section aria-labelledby="decision-title" className="rounded-xl border border-line bg-surface p-4">
      <h2 id="decision-title" className="font-display text-base font-semibold text-fg">
        Decision
      </h2>
      {!ready ? (
        <p id="decision-not-ready" role="status" className="mt-2 rounded-md border border-warning-border bg-warning-subtle p-2 text-sm text-warning-fg">
          Open Explanation and Timeline before deciding.
          <span className="mt-0.5 block text-xs">
            Still to open: {[!viewed.explanation ? "Explanation" : null, !viewed.timeline ? "Timeline" : null].filter(Boolean).join(" and ")}. The decision button unlocks once both tabs have loaded.
          </span>
        </p>
      ) : null}
      <form onSubmit={submit} className="mt-3 space-y-3" noValidate>
        <FormField label="Outcome" required>
          {(f) => <Select {...f} value={outcome} onChange={(e) => setOutcome(e.target.value)} options={outcomes.map((o) => ({ value: o.value, label: o.label }))} />}
        </FormField>
        <p className="text-xs text-fg-muted">
          {closing ? "No restriction on this account: the case is closed and nothing on the account changes." : `Resulting level: ${levelWords(resultingLevel)}`}
        </p>
        <FormField label="Rationale (internal)" required error={errors.rationale}>
          {(f) => <TextArea {...f} value={rationale} onChange={(e) => setRationale(e.target.value)} maxLength={4000} />}
        </FormField>
        <FormField
          label="Student summary"
          required={!closing}
          hint={closing ? `Optional. Leave empty to close without telling the student; if written, at least ${MIN_SUMMARY} characters.` : `At least ${MIN_SUMMARY} characters. Shown exactly as written.`}
          error={errors.student_summary}
        >
          {(f) => <TextArea {...f} value={summary} onChange={(e) => setSummary(e.target.value)} maxLength={2000} />}
        </FormField>
        <Button variant="ghost" size="sm" onClick={() => setPreview((p) => !p)} aria-expanded={preview}>
          {preview ? "Hide student preview" : "Preview as student"}
        </Button>
        {preview ? (
          <div className="rounded-md border border-line bg-surface-subtle p-3 text-sm text-fg" aria-label="Student preview">
            <p className="font-semibold">We reviewed your request</p>
            <p className="mt-1 whitespace-pre-wrap">{summary || "(empty)"}</p>
          </div>
        ) : null}
        {closing ? null : (
        <details className="rounded-md border border-line p-2">
          <summary className="cursor-pointer text-sm font-medium text-fg">Conditions / exception</summary>
          <div className="mt-2 space-y-2">
            <FormField label="Setting key" hint="e.g. devices.student.max_trusted" error={errors.conditions}>
              {(f) => <Input {...f} value={exceptionKey} onChange={(e) => setExceptionKey(e.target.value)} />}
            </FormField>
            <FormField label="Value">{(f) => <Input {...f} value={exceptionValue} onChange={(e) => setExceptionValue(e.target.value)} />}</FormField>
            <FormField label="Expires on" hint="Over 90 days, or beyond 2× the default, needs a second approver.">
              {(f) => <Input {...f} type="date" value={exceptionExpiry} onChange={(e) => setExceptionExpiry(e.target.value)} />}
            </FormField>
          </div>
        </details>
        )}
        {outcome === "lift_false_positive" ? (
          <>
            <Checkbox label="Extension credit (restricted days)" checked={extension} onChange={(e) => setExtension(e.target.checked)} />
            {extension ? (
              <FormField label="Extension days" error={errors.extension_days}>
                {(f) => <Input {...f} type="number" min={1} max={30} value={extensionDays} onChange={(e) => setExtensionDays(e.target.value)} />}
              </FormField>
            ) : null}
          </>
        ) : null}
        {outcome === "lift_false_positive" ? (
          <FormField label="False-positive rules" hint="Rule keys, comma separated (counted in the false-positive report)">
            {(f) => <Input {...f} value={fpRules} onChange={(e) => setFpRules(e.target.value)} />}
          </FormField>
        ) : null}
        <Checkbox
          label="Requires second approval"
          description={secondApproval ? "Likely required for this decision (computed by the server; cannot be unticked)." : "The server decides this when you submit."}
          checked={secondApproval}
          disabled
          readOnly
        />
        <InlineProblem error={error} />
        <Button type="submit" loading={busy} disabled={!ready} aria-describedby={!ready ? "decision-not-ready" : undefined} className="w-full">
          {secondApproval ? "Submit for approval" : "Record decision"}
        </Button>
      </form>
    </section>
  );
}

/* ---------------------------------------------------- Second-approval state */

/**
 * Pending `security.case.decision` proposal (approval_requests): requester can withdraw
 * (SEC-11a); a distinct reviewer approves (SEC-10) or sends back (SEC-11, note required).
 */
export function PendingApprovalPanel({ detail, approval, ifMatch, onChanged }: { detail: CaseDetail; approval: PendingCaseApproval; ifMatch: string | undefined; onChanged: () => void }) {
  const toast = useToast();
  const [dialog, setDialog] = useState<"approve" | "send_back" | "withdraw" | null>(null);
  const [note, setNote] = useState("");
  const base = `security/cases/${detail.case_id}/approval-requests/${approval.approval_request_id}`;
  const p = approval.payload;
  const expired = approval.status === "expired" || Date.parse(approval.expires_at) < Date.now();
  const canDecide = !approval.is_requester && approval.can_decide !== false && !expired;

  return (
    <section aria-labelledby="pending-title" className="rounded-xl border border-info-border bg-info-subtle p-4">
      <h2 id="pending-title" className="font-display text-base font-semibold text-info-fg">
        <span aria-hidden="true">ⓘ </span>
        {expired ? "Proposal expired" : "Waiting for a second approver"}
      </h2>
      <p className="mt-1 text-sm text-fg-secondary">
        Proposed by {approval.requested_by ? staffRef(approval.requested_by, "Reviewer") : "a reviewer"}
        {approval.requested_at ? ` ${formatDateTime(approval.requested_at)}` : ""} · {expired ? "expired — the proposer must re-propose" : `expires ${formatCountdown(approval.expires_at)}`}
      </p>
      {p ? (
        <KeyValueList
          className="mt-3"
          items={[
            { label: "Outcome", value: outcomeLabel(p.outcome) },
            { label: "Resulting level", value: typeof p.resulting_level === "number" ? levelWords(p.resulting_level) : "—" },
            { label: "Extension credit", value: p.extension_days ? `${p.extension_days} days` : "None" },
            { label: "Student summary", value: p.student_summary },
            ...(p.rationale ? [{ label: "Rationale", value: p.rationale }] : []),
          ]}
        />
      ) : null}
      <div className="mt-4 flex flex-wrap gap-2">
        {approval.is_requester && !expired ? (
          <Button variant="secondary" onClick={() => setDialog("withdraw")}>
            Withdraw proposal
          </Button>
        ) : null}
        {canDecide ? (
          <>
            <Button onClick={() => setDialog("approve")}>Approve</Button>
            <Button variant="secondary" onClick={() => setDialog("send_back")}>
              Send back
            </Button>
          </>
        ) : null}
      </div>
      {!approval.is_requester && approval.can_decide === false ? (
        <p className="mt-2 text-sm text-fg-secondary">You can&apos;t decide this proposal: you proposed it, applied the restriction, or have a conflict. Another reviewer must decide.</p>
      ) : null}
      {approval.is_requester ? <p className="mt-2 text-sm text-fg-secondary">You proposed this, so another reviewer must approve it.</p> : null}

      <ActionDialog
        open={dialog === "approve"}
        onClose={() => setDialog(null)}
        onOpen={() => setNote("")}
        title="Approve this decision?"
        description="The stored proposal is executed exactly as submitted. This needs a fresh confirmation."
        submitLabel="Approve"
        onSubmit={async () => toOutcome(await api.post(`${base}/approve`, { note: note.trim() || undefined }, { idempotencyKey: true, ifMatch }))}
        onDone={() => {
          setNote("");
          toast.show({ title: "Decision approved", tone: "success" });
          onChanged();
        }}
      >
        <FormField label="Note (optional)">{(f) => <TextArea {...f} value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} />}</FormField>
      </ActionDialog>
      <ActionDialog
        open={dialog === "send_back"}
        onClose={() => setDialog(null)}
        onOpen={() => setNote("")}
        title="Send back to the proposer"
        description="The request returns to Under review with your note. No decision is recorded."
        submitLabel="Send back"
        validate={() => (note.trim().length < 3 ? "A reason is required." : null)}
        onSubmit={async () => toOutcome(await api.post(`${base}/send-back`, { note: note.trim() }, { ifMatch }))}
        onDone={() => {
          setNote("");
          onChanged();
        }}
      >
        <FormField label="Reason" required>
          {(f) => <TextArea {...f} value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} />}
        </FormField>
      </ActionDialog>
      <ActionDialog
        open={dialog === "withdraw"}
        onClose={() => setDialog(null)}
        title="Withdraw your proposal?"
        description="The case stays escalated until you propose a new decision."
        submitLabel="Withdraw"
        onSubmit={async () => toOutcome(await api.post(`${base}/withdraw`, {}, { ifMatch }))}
        onDone={onChanged}
      />
    </section>
  );
}

/** Read-only decided state ("No delete"). */
export function DecidedPanel({ detail }: { detail: CaseDetail }) {
  const d = detail.decisions?.[detail.decisions.length - 1];
  if (!d) return null;
  return (
    <section aria-labelledby="decided-title" className="rounded-xl border border-line bg-surface p-4">
      <h2 id="decided-title" className="font-display text-base font-semibold text-fg">
        Decision recorded
      </h2>
      <KeyValueList
        className="mt-3"
        items={[
          { label: "Outcome", value: outcomeLabel(d.outcome) },
          { label: "Decided by", value: staffRef(d.decided_by, "Reviewer") },
          { label: "Approved by", value: d.approved_by ? staffRef(d.approved_by, "Reviewer") : "Not required" },
          { label: "When", value: formatDateTime(d.at) },
        ]}
      />
      <p className="mt-3 text-xs text-fg-muted">Decisions are append-only and cannot be deleted.</p>
    </section>
  );
}

/** "L0 · None" … "L4 · Suspended" for a resulting level. */
function levelWords(level: number): string {
  const lv = toLevel(level);
  return lv === null ? "—" : STAFF_LEVEL_LABEL[lv];
}

/** Decision outcome in the same words as the Outcome select. */
export function outcomeLabel(outcome: string | null | undefined): string {
  return DECISION_OUTCOMES.find((o) => o.value === outcome)?.label ?? humanize(outcome);
}

export function isApiCode(err: unknown, code: string): boolean {
  return err instanceof ApiError && err.code === code;
}
