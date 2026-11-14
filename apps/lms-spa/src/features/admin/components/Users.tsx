"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { Badge, Button, Card, Checkbox, EmptyState, ErrorState, FormField, Input, LoadingBlock, PageHeader, Pagination, Select, Table, useToast, type Column } from "@/components/ui";
import { api } from "@/lib/api/client";
import type { Body } from "@/lib/api-types";
import { useSimpleAuth } from "@/components/shell/Integrations";
import { ActionDialog, FilterBar, KeyValueList, StateBadge, TextArea, textLink } from "./console-ui";
import { cleanQuery, humanize, shortRef, toOutcome, useCursorList, useVersioned } from "../lib/console";
import { actionTypeLabel, type ApprovalRow } from "./ApprovalsQueue";
import { restrictionText, roleLabel, scopeLabel } from "./Governance";
import { useResource } from "@/lib/api/use-resource";
import { formatDate, formatDateTime } from "@/lib/format";

/** verified: app/modules/sessions/router.py REASON_CODES (required by staff session endpoints). */
const SESSION_REASON_CODES = ["ticket", "unblock_request", "case", "incident", "user_request", "legal"] as const;
const USER_STATUSES = ["active", "pending_verification", "pending_guardian_consent", "deactivated", "deleted"] as const;
/** api `status=current`: every account except erased ones. `""` (no filter) = any, including deleted. */
const CURRENT = "current";
const STATUS_FILTERS: readonly string[] = [CURRENT, "any", ...USER_STATUSES];
const STATUS_OPTIONS = [
  { value: CURRENT, label: "All (except deleted)" },
  ...USER_STATUSES.map((s) => ({ value: s, label: humanize(s) })),
  { value: "any", label: "Any, including deleted" },
];

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

/** Readable name for an account: display name, then email, then "User #9F3C21AB" (never a raw id). */
export const userName = (u: { display_name: string | null; email: string | null; user_id: string }) => u.display_name?.trim() || u.email || `User ${shortRef(u.user_id)}`;

/** Restriction level as a badge with words ("Temporarily restricted"), not a bare "L2". */
function RestrictionBadge({ level }: { level: number }) {
  if (!(level > 0)) return null;
  return <Badge tone={level >= 3 ? "danger" : "warning"}>{restrictionText(level)}</Badge>;
}

/** ADM-004 user search (ADM-02). No security evidence is shown here. */
export function UserSearch({ initialStatus = "", openAdd = false }: { initialStatus?: string; openAdd?: boolean }) {
  const [q, setQ] = useState("");
  // Default view hides erased ("Deleted user") accounts; "Any, including deleted" or "Deleted" shows them.
  const [status, setStatus] = useState(STATUS_FILTERS.includes(initialStatus) ? initialStatus : CURRENT);
  const list = useCursorList<UserRow>("admin/users", cleanQuery({ q: q.trim(), status: status === "any" ? "" : status }));
  const [addOpen, setAddOpen] = useState(openAdd);
  const cols: Column<UserRow>[] = [
    {
      key: "name",
      header: "User",
      cell: (u) => (
        <Link className={textLink} href={`/admin/users/${u.user_id}`}>
          {userName(u)}
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
          <RestrictionBadge level={u.restriction_level} />
        </span>
      ),
    },
    { key: "roles", header: "Roles", cell: (u) => (u.roles.length ? u.roles.map(roleLabel).join(", ") : "—") },
    { key: "joined", header: "Joined", priority: "secondary", cell: (u) => formatDate(u.created_at) },
    { key: "last", header: "Last sign-in", cell: (u) => formatDateTime(u.last_login_at) },
  ];
  return (
    <div>
      <PageHeader
        title="Users"
        description="Find anyone by name, email, mobile number or id, then open their account to manage access."
        actions={<Button onClick={() => setAddOpen(true)}>Add user</Button>}
      />
      <FilterBar label="User search">
        <FormField label="Search" hint="Name, email, mobile or user id">
          {(f) => <Input {...f} value={q} onChange={(e) => setQ(e.target.value)} />}
        </FormField>
        <FormField label="Status">
          {(f) => <Select {...f} value={status} onChange={(e) => setStatus(e.target.value)} options={STATUS_OPTIONS} />}
        </FormField>
      </FilterBar>
      <Table caption="Users" columns={cols} rows={list.rows} rowKey={(u) => u.user_id} loading={list.loading} error={list.error} onRetry={() => void list.reload()} empty={{ title: "No users match", description: q || status !== CURRENT ? "Check the spelling, try their email or mobile number, or clear the status filter." : "People appear here once they sign up or you add them with Add user." }} footer={<Pagination hasMore={list.hasMore} hasPrevious={list.hasPrevious} onNext={list.next} onPrevious={list.previous} />} />
      <AddUserDialog open={addOpen} onClose={() => setAddOpen(false)} onCreated={() => void list.reload()} />
    </div>
  );
}

