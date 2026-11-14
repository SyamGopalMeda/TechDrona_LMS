"use client";

import { useState, type ReactNode } from "react";
import { Button, Card, EmptyState, ErrorState, FormField, LoadingBlock, PageHeader, Pagination, Select, useToast } from "@/components/ui";
import { api } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { ActionDialog, FilterBar, InlineProblem, JsonBlock, KeyValueList, StateBadge, TextArea, ValueSummary } from "./console-ui";
import { UserRef } from "./Governance";
import { useSimpleAuth } from "@/components/shell/Integrations";
import { cleanQuery, formatINR, humanize, shortRef, toOutcome, useCursorList, useVersioned, type MutationOutcome } from "../lib/console";
import { DEFAULT_HANDLE, useIdentity } from "@/lib/api/session-cache";
import { formatDateTime, formatTimeUntil } from "@/lib/format";

/**
 * One approval request. verified: app/modules/admin/approvals.py approval_out (list rows from
 * GET admin/approvals; `payload`/`payload_hash` only on GET admin/approvals/{id}).
 */
export interface ApprovalRow {
  approval_request_id: string;
  action_type: string;
  target_type: string;
  target_id: string | null;
  requested_by: string;
  request_reason: string | null;
  required_approver_role: string | null;
  status: string;
  decided_by: string | null;
  decided_at: string | null;
  decision_note: string | null;
  expires_at: string;
  created_at: string | null;
  payload?: unknown;
  payload_hash?: string;
  /** The caller is the only active Admin, so they may decide their own request (rbac is_sole_admin). */
  self_decidable?: boolean;
}

export const approvalId = (r: ApprovalRow) => r.approval_request_id;

/**
 * Labels keyed by the real `action_type` values the api writes (grep `action_type=` in
 * apps/api/app/modules: admin/router.py, admin/accounts.py, commerce/router.py, entitlements,
 * orgs/lifecycle.py, rbac/router.py, security/controls.py, security/api_engine.py, analytics/exports.py).
 */
const ACTION_TYPES: Record<string, string> = {
  "policy.change": "Change policy",
  "security.export.per_user": "Security export (per-user rows)",
  "export.bulk_pii": "Bulk personal-data export",
  "security.restriction.bulk_lift": "Bulk false-positive lift",
  "risk.kill_switch.ratify": "Ratify kill switch",
  "risk.ruleset.activate": "Activate rule version",
  "risk.ruleset.rollback": "Roll back rule version",
  "rbac.grant.privileged": "Privileged role grant",
  "rbac.revoke.privileged": "Privileged role revoke",
  "commerce.refund": "Refund (goodwill or above threshold)",
  "commerce.coupon.activate": "Activate coupon",
  "commerce.price.create": "New price",
  "commerce.gst_export": "GST register export",
  "entitlements.grant.bulk": "Bulk access grant",
  "user.mfa.reset": "MFA reset",
};

export function actionTypeLabel(t: string): string {
  return ACTION_TYPES[t] ?? humanize(t);
}

/** Commerce Dual types decided by FIN `finance/approval-requests/*` (commerce/admin.py COMMERCE_ACTIONS). */
const COMMERCE_ACTIONS = new Set(["commerce.refund", "commerce.coupon.activate", "commerce.price.create", "commerce.contract.terminate", "entitlements.grant.bulk"]);
/** Privileged grant/revoke decided by RBAC-07/08 `rbac/approval-requests/*` (rbac/router.py PRIVILEGED_ACTIONS). */
const RBAC_ACTIONS = new Set(["rbac.grant.privileged", "rbac.revoke.privileged"]);

/** Module-specific decide endpoint for action types the admin registry may not (yet) execute. */
export function fallbackDecidePath(actionType: string, id: string, approve: boolean): string | null {
  const verb = approve ? "approve" : "reject";
  if (COMMERCE_ACTIONS.has(actionType)) return `finance/approval-requests/${id}/${verb}`;
  if (RBAC_ACTIONS.has(actionType)) return `rbac/approval-requests/${id}/${verb}`;
  return null;
}

