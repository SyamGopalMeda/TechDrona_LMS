"use client";

import { useState } from "react";
import { Badge, Button, Card, ErrorState, FormField, Input, PageHeader, Pagination, Select, Skeleton, StatTile, Table, useToast, type Column } from "@/components/ui";
import { api } from "@/lib/api/client";
import type { Body, Schema } from "@/lib/api-types";
import { useResource } from "@/features/account/lib/use-resource";
import { ActionDialog, FilterBar, InlineProblem, JsonBlock, KeyValueList, StateBadge, TextArea } from "./console-ui";
import { cleanQuery, formatCountdown, formatDate, formatDateTime, formatINR, humanize, toOutcome, useCursorList } from "../lib/console";

/** The api types these filters as UUIDs (a partial id would be a 422), so only complete ones are sent. */
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const uuidOrEmpty = (v: string) => (UUID_RE.test(v.trim()) ? v.trim() : "");

/** verified: app/modules/rbac/router.py list_roles (GET rbac/roles → {data}); `dual_control` = rbac/service.py is_dual_role. */
interface RoleOut {
  role_key: string;
  name: string;
  session_tier: string;
  mfa_required: boolean;
  allowed_scope_types: string[];
  dual_control: boolean;
}

/** One id per line (or comma separated); returns the ids and any that are not UUIDs. */
export function parseIdList(text: string): { ids: string[]; invalid: string[] } {
  const ids = Array.from(new Set(text.split(/[\s,]+/).map((v) => v.trim()).filter(Boolean)));
  return { ids, invalid: ids.filter((v) => !UUID_RE.test(v)) };
}

/* ------------------------------------------------------------- Role grants */

/**
 * Single-company target roles (owner decision D2): Admin (`super_admin`), Trainer, Evaluator,
 * Content manager, Student. Other role keys the api may still list are hidden from the pickers.
 */
export const TARGET_ROLES = ["super_admin", "trainer", "evaluator", "content_manager", "student"] as const;
const ROLE_LABELS: Record<string, string> = { super_admin: "Admin", trainer: "Trainer", evaluator: "Evaluator", content_manager: "Content manager", student: "Student" };
export const roleLabel = (key: string | null | undefined) => (key ? (ROLE_LABELS[key] ?? humanize(key)) : "—");
/** Grant scopes without `organization` (there is one company). */
const SCOPE_TYPES = ["platform", "batch", "course"];

/** verified: app/modules/rbac/router.py _grant_out (GET rbac/grants lists active grants only, {data}, unpaginated). */
interface Grant {
  grant_id: string;
  user_id: string;
  role_key: string;
  scope_type: string;
  scope_id: string | null;
  organization_id: string | null;
  granted_by: string;
  granted_at: string;
  expires_at: string | null;
  reason: string | null;
}