/** Roles offered when adding a user; "" = no role yet (they can still sign in as a learner). */
const ADD_ROLES = [
  { value: "", label: "No role (learner account)" },
  { value: "student", label: "Student" },
  { value: "trainer", label: "Trainer" },
  { value: "evaluator", label: "Evaluator" },
  { value: "content_manager", label: "Content manager" },
  { value: "super_admin", label: "Admin (needs approval in Approvals)" },
] as const;
/** Simple authentication: plain role names ("Admin", not "Admin (needs approval in Approvals)"). */
const roleOptions = (simple: boolean | null) => ADD_ROLES.map((r) => ({ value: r.value, label: simple && r.value === "super_admin" ? "Admin" : r.label }));
/** Roles that only apply to a batch (verified: rbac/catalogue.py allowed scopes; Trainer has no platform scope). */
const BATCH_ONLY_ROLES = new Set(["trainer"]);

interface CreatedUser {
  user_id: string;
  status: string;
  role: { role_key: string; status: "granted" | "approval_pending"; approval_request_id?: string } | null;
}

const EMPTY_NEW_USER = { full_name: "", email: "", mobile: "", password: "", must_change_password: false, role_key: "", batch_id: "", reason: "", confirm_adult: false };
const ADD_USER_DRAFT_KEY = "td-admin-add-user-draft";
const isEmptyDraft = (f: typeof EMPTY_NEW_USER) => Object.entries(f).every(([k, v]) => v === EMPTY_NEW_USER[k as keyof typeof EMPTY_NEW_USER]);
const PW_WORDS = ["river", "maple", "comet", "harbor", "violet", "cedar", "falcon", "amber", "orbit", "lotus", "summit", "pixel"];
const rand = (n: number) => (crypto.getRandomValues(new Uint32Array(1))[0] ?? 0) % n;

