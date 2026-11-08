"use client";

import Link from "next/link";
import { useState } from "react";
import { Badge, Button, Card, ErrorState, FormField, Input, PageHeader, Pagination, Select, Skeleton, Table, useToast, type Column } from "@/components/ui";
import { api } from "@/lib/api/client";
import type { Body } from "@/lib/api-types";
import { useResource } from "@/features/account/lib/use-resource";
import { ActionDialog, FilterBar, KeyValueList, StateBadge, TextArea, textLink } from "./console-ui";
import { cleanQuery, formatDate, formatDateTime, humanize, toOutcome, useCursorList } from "../lib/console";
import type { ApprovalRow } from "./ApprovalsQueue";

/** verified: app/modules/sessions/router.py REASON_CODES (required by staff session endpoints). */
const SESSION_REASON_CODES = ["ticket", "unblock_request", "case", "incident", "user_request", "legal"] as const;
const USER_STATUSES = ["active", "pending_verification", "pending_guardian_consent", "deactivated", "deleted"] as const;

/** ADM-02 row (app/modules/admin user search). */
interface UserRow {
  user_id: string;
  display_name: string | null;
  email: string | null;
  phone_masked: string | null;
  status: string;
  is_minor: boolean;
  restriction_level: number;
  roles: string[];
  created_at: string;
  last_login_at: string | null;
}

/** ADM-03 account view. */
interface UserAccount {
  user_id: string;
  display_name: string | null;
  email: string | null;
  phone_masked: string | null;
  status: string;
  privacy_tier: string | null;
  is_minor: boolean;
  email_verified_at: string | null;
  phone_verified_at: string | null;
  restriction_level: number;
  account_origin: string;
  created_at: string;
  last_login_at: string | null;
  grants: { grant_id: string; role: string; scope_type: string; scope_id: string | null; expires_at: string | null }[];
  mfa: { enrolled: boolean; factors: { factor_type: string; created_at: string | null; last_used_at: string | null }[] };
  sessions: { active: number };
  pending_approvals: ApprovalRow[];
  break_glass_active: boolean;
}

/** ADM-004 user search (ADM-02). No security evidence is shown here. */
export function UserSearch() {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const list = useCursorList<UserRow>("admin/users", cleanQuery({ q: q.trim(), status }));
  const cols: Column<UserRow>[] = [
    {
      key: "name",
      header: "User",
      cell: (u) => (
        <Link className={textLink} href={`/admin/users/${u.user_id}`}>
          {u.display_name ?? u.user_id}
        </Link>
      ),
    },
    { key: "contact", header: "Contact", cell: (u) => [u.email, u.phone_masked].filter(Boolean).join(" · ") || "—" },
    {
      key: "status",
      header: "Status",
      cell: (u) => (
        <span className="flex flex-wrap items-center gap-1">
          <StateBadge state={u.status} />
          {u.is_minor ? <Badge tone="warning">Minor</Badge> : null}
          {u.restriction_level > 0 ? <Badge tone="danger">L{u.restriction_level}</Badge> : null}
        </span>
      ),
    },
    { key: "roles", header: "Roles", cell: (u) => (u.roles.length ? u.roles.map(humanize).join(", ") : "—") },
    { key: "joined", header: "Joined", cell: (u) => formatDate(u.created_at) },
    { key: "last", header: "Last sign-in", cell: (u) => formatDateTime(u.last_login_at) },
  ];
  return (
    <div>
      <PageHeader eyebrow="ADM-004" title="Users" description="Security evidence is not shown here." />
      <FilterBar label="User search">
        <FormField label="Search" hint="Name, email, mobile or user id">
          {(f) => <Input {...f} value={q} onChange={(e) => setQ(e.target.value)} />}
        </FormField>
        <FormField label="Status">
          {(f) => <Select {...f} value={status} onChange={(e) => setStatus(e.target.value)} options={[{ value: "", label: "Any" }, ...USER_STATUSES.map((s) => ({ value: s, label: humanize(s) }))]} />}
        </FormField>
      </FilterBar>
      <Table caption="Users" columns={cols} rows={list.rows} rowKey={(u) => u.user_id} loading={list.loading} error={list.error} onRetry={() => void list.reload()} empty={{ title: "No users match" }} footer={<Pagination hasMore={list.hasMore} hasPrevious={list.hasPrevious} onNext={list.next} onPrevious={list.previous} />} />
    </div>
  );
}