/** ADM-005 role grants (RBAC-03/04/05). Privileged roles are Dual; SoD-10 conflicts come back as `sod_violation`. */
export function RoleGrants({ initialUserId = "" }: { initialUserId?: string }) {
  const [userId, setUserId] = useState(initialUserId);
  const [role, setRole] = useState("");
  const list = useCursorList<Grant>("rbac/grants", cleanQuery({ user_id: uuidOrEmpty(userId), role }));
  const [grantOpen, setGrantOpen] = useState(false);
  const [revoke, setRevoke] = useState<Grant | null>(null);
  const [revokeReason, setRevokeReason] = useState("");
  const [form, setForm] = useState({ user_id: initialUserId, role_key: "", scope_type: "platform", scope_id: "", expires_at: "", reason: "" });
  const rolesRes = useResource<{ data: RoleOut[] }>("rbac/roles");
  const roles = rolesRes.data?.data ?? [];
  const isPrivileged = (key: string) => roles.some((r) => r.role_key === key && r.dual_control);
  const roleOptions = roles.filter((r) => (TARGET_ROLES as readonly string[]).includes(r.role_key)).map((r) => ({ value: r.role_key, label: roleLabel(r.role_key) }));
  const scopeTypes = (roles.find((r) => r.role_key === form.role_key)?.allowed_scope_types ?? SCOPE_TYPES).filter((s) => SCOPE_TYPES.includes(s));
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const cols: Column<Grant>[] = [
    { key: "user", header: "User", cell: (g) => <span className="font-mono text-xs">{g.user_id}</span> },
    {
      key: "role",
      header: "Role",
      cell: (g) => (
        <span className="flex items-center gap-1">
          {roleLabel(g.role_key)}
          {isPrivileged(g.role_key) ? <Badge tone="warning">Privileged</Badge> : null}
        </span>
      ),
    },
    { key: "scope", header: "Scope", cell: (g) => `${g.scope_type}${g.scope_id ? `:${g.scope_id}` : ""}` },
    { key: "exp", header: "Expires", cell: (g) => (g.expires_at ? formatDate(g.expires_at) : "Never") },
    { key: "granted", header: "Granted", cell: (g) => formatDate(g.granted_at) },
    {
      key: "act",
      header: <span className="sr-only">Actions</span>,
      cell: (g) => (
        <Button size="sm" variant="secondary" onClick={() => setRevoke(g)} aria-label={`Revoke ${g.role_key} from ${g.user_id}`}>
          Revoke
        </Button>
      ),
    },
  ];

  return (
    <div>
      <PageHeader eyebrow="ADM-005" title="Role grants" description="Granting or revoking forces the grantee to sign in again. Admin grants need a second admin (maker ≠ checker)." actions={<Button onClick={() => setGrantOpen(true)}>Grant role</Button>} />
      <FilterBar label="Grant filters">
        <FormField label="User id">{(f) => <Input {...f} value={userId} onChange={(e) => setUserId(e.target.value)} />}</FormField>
        <FormField label="Role">{(f) => <Select {...f} value={role} onChange={(e) => setRole(e.target.value)} options={[{ value: "", label: "Any" }, ...roleOptions]} />}</FormField>
      </FilterBar>
      <Table caption="Role grants" columns={cols} rows={list.rows} rowKey={(g) => g.grant_id} loading={list.loading} error={list.error} onRetry={() => void list.reload()} empty={{ title: "No grants match" }} footer={<Pagination hasMore={list.hasMore} hasPrevious={list.hasPrevious} onNext={list.next} onPrevious={list.previous} />} />
      <ActionDialog
        open={grantOpen}
        onClose={() => setGrantOpen(false)}
        title="Grant a role"
        description={isPrivileged(form.role_key) ? "This is a privileged role: another admin must approve (dual control)." : "Takes effect at the grantee's next sign-in."}
        submitLabel={isPrivileged(form.role_key) ? "Request grant" : "Grant"}
        validate={() => (!form.user_id.trim() ? "Enter the user id." : !form.role_key ? "Choose a role." : form.scope_type !== "platform" && !form.scope_id.trim() ? "Enter the scope id." : form.reason.trim().length < 5 ? "Give a reason." : null)}
        onSubmit={async () =>
          toOutcome(
            await api.post(
              "rbac/grants",
              { user_id: form.user_id.trim(), role_key: form.role_key, scope_type: form.scope_type, scope_id: form.scope_type === "platform" ? null : form.scope_id.trim(), expires_at: form.expires_at ? new Date(`${form.expires_at}T23:59:59+05:30`).toISOString() : null, reason: form.reason.trim() } satisfies Body<"rbac/grants", "post">,
              { idempotencyKey: true },
            ),
          )
        }
        onDone={() => void list.reload()}
      >
        <FormField label="User id" required>{(f) => <Input {...f} value={form.user_id} onChange={set("user_id")} />}</FormField>
        <FormField label="Role" required error={rolesRes.error ? "Roles could not be loaded." : undefined}>
          {(f) => (
            <Select
              {...f}
              value={form.role_key}
              onChange={(e) => {
                const key = e.target.value;
                const allowed = roles.find((r) => r.role_key === key)?.allowed_scope_types;
                setForm((prev) => ({ ...prev, role_key: key, scope_type: allowed && !allowed.includes(prev.scope_type) ? (allowed[0] ?? prev.scope_type) : prev.scope_type }));
              }}
              placeholder={rolesRes.loading ? "Loading roles…" : "Choose a role"}
              options={roleOptions}
            />
          )}
        </FormField>
        <FormField label="Scope type" required>
          {(f) => <Select {...f} value={form.scope_type} onChange={set("scope_type")} options={scopeTypes.map((s) => ({ value: s, label: humanize(s) }))} />}
        </FormField>
        {form.scope_type !== "platform" ? <FormField label="Scope id" required>{(f) => <Input {...f} value={form.scope_id} onChange={set("scope_id")} />}</FormField> : null}
        <FormField label="Expires on">{(f) => <Input {...f} type="date" value={form.expires_at} onChange={set("expires_at")} />}</FormField>
        <FormField label="Reason" required>{(f) => <TextArea {...f} value={form.reason} onChange={set("reason")} />}</FormField>
      </ActionDialog>
      <ActionDialog
        open={revoke !== null}
        onClose={() => {
          setRevoke(null);
          setRevokeReason("");
        }}
        title={`Revoke ${roleLabel(revoke?.role_key)}?`}
        description={revoke && isPrivileged(revoke.role_key) ? "The grantee is signed out. This is a privileged role: another admin must approve." : "The grantee is signed out."}
        submitLabel="Revoke"
        danger
        validate={() => (revokeReason.trim().length < 5 ? "Give a reason." : null)}
        onSubmit={async () => toOutcome(await api.post(`rbac/grants/${revoke!.grant_id}/revoke`, { reason: revokeReason.trim() }, { idempotencyKey: true }))}
        onDone={() => {
          setRevokeReason("");
          void list.reload();
        }}
      >
        <FormField label="Reason" required>{(f) => <TextArea {...f} value={revokeReason} onChange={(e) => setRevokeReason(e.target.value)} />}</FormField>
      </ActionDialog>
    </div>
  );
}