/** ADM-06: create an account with a starting password and (optionally) a role in one step. */
export function AddUserDialog({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated?: () => void }) {
  const router = useRouter();
  const toast = useToast();
  const simple = useSimpleAuth();
  // Owner request 2026-11-11: what was typed stays until the account is created or "Clear form" is
  // pressed (closing the dialog or clicking outside it keeps the draft). The draft also survives a
  // reload of this tab (sessionStorage), WITHOUT the password, which is never stored.
  const [form, setForm] = useState<typeof EMPTY_NEW_USER>(() => {
    try {
      const raw = typeof window === "undefined" ? null : window.sessionStorage.getItem(ADD_USER_DRAFT_KEY);
      return raw ? { ...EMPTY_NEW_USER, ...(JSON.parse(raw) as Partial<typeof EMPTY_NEW_USER>), password: "" } : EMPTY_NEW_USER;
    } catch {
      return EMPTY_NEW_USER;
    }
  });
  useEffect(() => {
    try {
      const { password: _pw, ...draft } = form;
      void _pw;
      if (isEmptyDraft(form)) window.sessionStorage.removeItem(ADD_USER_DRAFT_KEY);
      else window.sessionStorage.setItem(ADD_USER_DRAFT_KEY, JSON.stringify(draft));
    } catch {
      /* private mode / storage blocked: the in-memory draft still works */
    }
  }, [form]);
  const clearForm = () => setForm(EMPTY_NEW_USER);
  const needsBatch = BATCH_ONLY_ROLES.has(form.role_key);
  const batches = useResource<{ data: { id: string; name: string; code: string; status: string }[] }>(open && needsBatch ? "batches" : null);
  const batchOptions = (batches.data?.data ?? []).filter((b) => b.status !== "archived").map((b) => ({ value: b.id, label: `${b.name} (${b.code})` }));
  const set = (k: "full_name" | "email" | "mobile" | "password" | "batch_id" | "reason") => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const suggestPassword = () => setForm((f) => ({ ...f, password: `${PW_WORDS[rand(12)]}-${PW_WORDS[rand(12)]}-${PW_WORDS[rand(12)]}-${10 + rand(90)}` }));
  return (
    <ActionDialog<CreatedUser>
      open={open}
      onClose={onClose}
      title="Add user"
      description="Creates a ready-to-use account. Give the person their email and starting password; they can change the password after signing in."
      submitLabel="Create account"
      validate={() =>
        form.full_name.trim().length < 2
          ? "Enter their full name."
          : !/^\S+@\S+\.\S+$/.test(form.email.trim())
            ? "Enter a valid email address."
            : form.password.length < 6
              ? "The starting password must be at least 6 characters."
              : needsBatch && !form.batch_id
                ? "Choose the batch this trainer will teach."
                : form.reason.trim().length < 5
                  ? "Give a reason (5+ characters)."
                  : !form.confirm_adult
                    ? "Confirm the person is 18 or older."
                    : null
      }
      onSubmit={async () =>
        toOutcome(
          await api.post<CreatedUser>(
            "admin/users",
            {
              full_name: form.full_name.trim(),
              email: form.email.trim(),
              mobile: form.mobile.trim() || null,
              password: form.password,
              must_change_password: form.must_change_password,
              role_key: form.role_key || null,
              scope_type: needsBatch ? "batch" : "platform",
              scope_id: needsBatch ? form.batch_id : null,
              reason: form.reason.trim(),
              confirm_adult: form.confirm_adult,
            } satisfies Body<"admin/users", "post"> & { must_change_password: boolean },
            { idempotencyKey: true },
          ),
        )
      }
      onDone={(outcome) => {
        if (outcome.kind !== "ok") return;
        clearForm();
        const created = outcome.data;
        const pendingRole = created.role?.status === "approval_pending";
        toast.show({
          title: "Account created",
          description: pendingRole ? "The Admin role is waiting in Approvals (approve it there; with two or more admins another admin must). Share the email and starting password with the person." : "Share the email and starting password with the person.",
          tone: "success",
        });
        onCreated?.();
        router.push(`/admin/users/${created.user_id}`);
      }}
    >
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-surface-sunken px-3 py-2 text-sm text-fg-secondary">
        <span>Your entries are kept until you create the account.</span>
        <Button type="button" variant="ghost" size="sm" onClick={clearForm} disabled={isEmptyDraft(form)}>
          Clear form
        </Button>
      </div>
      <FormField label="Full name" required>
        {(f) => <Input {...f} value={form.full_name} onChange={set("full_name")} autoComplete="off" />}
      </FormField>
      <FormField label="Email" required hint="They sign in with this.">
        {(f) => <Input {...f} type="email" value={form.email} onChange={set("email")} autoComplete="off" />}
      </FormField>
      <FormField label="Mobile number" hint="Optional">
        {(f) => <Input {...f} type="tel" inputMode="tel" value={form.mobile} onChange={set("mobile")} autoComplete="off" />}
      </FormField>
      <FormField label="Starting password" required hint="At least 6 characters. Tip: Suggest makes a strong one.">
        {(f) => (
          <div className="flex gap-2">
            <Input {...f} value={form.password} onChange={set("password")} autoComplete="new-password" className="min-w-0 flex-1" />
            <Button variant="secondary" onClick={suggestPassword}>
              Suggest
            </Button>
          </div>
        )}
      </FormField>
      <Checkbox
        label="Must change password on first login"
        description="They'll be asked to choose their own password right after signing in."
        checked={form.must_change_password}
        onChange={(e) => setForm((f) => ({ ...f, must_change_password: e.target.checked }))}
      />
      <FormField label="Role" hint={form.role_key === "super_admin" ? "Admin access starts after the request is approved in Approvals. While you are the only Admin you approve it yourself; otherwise another Admin must." : "You can change roles later in Roles."}>
        {(f) => <Select {...f} value={form.role_key} onChange={(e) => setForm((prev) => ({ ...prev, role_key: e.target.value, batch_id: "" }))} options={roleOptions(simple)} />}
      </FormField>
      {needsBatch ? (
        <FormField label="Batch" required error={batches.error ? "Batches could not be loaded." : undefined} hint={!batches.loading && !batchOptions.length ? "No open batches yet. Create one in Batches first." : undefined}>
          {(f) => <Select {...f} value={form.batch_id} onChange={set("batch_id")} placeholder={batches.loading ? "Loading batches…" : "Choose a batch"} options={batchOptions} />}
        </FormField>
      ) : null}
      <FormField label="Reason" required hint="Kept in the audit log, for example: New trainer for the March batch.">
        {(f) => <TextArea {...f} value={form.reason} onChange={set("reason")} />}
      </FormField>
      <Checkbox
        label="This person is 18 or older"
        description="Under-18 learners must sign up themselves so a parent can give consent."
        checked={form.confirm_adult}
        onChange={(e) => setForm((f) => ({ ...f, confirm_adult: e.target.checked }))}
      />
    </ActionDialog>
  );
}