type Action = "revoke" | "deactivate" | "reactivate" | "mfa";

/**
 * ADM-004 user account view (ADM-03): status, grants, MFA, sessions; deactivate / reactivate
 * (ADM-04, step-up), MFA reset (ADM-05, dual control) and session kill (SES-10).
 */
export function UserDetail({ userId }: { userId: string }) {
  const toast = useToast();
  const user = useResource<UserAccount>(`admin/users/${userId}`);
  const [action, setAction] = useState<Action | null>(null);
  const [reason, setReason] = useState("");
  const [reasonCode, setReasonCode] = useState<string>("ticket");
  const [method, setMethod] = useState("video_call");
  if (user.error) return <ErrorState error={user.error} onRetry={() => void user.reload()} />;
  if (!user.data) return <Skeleton className="h-40 w-full" />;
  const u = user.data;
  const deactivated = u.status === "deactivated";
  const close = () => {
    setAction(null);
    setReason("");
  };
  const done = (msg: string) => {
    toast.show({ title: msg, tone: "success" });
    setReason("");
    void user.reload();
  };

  return (
    <div>
      <PageHeader
        eyebrow="ADM-004"
        title={u.display_name ?? "User"}
        description={<span className="font-mono text-xs">{u.user_id}</span>}
        actions={
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" onClick={() => setAction("revoke")}>
              Revoke sessions
            </Button>
            {u.mfa.enrolled ? (
              <Button variant="secondary" onClick={() => setAction("mfa")}>
                Reset MFA
              </Button>
            ) : null}
            {deactivated ? (
              <Button onClick={() => setAction("reactivate")}>Reactivate</Button>
            ) : u.status !== "deleted" ? (
              <Button variant="danger" onClick={() => setAction("deactivate")}>
                Deactivate
              </Button>
            ) : null}
          </div>
        }
      />
      <Card className="mb-4">
        <KeyValueList
          items={[
            { label: "Status", value: <StateBadge state={u.status} /> },
            { label: "Privacy tier", value: u.is_minor ? <Badge tone="warning">Minor</Badge> : humanize(u.privacy_tier ?? "adult") },
            { label: "Email", value: `${u.email ?? "—"}${u.email ? (u.email_verified_at ? " · verified" : " · not verified") : ""}` },
            { label: "Mobile", value: `${u.phone_masked ?? "—"}${u.phone_masked ? (u.phone_verified_at ? " · verified" : " · not verified") : ""}` },
            { label: "Restriction level", value: u.restriction_level > 0 ? `L${u.restriction_level}` : "None" },
            { label: "Origin", value: humanize(u.account_origin) },
            { label: "MFA", value: u.mfa.enrolled ? u.mfa.factors.map((f) => humanize(f.factor_type)).join(", ") : "Not enrolled" },
            { label: "Active sessions", value: String(u.sessions.active) },
            { label: "Joined", value: formatDate(u.created_at) },
            { label: "Last sign-in", value: formatDateTime(u.last_login_at) },
            { label: "Break-glass", value: u.break_glass_active ? <Badge tone="danger">Active</Badge> : "No" },
          ]}
        />
      </Card>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card title="Role grants" actions={<Link className={textLink} href={`/admin/roles?user_id=${userId}`}>Manage</Link>}>
          {u.grants.length ? (
            <ul className="space-y-1 text-sm">
              {u.grants.map((g) => (
                <li key={g.grant_id}>
                  {humanize(g.role)} @ {g.scope_type}
                  {g.scope_id ? `:${g.scope_id}` : ""}
                  {g.expires_at ? ` · until ${formatDateTime(g.expires_at)}` : ""}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-fg-muted">No grants.</p>
          )}
        </Card>
        {u.pending_approvals.length ? (
          <Card title="Pending approvals for this user" className="lg:col-span-2">
            <ul className="space-y-1 text-sm">
              {u.pending_approvals.map((a) => (
                <li key={a.approval_request_id}>
                  {humanize(a.action_type)} · {a.request_reason ?? "—"} · expires {formatDateTime(a.expires_at)}{" "}
                  <Link className={textLink} href="/admin/approvals">
                    Open queue
                  </Link>
                </li>
              ))}
            </ul>
          </Card>
        ) : null}
      </div>

      <ActionDialog
        open={action === "revoke"}
        onClose={close}
        title="Revoke all sessions?"
        submitLabel="Revoke"
        danger
        validate={() => (reason.trim().length < 10 ? "Give a reason (10+ characters)." : null)}
        onSubmit={async () =>
          toOutcome(
            await api.post<{ revoked: number }>(
              `users/${userId}/sessions/revoke`,
              { session_id: null, all: true, reason_code: reasonCode, reason: reason.trim() } satisfies Body<"users/{user_id}/sessions/revoke", "post">,
            ),
          )
        }
        onDone={(o) => {
          if (o.kind === "ok") done(`Revoked ${o.data.revoked} sessions.`);
        }}
      >
        <FormField label="Reason code" required>
          {(f) => <Select {...f} value={reasonCode} onChange={(e) => setReasonCode(e.target.value)} options={SESSION_REASON_CODES.map((c) => ({ value: c, label: humanize(c) }))} />}
        </FormField>
        <FormField label="Reason" required>{(f) => <TextArea {...f} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} />}</FormField>
      </ActionDialog>

      <ActionDialog
        open={action === "deactivate" || action === "reactivate"}
        onClose={close}
        title={action === "deactivate" ? "Deactivate this account?" : "Reactivate this account?"}
        description={action === "deactivate" ? "The user is signed out everywhere and cannot sign in until reactivated. Needs a fresh step-up." : "The user can sign in again. Needs a fresh step-up."}
        submitLabel={action === "deactivate" ? "Deactivate" : "Reactivate"}
        danger={action === "deactivate"}
        validate={() => (reason.trim().length < 5 ? "Give a reason (5+ characters)." : null)}
        onSubmit={async () => toOutcome(await api.post<{ user_id: string; status: string }>(`admin/users/${userId}/${action === "deactivate" ? "deactivate" : "reactivate"}`, { reason: reason.trim() }, { idempotencyKey: true }))}
        onDone={(o) => {
          if (o.kind === "ok") done(o.data.status === "deactivated" ? "Account deactivated." : "Account reactivated.");
        }}
      >
        <FormField label="Reason" required>{(f) => <TextArea {...f} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={1000} />}</FormField>
      </ActionDialog>

      <ActionDialog
        open={action === "mfa"}
        onClose={close}
        title="Reset MFA?"
        description="Removes all MFA factors after you have verified the person's identity. A different security reviewer or super admin must approve before it runs."
        submitLabel="Request reset"
        danger
        validate={() => (reason.trim().length < 10 ? "Describe how identity was verified (10+ characters)." : null)}
        onSubmit={async () => toOutcome(await api.post(`admin/users/${userId}/mfa-reset`, { reason: reason.trim(), verification_method: method }, { idempotencyKey: true }))}
        onDone={(o) => {
          if (o.kind === "approval_pending") {
            toast.show({ title: "Sent for approval.", tone: "success" });
            void user.reload();
          }
        }}
      >
        <FormField label="Identity verified by" required>
          {(f) => (
            <Select
              {...f}
              value={method}
              onChange={(e) => setMethod(e.target.value)}
              options={[
                { value: "video_call", label: "Video call" },
                { value: "document", label: "Document check" },
                { value: "known_contact", label: "Verified contact" },
              ]}
            />
          )}
        </FormField>
        <FormField label="Reason" required>{(f) => <TextArea {...f} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={1000} />}</FormField>
      </ActionDialog>
    </div>
  );
}