/* ------------------------------------------------------------ Feature flags */

/** verified: app/modules/admin/router.py _flag_out (GET admin/feature-flags returns {data}). */
interface Flag {
  flag_key: string;
  description: string | null;
  is_enabled: boolean;
  rollout_percent: number;
  user_allowlist: string[];
}

/** ADM-007 feature flags (ADM-10/11; P5 on change). */
export function FeatureFlags() {
  const toast = useToast();
  const res = useResource<{ data: Flag[] }>("admin/feature-flags");
  const [edit, setEdit] = useState<Flag | null>(null);
  const [pct, setPct] = useState("");
  const [enabled, setEnabled] = useState("true");
  const [userIds, setUserIds] = useState("");
  const flags = res.data?.data;
  const cols: Column<Flag>[] = [
    { key: "key", header: "Flag", cell: (f) => <span><span className="font-mono text-xs">{f.flag_key}</span>{f.description ? <span className="block text-xs text-fg-muted">{f.description}</span> : null}</span> },
    { key: "on", header: "State", cell: (f) => <Badge tone={f.is_enabled ? "success" : "neutral"}>{f.is_enabled ? "On" : "Off"}</Badge> },
    { key: "pct", header: "Rollout", align: "right", cell: (f) => `${f.rollout_percent}%` },
    { key: "allow", header: "Allowlists", cell: (f) => `${f.user_allowlist.length} users` },
    {
      key: "act",
      header: <span className="sr-only">Actions</span>,
      cell: (f) => (
        <Button
          size="sm"
          variant="secondary"
          onClick={() => {
            setEdit(f);
            setEnabled(String(f.is_enabled));
            setPct(String(f.rollout_percent));
            setUserIds(f.user_allowlist.join("\n"));
          }}
          aria-label={`Edit ${f.flag_key}`}
        >
          Edit
        </Button>
      ),
    },
  ];
  return (
    <div>
      <PageHeader eyebrow="ADM-007" title="Feature flags" />
      <Table caption="Feature flags" columns={cols} rows={flags} rowKey={(f) => f.flag_key} loading={res.loading} error={res.error} onRetry={() => void res.reload()} empty={{ title: "No flags" }} />
      <ActionDialog
        open={edit !== null}
        onClose={() => setEdit(null)}
        title={`Edit ${edit?.flag_key ?? ""}`}
        submitLabel="Save"
        validate={() => {
          const n = Number(pct);
          if (!(pct.trim() !== "" && Number.isInteger(n) && n >= 0 && n <= 100)) return "Rollout must be a whole number from 0 to 100.";
          const bad = parseIdList(userIds).invalid;
          return bad.length ? `Not a valid id: ${bad[0]}` : null;
        }}
        onSubmit={async () =>
          toOutcome(
            await api.patch(
              `admin/feature-flags/${encodeURIComponent(edit!.flag_key)}`,
              { is_enabled: enabled === "true", rollout_percent: Number(pct), user_allowlist: parseIdList(userIds).ids } satisfies Schema<"FlagPatch">,
            ),
          )
        }
        onDone={() => {
          toast.show({ title: "Flag updated.", tone: "success" });
          void res.reload();
        }}
      >
        <FormField label="State">{(f) => <Select {...f} value={enabled} onChange={(e) => setEnabled(e.target.value)} options={[{ value: "true", label: "On" }, { value: "false", label: "Off" }]} />}</FormField>
        <FormField label="Rollout %">{(f) => <Input {...f} type="number" min={0} max={100} value={pct} onChange={(e) => setPct(e.target.value)} />}</FormField>
        <FormField label="User allowlist" hint="User ids, one per line. Listed users always get the flag.">
          {(f) => <TextArea {...f} value={userIds} onChange={(e) => setUserIds(e.target.value)} />}
        </FormField>
      </ActionDialog>
    </div>
  );
}