type Action = "revoke" | "deactivate" | "reactivate" | "mfa";

/**
 * ADM-004 user account view (ADM-03): status, grants, MFA, sessions; deactivate / reactivate
 * (ADM-04, step-up), MFA reset (ADM-05, dual control) and session kill (SES-10).
 */
/** verified: app/modules/sessions/router.py _devices_payload (GET users/{id}/devices). */
interface AdminDevice {
  user_device_id: string;
  label: string | null;
  user_label?: string | null;
  trust_status?: string;
  last_used_at?: string | null;
}
interface AdminDevicesPayload {
  data: AdminDevice[];
  limits?: { max_trusted?: number; trusted_counted?: number; support_resets_used_30d?: number };
}
const adminDeviceName = (d: AdminDevice) => d.user_label ?? d.label ?? "Device";

/**
 * Trusted devices of a user for an Admin acting on the person's own request (reason_code
 * `user_request`). Loaded only when the admin opens it, because every view is audited with that
 * reason. Reset = POST users/{id}/devices/{device}/reset (Admin may go beyond the support quota).
 * Support staff use the ticket-based lookup at /desk/users/{id} instead.
 */
export function UserDevices({ userId }: { userId: string }) {
  const toast = useToast();
  const [shown, setShown] = useState(false);
  const query = useMemo(() => ({ reason_code: "user_request" }), []);
  const devices = useVersioned<AdminDevicesPayload>(shown ? `users/${userId}/devices` : null, query);
  const [reset, setReset] = useState<AdminDevice | null>(null);
  const [reason, setReason] = useState("");
  return (
    <Card
      title="Devices"
      description="Trusted devices this person signs in from. Opening the list is recorded in the audit log as a request from the user."
      actions={
        shown ? null : (
          <Button size="sm" variant="secondary" onClick={() => setShown(true)}>
            Show devices
          </Button>
        )
      }
    >
      {!shown ? null : devices.error ? (
        <ErrorState error={devices.error} onRetry={() => void devices.reload()} />
      ) : !devices.data ? (
        <LoadingBlock label="Loading devices…" rows={2} />
      ) : (
        <Table
          caption="Devices"
          columns={[
            { key: "label", header: "Device", cell: (d) => adminDeviceName(d) },
            { key: "trust", header: "Trust", cell: (d) => humanize(d.trust_status ?? "") },
            { key: "used", header: "Last used", cell: (d) => formatDateTime(d.last_used_at) },
            {
              key: "act",
              header: <span className="sr-only">Actions</span>,
              cell: (d) => (
                <Button size="sm" variant="secondary" onClick={() => setReset(d)} aria-label={`Reset ${adminDeviceName(d)}`}>
                  Reset device
                </Button>
              ),
            },
          ]}
          rows={devices.data.data}
          rowKey={(d) => d.user_device_id}
          empty={{ title: "No devices", description: "This person has not signed in on any device yet.", icon: "lock" }}
        />
      )}
      <ActionDialog
        open={reset !== null}
        onClose={() => setReset(null)}
        onOpen={() => setReason("")}
        title={`Reset ${reset ? adminDeviceName(reset) : "device"}?`}
        description="Removes this trusted device and signs it out, so the person can add a new one. Use it when they ask (lost or replaced device)."
        submitLabel="Reset device"
        danger
        validate={() => (reason.trim().length < 5 ? "Give a reason (5+ characters)." : null)}
        onSubmit={async () =>
          toOutcome(
            await api.post(
              `users/${userId}/devices/${reset!.user_device_id}/reset`,
              { reason_code: "user_request", reason: reason.trim() } satisfies Body<"users/{user_id}/devices/{user_device_id}/reset", "post">,
              { idempotencyKey: true },
            ),
          )
        }
        onDone={(o) => {
          if (o.kind === "ok") toast.show({ title: "Device reset.", tone: "success" });
          setReason("");
          void devices.reload();
        }}
      >
        <FormField label="Reason" required>{(f) => <TextArea {...f} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} />}</FormField>
      </ActionDialog>
    </Card>
  );
}