/**
 * Decide one approval (ADM-13/ADM-25). The one queue is `admin/approvals/{id}/approve|reject`
 * (ADM-14); when the admin registry has no executor for a commerce or privileged-RBAC type it
 * answers 404 not_found, and the request is decided by its owning module instead
 * (FIN `finance/approval-requests/{id}/*`, RBAC-07/08 `rbac/approval-requests/{id}/*`).
 * Both take `{ note }` and enforce the same SoD (approver ≠ requester) server-side.
 */
export async function decideApproval(row: Pick<ApprovalRow, "approval_request_id" | "action_type">, approve: boolean, note: string): Promise<MutationOutcome<unknown>> {
  const id = row.approval_request_id;
  const body = { note: note.trim() || undefined };
  try {
    return toOutcome(await api.post(`admin/approvals/${id}/${approve ? "approve" : "reject"}`, body, { idempotencyKey: true }));
  } catch (err) {
    const fallback = fallbackDecidePath(row.action_type, id, approve);
    if (!fallback || !(err instanceof ApiError) || err.status !== 404) throw err;
    return toOutcome(await api.post(fallback, RBAC_ACTIONS.has(row.action_type) ? { note: body.note?.slice(0, 500) } : body, { idempotencyKey: true }));
  }
}

/* ---------------------------------------------------------------- payload view */

const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);

function payloadValue(key: string, v: unknown): ReactNode {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "number" && key.endsWith("_paise")) return formatINR(v);
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (typeof v === "string" && /_id$|^id$/.test(key)) return <span title={v}>{key === "user_id" ? `User ${shortRef(v)}` : shortRef(v)}</span>;
  if (typeof v === "string" || typeof v === "number") return String(v);
  if (Array.isArray(v) && v.every((x) => typeof x !== "object" || x === null)) return v.length ? v.map(String).join(", ") : "None";
  return <ValueSummary label={humanize(key)} value={v} raw={false} />;
}

/**
 * The stored change that will run (FR-ADM-004 "payload diff"): one readable row per field, with
 * the exact JSON and its integrity hash under a collapsed "Raw data" disclosure (audit 1.11).
 */
export function ApprovalPayload({ payload, hash }: { payload: unknown; hash?: string }) {
  return (
    <div className="space-y-2" role="group" aria-label="Request payload">
      {isRecord(payload) ? (
        Object.keys(payload).length ? (
          <KeyValueList items={Object.entries(payload).map(([k, v]) => ({ key: k, label: humanize(k), value: payloadValue(k, v), wide: typeof v === "object" && v !== null }))} />
        ) : (
          <p className="text-sm text-fg-muted">The request carries no details.</p>
        )
      ) : (
        <ValueSummary label="Request details" value={payload} raw={false} />
      )}
      <details className="text-sm">
        <summary className="inline-flex min-h-6 cursor-pointer items-center font-medium text-fg-secondary hover:text-fg focus-visible:shadow-focus focus-visible:outline-none">Raw data</summary>
        <div className="mt-2 space-y-2">
          <JsonBlock label="Payload" value={payload} collapsed={false} />
          {hash ? <p className="break-all font-mono text-xs text-fg-muted">Payload hash {hash}</p> : null}
        </div>
      </details>
    </div>
  );
}

/** GET admin/approvals/{id} (the only route that returns `payload` and `payload_hash`). */
function ApprovalDetail({ id }: { id: string }) {
  const detail = useVersioned<ApprovalRow>(`admin/approvals/${id}`);
  if (detail.error) return <InlineProblem error={detail.error} />;
  if (!detail.data) return <LoadingBlock label="Loading the request details…" lines={2} />;
  return <ApprovalPayload payload={detail.data.payload} hash={detail.data.payload_hash} />;
}

export interface ApprovalsQueueProps {
  title?: string;
  eyebrow?: string;
  description?: string;
  /** Restrict to these action types (comma-joined into `action_type`). */
  actionTypes?: string[];
  /** Hide the type filter (fixed queues such as finance refunds). */
  fixedType?: boolean;
  embedded?: boolean;
}

/**
 * Dual-control approvals (ADM-12..16). The api already filters to action types the caller may
 * approve. Approve/reject are hidden for the requester ("You requested this…"); never used
 * for `security.case.decision` (those are decided on the case, SEC-10/SEC-11).
 */