/* --------------------------------------------------------------- Audit log */

type AuditRow = Schema<"AuditEventOut">;
type ChainStatus = Schema<"ChainStatusOut">;

/** ADM-008 audit log viewer (AUD-01/02) with hash-chain status (AUD-03). Read-only: no edit or delete exists. */
export function AuditLog() {
  const [action, setAction] = useState("");
  const [actor, setActor] = useState("");
  const [subject, setSubject] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const list = useCursorList<AuditRow>(
    "audit/events",
    cleanQuery({ action: action.trim(), actor_user_id: uuidOrEmpty(actor), subject_user_id: uuidOrEmpty(subject), from: from ? `${from}T00:00:00+05:30` : "", to: to ? `${to}T23:59:59+05:30` : "", limit: 50 }),
  );
  const chain = useResource<ChainStatus>("audit/chain-status");
  const [open, setOpen] = useState<AuditRow | null>(null);
  const [detail, setDetail] = useState<{ data?: unknown; error?: unknown } | null>(null);
  const broken = chain.data && !chain.data.verified;

  const openRow = async (r: AuditRow) => {
    setOpen(r);
    setDetail(null);
    try {
      const d = await api.get<Schema<"AuditEventDetailOut">>(`audit/events/${r.seq}`);
      setDetail({ data: { before: d.before_state ?? null, after: d.after_state ?? null, reason: d.reason ?? null, ip: d.ip ?? null } });
    } catch (err) {
      setDetail({ error: err });
    }
  };

  const cols: Column<AuditRow>[] = [
    { key: "seq", header: "Seq", align: "right", cell: (r) => r.seq },
    { key: "at", header: "When", cell: (r) => formatDateTime(r.occurred_at) },
    { key: "action", header: "Action", cell: (r) => <span className="font-mono text-xs">{r.action}</span> },
    { key: "actor", header: "Actor", cell: (r) => <span className="text-xs">{r.actor_user_id ?? r.actor_type ?? "—"}{r.actor_roles?.length ? ` (${r.actor_roles.join(", ")})` : ""}</span> },
    { key: "target", header: "Target", cell: (r) => <span className="text-xs">{r.target_type ? `${r.target_type}:${r.target_id ?? ""}` : "—"}</span> },
    { key: "reason", header: "Reason", cell: (r) => r.reason_code ?? "—" },
    {
      key: "open",
      header: <span className="sr-only">Details</span>,
      cell: (r) => (
        <Button size="sm" variant="ghost" onClick={() => void openRow(r)} aria-label={`Details for audit entry ${r.seq}`}>
          Details
        </Button>
      ),
    },
  ];

  return (
    <div>
      <PageHeader eyebrow="ADM-008" title="Audit log" description="Append-only and hash-chained. Your queries are audited too." />
      {chain.data ? (
        <p role={broken ? "alert" : "status"} className={`mb-4 rounded-lg border p-3 text-sm ${broken ? "border-danger-border bg-danger-subtle text-danger-fg" : "border-success-border bg-success-subtle text-success-fg"}`}>
          <span aria-hidden="true">{broken ? "⚠ " : "✓ "}</span>
          {broken
            ? `Audit chain break detected${chain.data.first_bad_seq ? ` at seq ${chain.data.first_bad_seq}` : ""}${chain.data.reason ? ` (${chain.data.reason})` : ""}.`
            : `Audit chain verified (${chain.data.checked_rows} rows${chain.data.last_seq ? `, up to seq ${chain.data.last_seq}` : ""}).`}
        </p>
      ) : null}
      <FilterBar label="Audit filters">
        <FormField label="Action" hint="e.g. case.decide">{(f) => <Input {...f} value={action} onChange={(e) => setAction(e.target.value)} />}</FormField>
        <FormField label="Actor user id" hint="Full id">{(f) => <Input {...f} value={actor} onChange={(e) => setActor(e.target.value)} />}</FormField>
        <FormField label="Subject user id" hint="Full id">{(f) => <Input {...f} value={subject} onChange={(e) => setSubject(e.target.value)} />}</FormField>
        <FormField label="From">{(f) => <Input {...f} type="date" value={from} onChange={(e) => setFrom(e.target.value)} />}</FormField>
        <FormField label="To">{(f) => <Input {...f} type="date" value={to} onChange={(e) => setTo(e.target.value)} />}</FormField>
      </FilterBar>
      <Table caption="Audit events" columns={cols} rows={list.rows} rowKey={(r) => String(r.seq)} loading={list.loading} error={list.error} onRetry={() => void list.reload()} empty={{ title: "No events match" }} footer={<Pagination hasMore={list.hasMore} hasPrevious={list.hasPrevious} onNext={list.next} onPrevious={list.previous} />} />
      {open ? (
        <Card title={`Entry ${open.seq}`} className="mt-4" actions={<Button size="sm" variant="ghost" onClick={() => setOpen(null)}>Close</Button>}>
          <KeyValueList items={[{ label: "Request id", value: open.request_id ?? "—" }, { label: "Row hash", value: <span className="break-all font-mono text-xs">{open.row_hash ?? "—"}</span> }, { label: "Previous hash", value: <span className="break-all font-mono text-xs">{open.prev_hash ?? "—"}</span> }]} />
          <div className="mt-3">{detail?.error ? <InlineProblem error={detail.error} /> : detail?.data ? <JsonBlock label="Before / after" value={detail.data} /> : <Skeleton className="h-20 w-full" />}</div>
        </Card>
      ) : null}
    </div>
  );
}