export function UserDetail({ userId }: { userId: string }) {
  const toast = useToast();
  const user = useResource<UserAccount>(`admin/users/${userId}`);
  const simple = useSimpleAuth();
  const [action, setAction] = useState<Action | null | "password">(null);
  const [newPassword, setNewPassword] = useState("");
  // An admin-set password should usually be replaced by the person: on by default.
  const [mustChange, setMustChange] = useState(true);
  const [reason, setReason] = useState("");
  const [reasonCode, setReasonCode] = useState<string>("ticket");
  const [method, setMethod] = useState("video_call");
  const crumbs = (label: string) => [{ label: "Users", href: "/admin/users" }, { label }];
  if (user.error)
    return (
      <div>
        <PageHeader breadcrumbs={crumbs("Account")} title="Account" />
        <ErrorState error={user.error} onRetry={() => void user.reload()} />
      </div>
    );
  if (!user.data)
    return (
      <div>
        <PageHeader breadcrumbs={crumbs("Account")} title="Account" />
        <LoadingBlock label="Loading the account…" size="card" rows={3} />
      </div>
    );
  const u = user.data;
  const name = userName(u);
  const deactivated = u.status === "deactivated";
  const close = () => {
    setAction(null);
    setReason("");
  };
  // Every action dialog opens with fresh fields (audit 0.5).
  const fresh = () => {
    setReason("");
    setReasonCode("ticket");
    setMethod("video_call");
  };
  const done = (msg: string) => {
    toast.show({ title: msg, tone: "success" });
    setReason("");
    void user.reload();
  };

  return (
    <div>
      <PageHeader
        breadcrumbs={crumbs(name)}
        title={name}
        meta={
          <>
            <StateBadge state={u.status} />
            <RestrictionBadge level={u.restriction_level} />
          </>
        }
        description={[u.display_name ? u.email : null, `Account ${shortRef(u.user_id)}`].filter(Boolean).join(" · ")}
        actions={
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" onClick={() => setAction("revoke")}>
              Revoke sessions
            </Button>
            {u.status === "active" ? (
              <Button variant="secondary" onClick={() => setAction("password")}>
                Set new password
              </Button>
            ) : null}
            {u.mfa.enrolled && !simple ? (
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
            { label: "Restriction", value: restrictionText(u.restriction_level) },
            { label: "Origin", value: humanize(u.account_origin) },
            ...(simple ? [] : [{ label: "MFA", value: u.mfa.enrolled ? u.mfa.factors.map((f) => humanize(f.factor_type)).join(", ") : "Not enrolled" }]),
            { label: "Active sessions", value: String(u.sessions.active) },
            { label: "Joined", value: formatDate(u.created_at) },
            { label: "Last sign-in", value: formatDateTime(u.last_login_at) },
            { label: "Break-glass", value: u.break_glass_active ? <Badge tone="danger">Active</Badge> : "No" },
            { label: "User id", key: "id", value: <span className="select-all break-all font-mono text-xs">{u.user_id}</span>, wide: true },
          ]}
        />
      </Card>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card title="Role grants" actions={<Link className={`${textLink} inline-flex min-h-6 items-center text-sm`} href={`/admin/roles?user_id=${userId}`}>Manage</Link>}>
          {u.grants.length ? (
            <ul className="space-y-1 text-sm">
              {u.grants.map((g) => (
                <li key={g.grant_id}>
                  <span className="font-medium">{roleLabel(g.role)}</span> · {scopeLabel(g.scope_type, g.scope_id)}
                  {g.expires_at ? ` · until ${formatDateTime(g.expires_at)}` : ""}
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState variant="inline" icon="users" title="No roles yet" description="This person has the standard student access only. Use Manage to grant a role." />
          )}
        </Card>
        {simple ? null : <UserDevices userId={userId} />}
        {u.pending_approvals.length ? (
          <Card title="Pending approvals for this user" className="lg:col-span-2">
            <ul className="space-y-1 text-sm">
              {u.pending_approvals.map((a) => (
                <li key={a.approval_request_id}>
                  {actionTypeLabel(a.action_type)} · {a.request_reason ?? "—"} · expires {formatDateTime(a.expires_at)}{" "}
                  <Link className={`${textLink} inline-flex min-h-6 items-center`} href="/admin/approvals">
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
        onOpen={fresh}
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
        onOpen={fresh}
        title={action === "deactivate" ? "Deactivate this account?" : "Reactivate this account?"}
        description={`${action === "deactivate" ? "The user is signed out everywhere and cannot sign in until reactivated." : "The user can sign in again."}${simple ? "" : " Needs a fresh step-up."}`}
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
        open={action === "password"}
        onClose={() => {
          close();
          setNewPassword("");
        }}
        onOpen={() => {
          fresh();
          setNewPassword("");
          setMustChange(true);
        }}
        title="Set a new password"
        description={`Use this when the person can't reset it themselves (for example while email isn't connected). They are signed out everywhere and sign in with this password. Share it with them privately.${simple ? "" : " Needs a fresh step-up."}`}
        submitLabel="Set password"
        validate={() => (newPassword.length < 6 ? "The password must be at least 6 characters." : reason.trim().length < 5 ? "Give a reason (5+ characters)." : null)}
        onSubmit={async () => toOutcome(await api.post(`admin/users/${userId}/password`, { password: newPassword, reason: reason.trim(), must_change_password: mustChange }, { idempotencyKey: true }))}
        onDone={(o) => {
          if (o.kind === "ok") {
            setNewPassword("");
            done(mustChange ? "New password set. Share it with the person; they'll choose their own after signing in." : "New password set. Share it with the person.");
          }
        }}
      >
        <FormField label="New password" required hint="At least 6 characters.">
          {(f) => (
            <div className="flex gap-2">
              <Input {...f} value={newPassword} onChange={(e) => setNewPassword(e.target.value)} autoComplete="new-password" />
              <Button
                type="button"
                variant="secondary"
                onClick={() => setNewPassword(`${PW_WORDS[rand(12)]}-${PW_WORDS[rand(12)]}-${10 + rand(90)}`)}
              >
                Suggest
              </Button>
            </div>
          )}
        </FormField>
        <Checkbox
          label="Must change password on first login"
          description="They'll be asked to choose their own password right after signing in."
          checked={mustChange}
          onChange={(e) => setMustChange(e.target.checked)}
        />
        <FormField label="Reason" required>{(f) => <TextArea {...f} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={1000} />}</FormField>
      </ActionDialog>

      <ActionDialog
        open={action === "mfa"}
        onClose={close}
        onOpen={fresh}
        title="Reset MFA?"
        description="Removes all MFA factors after you have verified the person's identity. A different admin must approve before it runs."
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