export function ApprovalsQueue({ title = "Approvals", eyebrow, description, actionTypes, fixedType, embedded }: ApprovalsQueueProps) {
  const toast = useToast();
  const [type, setType] = useState(actionTypes?.join(",") ?? "");
  const [status, setStatus] = useState("pending");
  // verified: app/modules/admin/router.py approvals — only `status` is a query param; the api
  // returns every row the caller requested or may approve ({data}, unpaginated), so the type
  // filter is applied here.
  const list = useCursorList<ApprovalRow>("admin/approvals", cleanQuery({ status }));
  const me = useIdentity<{ user: { id: string } }>("me", { handle: DEFAULT_HANDLE });
  // TD_SIMPLE_AUTH: step-up is always treated as fresh (sessions/resolver.py), so no second prompt.
  const simple = useSimpleAuth() === true;
  const myId = me.data?.user.id;
  const typeFilter = (fixedType ? actionTypes?.join(",") : type) ?? "";
  const wanted = typeFilter ? new Set(typeFilter.split(",")) : null;
  const rows = list.rows?.filter((r) => !wanted || wanted.has(r.action_type));
  const [dialog, setDialog] = useState<{ kind: "approve" | "reject" | "cancel"; row: ApprovalRow } | null>(null);
  const [note, setNote] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const toggle = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const done = (msg: string) => {
    setNote("");
    toast.show({ title: msg, tone: "success" });
    void list.reload();
  };

  const body = (
    <>
      {!fixedType ? (
        <FilterBar label="Approval filters">
          <FormField label="Type">
            {(f) => (
              <Select
                {...f}
                value={type}
                onChange={(e) => setType(e.target.value)}
                options={[{ value: actionTypes?.join(",") ?? "", label: "All types" }, ...(actionTypes ?? Object.keys(ACTION_TYPES)).map((t) => ({ value: t, label: actionTypeLabel(t) }))]}
              />
            )}
          </FormField>
          <FormField label="Status">
            {(f) => (
              <Select
                {...f}
                value={status}
                onChange={(e) => setStatus(e.target.value)}
                options={["pending", "approved", "executed", "rejected", "expired", "cancelled"].map((s) => ({ value: s, label: humanize(s) }))}
              />
            )}
          </FormField>
        </FilterBar>
      ) : null}
      {list.error ? (
        <ErrorState error={list.error} onRetry={() => void list.reload()} />
      ) : !rows ? (
        <LoadingBlock label="Loading approval requests…" size="card" rows={2} />
      ) : rows.length === 0 ? (
        <EmptyState
          icon="check"
          title={status === "pending" ? "Nothing waiting for approval" : `No ${humanize(status).toLowerCase()} requests`}
          description={
            status === "pending"
              ? "Requests you can decide appear here. Your own requests show for tracking only."
              : "Choose another status to see older requests."
          }
        />
      ) : (
        <ul className="space-y-3" aria-label="Approval requests">
          {rows.map((r) => {
            const id = approvalId(r);
            const isRequester = !!myId && r.requested_by === myId && !r.self_decidable;
            const expired = r.status === "expired" || (!!r.expires_at && Date.parse(r.expires_at) < Date.now() && r.status === "pending");
            const pending = r.status === "pending" && !expired;
            return (
              <li key={id}>
                <Card
                  className={expired ? "bg-surface-sunken" : undefined}
                  title={
                    <span className="flex flex-wrap items-center gap-2">
                      {actionTypeLabel(r.action_type)}
                      <span className="font-normal text-fg-secondary">
                        · {humanize(r.target_type)}
                        {r.target_id ? ` ${shortRef(r.target_id)}` : ""}
                      </span>
                      <StateBadge state={expired ? "expired" : r.status} />
                    </span>
                  }
                >
                  <KeyValueList
                    items={[
                      { label: "Requested by", value: isRequester ? "You" : <UserRef id={r.requested_by} /> },
                      { label: "Requested", value: formatDateTime(r.created_at) },
                      { label: "Expires", value: r.expires_at ? (expired ? "Expired — request again" : `${formatTimeUntil(r.expires_at)} (${formatDateTime(r.expires_at)})`) : "—" },
                      { label: "Reason", value: r.request_reason ?? "—" },
                      ...(r.decision_note ? [{ label: "Decision note", value: r.decision_note }] : []),
                    ]}
                  />
                  <div className="mt-3">
                    <Button size="sm" variant="ghost" aria-expanded={expanded.has(id)} aria-controls={`approval-payload-${id}`} onClick={() => toggle(id)}>
                      {expanded.has(id) ? "Hide details" : "Show details"}
                    </Button>
                    {expanded.has(id) ? (
                      <div id={`approval-payload-${id}`} className="mt-2">
                        {r.payload !== undefined ? <ApprovalPayload payload={r.payload} hash={r.payload_hash} /> : <ApprovalDetail id={id} />}
                      </div>
                    ) : null}
                  </div>
                  {pending ? (
                    <div className="mt-4 flex flex-wrap items-center gap-2">
                      {isRequester ? (
                        <>
                          <p className="text-sm text-fg-secondary">You requested this, so another approver must decide.</p>
                          <Button size="sm" variant="secondary" onClick={() => setDialog({ kind: "cancel", row: r })}>
                            Cancel request
                          </Button>
                        </>
                      ) : (
                        <>
                          <Button size="sm" onClick={() => setDialog({ kind: "approve", row: r })} aria-label={`Approve ${actionTypeLabel(r.action_type)} ${id}`}>
                            Approve
                          </Button>
                          <Button size="sm" variant="secondary" onClick={() => setDialog({ kind: "reject", row: r })} aria-label={`Send back ${actionTypeLabel(r.action_type)} ${id}`}>
                            Send back
                          </Button>
                        </>
                      )}
                    </div>
                  ) : null}
                </Card>
              </li>
            );
          })}
        </ul>
      )}
      <Pagination hasMore={list.hasMore} hasPrevious={list.hasPrevious} onNext={list.next} onPrevious={list.previous} loading={list.loading} label="Approval pages" />

      <ActionDialog
        open={dialog?.kind === "approve"}
        onClose={() => setDialog(null)}
        onOpen={() => setNote("")}
        title="Approve and execute?"
        description="The change below runs exactly as requested (its integrity is re-checked first). You may be asked to confirm your identity."
        submitLabel="Approve"
        onSubmit={() => decideApproval(dialog!.row, true, note)}
        onDone={() => done("Approved.")}
      >
        {dialog?.kind === "approve" ? <ApprovalDetail id={approvalId(dialog.row)} /> : null}
        <FormField label="Note (optional)">{(f) => <TextArea {...f} value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} />}</FormField>
      </ActionDialog>
      <ActionDialog
        open={dialog?.kind === "reject"}
        onClose={() => setDialog(null)}
        onOpen={() => setNote("")}
        title="Send back"
        submitLabel="Send back"
        validate={() => (note.trim().length < 5 ? "Give a reason (5+ characters) so the requester knows what to fix." : null)}
        onSubmit={() => decideApproval(dialog!.row, false, note)}
        onDone={() => done("Sent back.")}
      >
        {dialog?.kind === "reject" ? <ApprovalDetail id={approvalId(dialog.row)} /> : null}
        <FormField label="Reason" required>{(f) => <TextArea {...f} value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} />}</FormField>
      </ActionDialog>
      <ActionDialog
        open={dialog?.kind === "cancel"}
        onClose={() => setDialog(null)}
        title="Cancel your request?"
        submitLabel="Cancel request"
        cancelLabel="Keep request"
        onSubmit={async () => toOutcome(await api.post(`admin/approvals/${approvalId(dialog!.row)}/cancel`, {}))}
        onDone={() => done("Request cancelled.")}
      />
    </>
  );

  if (embedded) return <div>{body}</div>;
  return (
    <div>
      <PageHeader eyebrow={eyebrow} title={title} description={
          description ??
          (simple
            ? "Changes that need a second person to approve. You can never approve your own request."
            : "Changes that need a second person to approve. Approving asks you to confirm again, and you can never approve your own request.")
        } />
      {body}
    </div>
  );
}