/* --------------------------------------------------------------- Dashboard */

/** ADM-01 platform aggregates (no per-user data). */
interface DashboardOut {
  generated_at: string;
  users: { total: number; active: number; pending_verification: number; deactivated: number; minors: number; new_7d: number; new_30d: number };
  sessions: { active: number };
  support: { open: number; breached: number; unassigned: number };
  security: { restricted_by_level: Record<string, number>; open_cases: number };
  approvals: { pending: number };
  privacy: { open: number; overdue: number };
  break_glass: { active: number };
  commerce: { paid_orders_30d: number; revenue_paise_30d: number };
}

const num = (v: number | null | undefined) => (typeof v === "number" ? new Intl.NumberFormat("en-IN").format(v) : "—");

/** ADM-001 platform dashboard (ADM-01, aggregates only) with the audit chain status. */
export function AdminDashboard() {
  const chain = useResource<ChainStatus>("audit/chain-status");
  const dash = useResource<DashboardOut>("admin/dashboard");
  const d = dash.data;
  return (
    <div>
      <PageHeader eyebrow="ADM-001" title="Platform overview" description={chain.data ? `Audit chain: ${chain.data.verified ? "✓ verified" : "⚠ break detected"} (${chain.data.checked_rows} rows checked)` : undefined} />
      {dash.error ? (
        <ErrorState error={dash.error} onRetry={() => void dash.reload()} />
      ) : !d ? (
        <Skeleton className="h-40 w-full" />
      ) : (
        <div className="space-y-4">
          {d.break_glass.active > 0 ? (
            <p role="alert" className="rounded-lg border border-danger-border bg-danger-subtle p-3 text-sm font-semibold text-danger-fg">
              ⚠ Break-glass elevation active: {d.break_glass.active}
            </p>
          ) : null}
          <Card title="Users">
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <StatTile label="Total users" value={num(d.users.total)} />
              <StatTile label="Active" value={num(d.users.active)} />
              <StatTile label="Pending verification" value={num(d.users.pending_verification)} />
              <StatTile label="Deactivated" value={num(d.users.deactivated)} />
              <StatTile label="Minors" value={num(d.users.minors)} />
              <StatTile label="New (7 d)" value={num(d.users.new_7d)} />
              <StatTile label="New (30 d)" value={num(d.users.new_30d)} />
              <StatTile label="Active sessions" value={num(d.sessions.active)} />
            </div>
          </Card>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Card title="Support">
              <div className="grid grid-cols-3 gap-3">
                <StatTile label="Open tickets" value={num(d.support.open)} />
                <StatTile label="SLA breached" value={num(d.support.breached)} />
                <StatTile label="Unassigned" value={num(d.support.unassigned)} />
              </div>
            </Card>
            <Card title="Security (aggregates)">
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
                {Object.entries(d.security.restricted_by_level).map(([lvl, v]) => (
                  <StatTile key={lvl} label={`Restricted L${lvl}`} value={num(v)} />
                ))}
                <StatTile label="Open cases" value={num(d.security.open_cases)} />
              </div>
            </Card>
            <Card title="Governance">
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
                <StatTile label="Pending approvals" value={num(d.approvals.pending)} />
                <StatTile label="Privacy requests open" value={num(d.privacy.open)} />
                <StatTile label="Privacy overdue" value={num(d.privacy.overdue)} />
              </div>
            </Card>
            <Card title="Commerce (30 d)">
              <div className="grid grid-cols-2 gap-3">
                <StatTile label="Paid orders" value={num(d.commerce.paid_orders_30d)} />
                <StatTile label="Revenue" value={formatINR(d.commerce.revenue_paise_30d)} />
              </div>
            </Card>
          </div>
          <p className="text-xs text-fg-muted">Generated {formatDateTime(d.generated_at)}</p>
        </div>
      )}
    </div>
  );
}

/* --------------------------------------------------------- Privacy requests */

/** verified: app/modules/admin/privacy.py request_out(staff=True) (GET admin/privacy-requests returns {data}, unpaginated). */
interface PrivacyRequest {
  request_id: string;
  request_ref: string;
  request_type: string;
  status: string;
  received_at: string;
  due_at: string;
  cooling_off_until: string | null;
  completed_at: string | null;
  response_summary: string | null;
  export_available: boolean;
  user_id: string | null;
  requester_relationship: string | null;
  details: string | null;
  identity_verification_method: string | null;
  identity_verified_at: string | null;
  overdue: boolean;
}

/** app/modules/admin/privacy.py OPEN_STATES. */
const PRIVACY_OPEN = new Set(["received", "identity_verification", "in_progress", "awaiting_requester", "cooling_off"]);

/** ADM-009 DPDP rights queue (PRV-07..11). */
export function PrivacyRequests() {
  const [status, setStatus] = useState("open");
  // No status filter in the api: it returns open requests plus those closed in the last 30 days.
  const list = useCursorList<PrivacyRequest>("admin/privacy-requests");
  const rows = list.rows?.filter((r) => (status === "open" ? PRIVACY_OPEN.has(r.status) : r.status === status));
  const [act, setAct] = useState<{ kind: "verify" | "complete" | "reject"; row: PrivacyRequest } | null>(null);
  const [method, setMethod] = useState("session");
  const [note, setNote] = useState("");
  const cols: Column<PrivacyRequest>[] = [
    { key: "ref", header: "Reference", cell: (r) => <span className="font-mono">{r.request_ref}</span> },
    { key: "type", header: "Type", cell: (r) => humanize(r.request_type) },
    { key: "status", header: "Status", cell: (r) => <StateBadge state={r.status} /> },
    { key: "due", header: "Due", cell: (r) => <span className={r.overdue ? "font-semibold text-danger-fg" : undefined}>{r.overdue ? "⚠ Overdue · " : ""}{formatCountdown(r.due_at)}</span> },
    { key: "id", header: "Identity", cell: (r) => (r.identity_verified_at ? "Verified" : "Not verified") },
    {
      key: "act",
      header: <span className="sr-only">Actions</span>,
      cell: (r) =>
        !PRIVACY_OPEN.has(r.status) ? null : (
        <span className="flex gap-1">
          {!r.identity_verified_at ? <Button size="sm" variant="secondary" onClick={() => setAct({ kind: "verify", row: r })}>Verify identity</Button> : <Button size="sm" onClick={() => setAct({ kind: "complete", row: r })}>Complete</Button>}
          <Button size="sm" variant="ghost" onClick={() => setAct({ kind: "reject", row: r })}>Reject</Button>
        </span>
      ),
    },
  ];
  const path = act ? `admin/privacy-requests/${act.row.request_id}` : "";
  return (
    <div>
      <PageHeader eyebrow="ADM-009" title="Privacy requests" description="DPDP rights requests with response timers." />
      <FilterBar>
        <FormField label="Status">{(f) => <Select {...f} value={status} onChange={(e) => setStatus(e.target.value)} options={["open", "cooling_off", "completed", "rejected"].map((s) => ({ value: s, label: humanize(s) }))} />}</FormField>
      </FilterBar>
      <Table caption="Privacy requests" columns={cols} rows={rows} rowKey={(r) => r.request_id} loading={list.loading} error={list.error} onRetry={() => void list.reload()} empty={{ title: "No requests" }} footer={<Pagination hasMore={list.hasMore} hasPrevious={list.hasPrevious} onNext={list.next} onPrevious={list.previous} />} />
      <ActionDialog
        open={act !== null}
        onClose={() => setAct(null)}
        title={act?.kind === "verify" ? "Record identity verification" : act?.kind === "complete" ? "Complete request" : "Reject request"}
        submitLabel={act?.kind === "reject" ? "Reject" : act?.kind === "complete" ? "Complete" : "Record"}
        danger={act?.kind === "reject"}
        validate={() => (act?.kind === "reject" && note.trim().length < 10 ? "Give the legal reason (10+ characters)." : act?.kind === "complete" && note.trim().length < 3 ? "Summarise the response sent to the requester." : null)}
        onSubmit={async () =>
          toOutcome(
            act!.kind === "verify"
              ? await api.post(`${path}/verify-identity`, { method } as Schema<"VerifyIn">)
              : act!.kind === "complete"
                ? await api.post(`${path}/complete`, { response_summary: note.trim() } satisfies Schema<"CompleteIn">, { idempotencyKey: true })
                : await api.post(`${path}/reject`, { reason: note.trim() } satisfies Schema<"RejectIn">),
          )
        }
        onDone={() => {
          setNote("");
          void list.reload();
        }}
      >
        {act?.kind === "verify" ? <FormField label="Method">{(f) => <Select {...f} value={method} onChange={(e) => setMethod(e.target.value)} options={["session", "otp", "guardian_otp", "manual"].map((m) => ({ value: m, label: humanize(m) }))} />}</FormField> : null}
        {act?.kind !== "verify" ? (
          <FormField label={act?.kind === "reject" ? "Reason" : "Response summary"} required>
            {(f) => <TextArea {...f} value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000} />}
          </FormField>
        ) : null}
      </ActionDialog>
    </div>
  );
}

/* ------------------------------------------------------------- Break-glass */

/** ADM-17..19 break-glass session. */
interface BreakGlassSession {
  break_glass_id: string;
  user_id: string;
  reason: string;
  elevated_role: string;
  status: "active" | "ended" | "expired";
  started_at: string;
  expires_at: string;
  ended_at: string | null;
  end_reason: string | null;
  ended_by: string | null;
  review_status: "not_due" | "pending" | "overdue" | "reviewed";
  review_due_at: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  review_note: string | null;
}

const REVIEW_TONE = { not_due: "neutral", pending: "warning", overdue: "danger", reviewed: "success" } as const;

type BgDialog = { kind: "end" | "review"; row: BreakGlassSession };

/**
 * ADM-012 break-glass history (ADM-17/18/19). Activation is retired in single-company mode
 * (WS3: `POST admin/break-glass` returns 405 — Admin already holds every break-glass permission);
 * historic sessions can still be ended early and reviewed by a different admin.
 */
export function BreakGlass() {
  const toast = useToast();
  const [status, setStatus] = useState("");
  const list = useCursorList<BreakGlassSession>("admin/break-glass", cleanQuery({ status }));
  const active = (list.envelope?.active as BreakGlassSession | null | undefined) ?? null;
  const [dialog, setDialog] = useState<BgDialog | null>(null);
  const [reason, setReason] = useState("");
  const close = () => {
    setDialog(null);
    setReason("");
  };
  const target = dialog ? dialog.row : null;
  const cols: Column<BreakGlassSession>[] = [
    { key: "who", header: "Admin", cell: (r) => <span className="font-mono text-xs">{r.user_id.slice(0, 8)}</span> },
    { key: "reason", header: "Reason", cell: (r) => r.reason },
    { key: "status", header: "Status", cell: (r) => <StateBadge state={r.status} /> },
    { key: "window", header: "Window", cell: (r) => `${formatDateTime(r.started_at)} → ${formatDateTime(r.ended_at ?? r.expires_at)}` },
    { key: "review", header: "Review", cell: (r) => <Badge tone={REVIEW_TONE[r.review_status] ?? "neutral"}>{humanize(r.review_status)}</Badge> },
    {
      key: "act",
      header: <span className="sr-only">Actions</span>,
      cell: (r) =>
        r.status === "active" ? (
          <Button size="sm" variant="secondary" onClick={() => setDialog({ kind: "end", row: r })}>
            End now
          </Button>
        ) : r.review_status === "pending" || r.review_status === "overdue" ? (
          <Button size="sm" variant="secondary" onClick={() => setDialog({ kind: "review", row: r })} aria-label={`Review break-glass ${r.break_glass_id}`}>
            Review
          </Button>
        ) : null,
    },
  ];
  return (
    <div>
      <PageHeader
        eyebrow="ADM-012"
        title="Break-glass"
        description="History of past break-glass sessions. Activation is retired: Admin already holds every break-glass permission. Sessions still awaiting review can be reviewed by a different admin."
      />
      {active ? (
        <div role="alert" className="mb-4 rounded-lg border border-danger-border bg-danger-subtle p-3 text-sm">
          <p className="font-semibold text-danger-fg">
            Break-glass is active until {formatDateTime(active.expires_at)} ({formatCountdown(active.expires_at)}).
          </p>
          <p className="mt-1 text-fg-secondary">
            Elevated role: {humanize(active.elevated_role)}. Reason: {active.reason}
          </p>
          <div className="mt-2">
            <Button size="sm" variant="secondary" onClick={() => setDialog({ kind: "end", row: active })}>
              End break-glass
            </Button>
          </div>
        </div>
      ) : null}
      <FilterBar label="Break-glass filters">
        <FormField label="Status">
          {(f) => <Select {...f} value={status} onChange={(e) => setStatus(e.target.value)} options={[{ value: "", label: "Any" }, ...["active", "ended", "expired"].map((v) => ({ value: v, label: humanize(v) }))]} />}
        </FormField>
      </FilterBar>
      <Table caption="Break-glass history" columns={cols} rows={list.rows} rowKey={(r) => r.break_glass_id} loading={list.loading} error={list.error} onRetry={() => void list.reload()} empty={{ title: "No break-glass sessions" }} footer={<Pagination hasMore={list.hasMore} hasPrevious={list.hasPrevious} onNext={list.next} onPrevious={list.previous} />} />
      <ActionDialog
        open={target !== null}
        onClose={close}
        title={dialog?.kind === "end" ? "End break-glass now?" : "Record post-hoc review"}
        submitLabel={dialog?.kind === "end" ? "End now" : "Record review"}
        validate={() => (dialog?.kind === "review" && reason.trim().length < 5 ? "Add a review note (5+ characters)." : null)}
        onSubmit={async () =>
          toOutcome(await api.post<BreakGlassSession>(`admin/break-glass/${target!.break_glass_id}/${dialog?.kind === "end" ? "end" : "review"}`, { note: reason.trim() || null }, { idempotencyKey: true }))
        }
        onDone={() => {
          setReason("");
          toast.show({ title: dialog?.kind === "end" ? "Break-glass ended." : "Review recorded.", tone: "success" });
          void list.reload();
        }}
      >
        <FormField label={dialog?.kind === "review" ? "Review note" : "Note (optional)"} required={dialog?.kind === "review"}>
          {(f) => <TextArea {...f} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={2000} />}
        </FormField>
      </ActionDialog>
    </div>
  );
}
