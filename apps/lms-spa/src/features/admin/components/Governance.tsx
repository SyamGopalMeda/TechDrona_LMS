"use client";

import Link from "next/link";
import { useState } from "react";
import { buttonClasses } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Display";
import {
  Badge,
  Button,
  Card,
  DashboardHero,
  Dialog,
  EmptyState,
  ErrorState,
  FormField,
  Input,
  LoadingBlock,
  PageHeader,
  Pagination,
  QuickActions,
  Reveal,
  Select,
  StatGrid,
  StatTile,
  StatusBadge,
  Table,
  ViewAllLink,
  useToast,
  type Column,
} from "@/components/ui";
import { api } from "@/lib/api/client";
import type { Body, Schema } from "@/lib/api-types";
import { LEVEL_NAME, toLevel } from "@/features/security-admin/components/RiskLevel";
import { ActionDialog, FilterBar, InlineProblem, KeyValueList, StateBadge, TextArea, ValueSummary, textLink } from "./console-ui";
import { AdminCoursesSection } from "./CourseCards";
import { INTEGRATION_LABELS, useIntegrations, useSimpleAuth, type IntegrationKey } from "@/components/shell/Integrations";
import { cleanQuery, formatINR, humanize, shortRef, toOutcome, useCursorList } from "../lib/console";
import { useResource } from "@/lib/api/use-resource";
import { DEFAULT_HANDLE, useIdentity } from "@/lib/api/session-cache";
import { formatDate, formatDateTime, formatTimeUntil } from "@/lib/format";

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

/** A user id as a readable link to their account page ("User #9F3C21AB"); these APIs return ids only. */
export function UserRef({ id, label = "User" }: { id: string | null | undefined; label?: string }) {
  if (!id) return <span className="text-fg-muted">—</span>;
  return (
    <Link className={`${textLink} inline-flex min-h-6 items-center`} href={`/admin/users/${id}`}>
      {label} {shortRef(id)}
    </Link>
  );
}

const SCOPE_LABELS: Record<string, string> = { platform: "Whole platform", batch: "Batch", course: "Course", organization: "Organisation" };
/** "Whole platform", "Batch #9F3C21AB". */
export const scopeLabel = (type: string, id: string | null | undefined) => `${SCOPE_LABELS[type] ?? humanize(type)}${id ? ` ${shortRef(id)}` : ""}`;

/** Restriction level in words ("Temporarily restricted"), never a bare "L3". */
export function restrictionText(level: number | string | null | undefined): string {
  const lv = toLevel(level);
  if (lv === null) return "—";
  return lv === 0 ? "None" : LEVEL_NAME[lv];
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
  // TD_SIMPLE_AUTH (GET public/integrations → simple_auth): an Admin's grant applies at once
  // (rbac/router.py create_grant); revoking a privileged role still needs a second admin.
  const simple = useSimpleAuth() === true;
  const grantNeedsApproval = (key: string) => isPrivileged(key) && !simple;
  const roleOptions = roles.filter((r) => (TARGET_ROLES as readonly string[]).includes(r.role_key)).map((r) => ({ value: r.role_key, label: roleLabel(r.role_key) }));
  const scopeTypes = (roles.find((r) => r.role_key === form.role_key)?.allowed_scope_types ?? SCOPE_TYPES).filter((s) => SCOPE_TYPES.includes(s));
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const cols: Column<Grant>[] = [
    { key: "user", header: "User", cell: (g) => <UserRef id={g.user_id} /> },
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
    { key: "scope", header: "Applies to", cell: (g) => scopeLabel(g.scope_type, g.scope_id) },
    { key: "exp", header: "Expires", cell: (g) => (g.expires_at ? formatDate(g.expires_at) : "Never") },
    { key: "granted", header: "Granted", priority: "secondary", cell: (g) => formatDate(g.granted_at) },
    {
      key: "act",
      header: <span className="sr-only">Actions</span>,
      cell: (g) => (
        <Button size="sm" variant="secondary" onClick={() => setRevoke(g)} aria-label={`Revoke ${roleLabel(g.role_key)} from user ${shortRef(g.user_id)}`}>
          Revoke
        </Button>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        title="Role grants"
        description={
          simple
            ? "Give people roles such as Trainer or Admin. The person is signed out when a role changes. Removing an Admin role needs a second admin to approve."
            : "Give people roles such as Trainer or Admin. The person is signed out when a role changes, and Admin roles need a second admin to approve."
        }
        actions={<Button onClick={() => setGrantOpen(true)}>Grant role</Button>}
      />
      <FilterBar label="Grant filters">
        <FormField label="User id" hint="Paste the full id from the person's page in Users">
          {(f) => <Input {...f} value={userId} onChange={(e) => setUserId(e.target.value)} />}
        </FormField>
        <FormField label="Role">{(f) => <Select {...f} value={role} onChange={(e) => setRole(e.target.value)} options={[{ value: "", label: "Any" }, ...roleOptions]} />}</FormField>
      </FilterBar>
      <Table caption="Role grants" columns={cols} rows={list.rows} rowKey={(g) => g.grant_id} loading={list.loading} error={list.error} onRetry={() => void list.reload()} empty={{ title: "No grants match", description: userId || role ? "Clear the filters to see every active grant." : "Use Grant role to give someone access." }} footer={<Pagination hasMore={list.hasMore} hasPrevious={list.hasPrevious} onNext={list.next} onPrevious={list.previous} />} />
      <ActionDialog
        open={grantOpen}
        onClose={() => setGrantOpen(false)}
        onOpen={() => setForm({ user_id: initialUserId, role_key: "", scope_type: "platform", scope_id: "", expires_at: "", reason: "" })}
        title="Grant a role"
        description={grantNeedsApproval(form.role_key) ? "This is a privileged role: another admin must approve (dual control)." : "Takes effect at the grantee's next sign-in."}
        submitLabel={grantNeedsApproval(form.role_key) ? "Request grant" : "Grant"}
        validate={() => (!form.user_id.trim() ? "Enter the user id." : !form.role_key ? "Choose a role." : form.scope_type !== "platform" && !form.scope_id.trim() ? "Enter the scope id." : form.reason.trim().length < 5 ? "Give a reason (5+ characters)." : null)}
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
        <FormField label="User id" required hint="Tip: open the person in Users and choose Manage under Role grants to fill this in.">
          {(f) => <Input {...f} value={form.user_id} onChange={set("user_id")} />}
        </FormField>
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
        <FormField label="Applies to" required>
          {(f) => <Select {...f} value={form.scope_type} onChange={set("scope_type")} options={scopeTypes.map((s) => ({ value: s, label: SCOPE_LABELS[s] ?? humanize(s) }))} />}
        </FormField>
        {form.scope_type !== "platform" ? <FormField label="Scope id" required hint="Paste the full id from the batch or course page.">{(f) => <Input {...f} value={form.scope_id} onChange={set("scope_id")} />}</FormField> : null}
        <FormField label="Expires on">{(f) => <Input {...f} type="date" value={form.expires_at} onChange={set("expires_at")} />}</FormField>
        <FormField label="Reason" required>{(f) => <TextArea {...f} value={form.reason} onChange={set("reason")} />}</FormField>
      </ActionDialog>
      <ActionDialog
        open={revoke !== null}
        onClose={() => {
          setRevoke(null);
          setRevokeReason("");
        }}
        onOpen={() => setRevokeReason("")}
        title={`Revoke ${roleLabel(revoke?.role_key)}?`}
        description={revoke && isPrivileged(revoke.role_key) ? "The grantee is signed out. This is a privileged role: another admin must approve." : "The grantee is signed out."}
        submitLabel="Revoke"
        danger
        validate={() => (revokeReason.trim().length < 5 ? "Give a reason (5+ characters)." : null)}
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

/** "payments.cashfree_enabled" → "Payments · Cashfree enabled". */
export function flagName(key: string): string {
  return key
    .split(".")
    .map((part) => humanize(part))
    .join(" · ");
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
    {
      key: "key",
      header: "Feature",
      cell: (f) => (
        <span>
          <span className="font-medium text-fg">{flagName(f.flag_key)}</span>
          {f.description ? <span className="block text-xs text-fg-muted">{f.description}</span> : null}
        </span>
      ),
    },
    { key: "on", header: "State", cell: (f) => <StatusBadge status={f.is_enabled ? "enabled" : "disabled"} /> },
    { key: "pct", header: "Rollout", align: "right", cell: (f) => (f.rollout_percent >= 100 ? "Everyone" : `${f.rollout_percent}% of users`) },
    { key: "allow", header: "Always on for", priority: "secondary", cell: (f) => (f.user_allowlist.length ? `${f.user_allowlist.length} ${f.user_allowlist.length === 1 ? "user" : "users"}` : "—") },
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
      <PageHeader title="Feature flags" description="Turn features on for everyone, for a share of users, or for named users. Changes reach real users straight away." />
      <Table
        caption="Feature flags"
        columns={cols}
        rows={flags}
        rowKey={(f) => f.flag_key}
        loading={res.loading}
        error={res.error}
        onRetry={() => void res.reload()}
        empty={{ title: "No feature flags yet", description: "Flags appear here when the engineering team ships a feature behind one." }}
      />
      <ActionDialog
        open={edit !== null}
        onClose={() => setEdit(null)}
        title={`Edit ${edit ? flagName(edit.flag_key) : "flag"}`}
        description={
          <>
            This changes the live platform for real users. <span className="text-fg-muted">Flag key: {edit?.flag_key}</span>
          </>
        }
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
        <FormField label="Rollout %" hint="Share of users who get the feature (0 to 100).">{(f) => <Input {...f} type="number" min={0} max={100} value={pct} onChange={(e) => setPct(e.target.value)} />}</FormField>
        <FormField label="User allowlist" hint="Full user ids, one per line. Listed users always get the feature.">
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
  const [detail, setDetail] = useState<{ data?: Schema<"AuditEventDetailOut">; error?: unknown } | null>(null);
  const broken = chain.data && !chain.data.verified;

  const openRow = async (r: AuditRow) => {
    setOpen(r);
    setDetail(null);
    try {
      const d = await api.get<Schema<"AuditEventDetailOut">>(`audit/events/${r.seq}`);
      setDetail({ data: d });
    } catch (err) {
      setDetail({ error: err });
    }
  };
  const filtered = Boolean(action || actor || subject || from || to);

  const cols: Column<AuditRow>[] = [
    { key: "at", header: "When", cell: (r) => formatDateTime(r.occurred_at) },
    { key: "action", header: "Action", cell: (r) => <span title={r.action}>{actionLabel(r.action)}</span> },
    { key: "actor", header: "Done by", cell: (r) => <AuditActor row={r} /> },
    { key: "target", header: "Record", cell: (r) => (r.target_type ? scopeLabel(r.target_type, r.target_id) : "—") },
    { key: "reason", header: "Reason", priority: "secondary", cell: (r) => (r.reason_code ? humanize(r.reason_code) : "—") },
    { key: "seq", header: "Entry", align: "right", priority: "secondary", cell: (r) => r.seq },
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
      <PageHeader title="Audit log" description="Every sensitive action, in order. Entries can't be edited or deleted, and your searches here are recorded too." />
      {chain.data ? (
        <p role={broken ? "alert" : "status"} className={`mb-4 rounded-lg border p-3 text-sm ${broken ? "border-danger-border bg-danger-subtle text-danger-fg" : "border-success-border bg-success-subtle text-success-fg"}`}>
          <span aria-hidden="true">{broken ? "⚠ " : "✓ "}</span>
          {broken
            ? `Audit chain break detected${chain.data.first_bad_seq ? ` at seq ${chain.data.first_bad_seq}` : ""}${chain.data.reason ? ` (${chain.data.reason})` : ""}.`
            : `Audit chain verified (${chain.data.checked_rows} rows${chain.data.last_seq ? `, up to seq ${chain.data.last_seq}` : ""}).`}
        </p>
      ) : null}
      <FilterBar label="Audit filters" columns={3}>
        <FormField label="Action" hint="Exact action key, e.g. case.decide">{(f) => <Input {...f} value={action} onChange={(e) => setAction(e.target.value)} />}</FormField>
        <FormField label="Done by (user id)" hint="Full id from the person's page in Users">{(f) => <Input {...f} value={actor} onChange={(e) => setActor(e.target.value)} />}</FormField>
        <FormField label="About user (user id)" hint="Full id from the person's page in Users">{(f) => <Input {...f} value={subject} onChange={(e) => setSubject(e.target.value)} />}</FormField>
        <FormField label="From">{(f) => <Input {...f} type="date" value={from} onChange={(e) => setFrom(e.target.value)} />}</FormField>
        <FormField label="To">{(f) => <Input {...f} type="date" value={to} onChange={(e) => setTo(e.target.value)} />}</FormField>
      </FilterBar>
      <Table
        caption="Audit events"
        columns={cols}
        rows={list.rows}
        rowKey={(r) => String(r.seq)}
        loading={list.loading}
        error={list.error}
        onRetry={() => void list.reload()}
        empty={{ title: "No events match", description: filtered ? "Widen the dates or clear a filter." : "Recorded actions appear here as soon as they happen." }}
        footer={<Pagination hasMore={list.hasMore} hasPrevious={list.hasPrevious} onNext={list.next} onPrevious={list.previous} />}
      />
      <Dialog open={open !== null} onClose={() => setOpen(null)} size="lg" title={open ? actionLabel(open.action) : "Audit entry"} description={open ? `Entry ${open.seq} · ${formatDateTime(open.occurred_at)}` : undefined}>
        {open ? (
          <div className="space-y-5">
            <KeyValueList
              items={[
                { label: "Done by", value: <AuditActor row={open} /> },
                { label: "Record", value: open.target_type ? scopeLabel(open.target_type, open.target_id) : "—" },
                { label: "About user", value: open.subject_user_id ? <UserRef id={open.subject_user_id} /> : "—" },
                { label: "Reason", value: [open.reason_code ? humanize(open.reason_code) : null, open.reason].filter(Boolean).join(" · ") || "—" },
                { label: "Action key", value: <span className="font-mono text-xs">{open.action}</span> },
                { label: "IP address", value: detail?.data?.ip ?? "—" },
              ]}
            />
            {detail?.error ? (
              <InlineProblem error={detail.error} />
            ) : detail?.data ? (
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <section aria-labelledby="audit-before">
                  <h3 id="audit-before" className="mb-2 text-sm font-semibold text-fg">
                    Before
                  </h3>
                  {detail.data.before_state == null ? <p className="text-sm text-fg-muted">Nothing (new record)</p> : <ValueSummary label="Before" value={detail.data.before_state} />}
                </section>
                <section aria-labelledby="audit-after">
                  <h3 id="audit-after" className="mb-2 text-sm font-semibold text-fg">
                    After
                  </h3>
                  {detail.data.after_state == null ? <p className="text-sm text-fg-muted">Nothing (removed)</p> : <ValueSummary label="After" value={detail.data.after_state} />}
                </section>
              </div>
            ) : (
              <LoadingBlock label="Loading the before and after…" lines={3} />
            )}
            <details className="text-sm">
              <summary className="inline-flex min-h-6 cursor-pointer items-center font-medium text-fg-secondary hover:text-fg focus-visible:shadow-focus focus-visible:outline-none">Integrity details</summary>
              <div className="mt-2">
                <KeyValueList
                  columns={1}
                  items={[
                    { label: "Request id", value: open.request_id ? <span className="break-all font-mono text-xs">{open.request_id}</span> : "—" },
                    { label: "Row hash", value: <span className="break-all font-mono text-xs">{open.row_hash ?? "—"}</span> },
                    { label: "Previous hash", value: <span className="break-all font-mono text-xs">{open.prev_hash ?? "—"}</span> },
                  ]}
                />
              </div>
            </details>
          </div>
        ) : null}
      </Dialog>
    </div>
  );
}

/** "case.decide" → "Case decide"; the exact key stays in the details and the filter. */
export const actionLabel = (key: string) => humanize(key);

function AuditActor({ row }: { row: AuditRow }) {
  const roles = row.actor_roles?.length ? ` (${row.actor_roles.map(roleLabel).join(", ")})` : "";
  if (row.actor_user_id)
    return (
      <span className="text-sm">
        <UserRef id={row.actor_user_id} />
        {roles}
      </span>
    );
  return <span className="text-sm">{row.actor_type ? humanize(row.actor_type) : "—"}</span>;
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
  /** Added 2026-11-11; optional so an older api still renders. */
  learning?: { learners: number; courses_published: number; courses_draft: number; batches_active: number; batches_planned: number };
}

const num = (v: number | null | undefined) => (typeof v === "number" ? new Intl.NumberFormat("en-IN").format(v) : "—");
const plural = (n: number, one: string, many: string) => `${num(n)} ${n === 1 ? one : many}`;

interface AttentionItem {
  key: string;
  count: number;
  label: string;
  hint: string;
  href: string;
  tone: "warning" | "danger";
}

/** The "needs your attention" list (design-system §4.4): only counts above zero, most urgent first. */
export function attentionItems(d: DashboardOut): AttentionItem[] {
  const items: AttentionItem[] = [
    { key: "bg", count: d.break_glass.active, label: plural(d.break_glass.active, "emergency-access session is active", "emergency-access sessions are active"), hint: "End it or confirm it is still needed.", href: "/admin/break-glass", tone: "danger" },
    { key: "privacy-overdue", count: d.privacy.overdue, label: plural(d.privacy.overdue, "privacy request is overdue", "privacy requests are overdue"), hint: "Past the legal response deadline.", href: "/admin/privacy-requests", tone: "danger" },
    { key: "sla", count: d.support.breached, label: plural(d.support.breached, "support ticket missed its response time", "support tickets missed their response time"), hint: "Reply or reassign in the ticket queue.", href: "/desk", tone: "danger" },
    { key: "approvals", count: d.approvals.pending, label: plural(d.approvals.pending, "request is waiting for your approval", "requests are waiting for approval"), hint: "Review and decide them in Approvals.", href: "/admin/approvals", tone: "warning" },
    { key: "cases", count: d.security.open_cases, label: plural(d.security.open_cases, "security case is open", "security cases are open"), hint: "Review the evidence and decide.", href: "/security/cases", tone: "warning" },
    { key: "unassigned", count: d.support.unassigned, label: plural(d.support.unassigned, "support ticket has no owner", "support tickets have no owner"), hint: "Assign them in the ticket queue.", href: "/desk", tone: "warning" },
  ];
  return items.filter((i) => i.count > 0);
}

function NeedsAttention({ items }: { items: AttentionItem[] }) {
  return (
    <Card title="Needs your attention" icon="alert" padding={items.length ? "none" : "default"}>
      {items.length ? (
        <ul className="divide-y divide-line">
          {items.map((i) => (
            <li key={i.key}>
              <Link
                href={i.href}
                className="group flex min-h-touch items-center gap-3 px-4 py-3 text-fg no-underline hover:bg-surface-hover focus-visible:shadow-focus focus-visible:outline-none sm:px-5"
              >
                <StatusBadge status={i.tone === "danger" ? "overdue" : "pending"} label={i.tone === "danger" ? "Urgent" : "To do"} />
                <span className="min-w-0 flex-1">
                  <span className="block font-semibold">{i.label}</span>
                  <span className="block text-sm text-fg-secondary">{i.hint}</span>
                </span>
                <span aria-hidden="true" className="text-fg-muted group-hover:text-brand">
                  →
                </span>
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <EmptyState variant="inline" icon="check" title="Nothing needs your attention" description="No overdue requests, waiting approvals, open cases or late tickets right now." />
      )}
    </Card>
  );
}

/** Which outside services are really connected (owner rule: not-integrated must say so). */
export function IntegrationsCard() {
  const st = useIntegrations();
  if (!st) return null;
  const keys = Object.keys(INTEGRATION_LABELS) as IntegrationKey[];
  const missing = keys.filter((k) => st[k] === false).length;
  return (
    <Card title="Integrations" icon="layers" description={missing ? `${missing} not connected yet: these features say "Not integrated yet" to users.` : "Every outside service is connected."}>
      <ul className="divide-y divide-line">
        {keys.map((k) => (
          <li key={k} className="flex items-center justify-between gap-3 py-2 text-sm">
            <span className="text-fg">{INTEGRATION_LABELS[k]}</span>
            {st[k] === true ? (
              <Badge tone="success" dot>
                Connected
              </Badge>
            ) : st[k] === false ? (
              <Badge tone="warning" dot>
                Not integrated yet
              </Badge>
            ) : (
              <Badge tone="neutral">Unknown</Badge>
            )}
          </li>
        ))}
      </ul>
    </Card>
  );
}

/**
 * ADM-023 Settings › System status (live audit admin.md F6/M9/M11): the outside-service status that
 * used to sit on the dashboard, plus the engineering and emergency tools that left the sidebar.
 */
export function SystemStatus() {
  return (
    <div>
      <PageHeader title="System status" description="Which outside services are connected, and advanced tools you rarely need." />
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2 [&>*]:min-w-0">
        <IntegrationsCard />
        <Card title="Advanced tools" icon="key" description="Engineering and emergency tools. Change them only when you know why.">
          <ul className="divide-y divide-line">
            <li className="py-2">
              <Link href="/admin/feature-flags" className={`${textLink} inline-flex min-h-touch items-center font-semibold`}>
                Feature flags
              </Link>
              <p className="text-sm text-fg-secondary">Switch features on or off, such as sending certificates automatically.</p>
            </li>
            <li className="py-2">
              <Link href="/admin/break-glass" className={`${textLink} inline-flex min-h-touch items-center font-semibold`}>
                Break-glass history
              </Link>
              <p className="text-sm text-fg-secondary">Past emergency-access sessions, to end or review.</p>
            </li>
          </ul>
        </Card>
      </div>
    </div>
  );
}

/** `GET me/grants` rows (rbac/router.py my_grants → `_grant_out`); only these fields are read here. */
interface MyGrantsOut {
  data?: { role_key: string; scope_type: string; scope_id: string | null }[];
}

/** Batches the signed-in Admin teaches: their own `trainer` grants at batch scope. */
export function taughtBatchCount(grants: MyGrantsOut["data"]): number {
  return new Set((grants ?? []).filter((g) => g.role_key === "trainer" && g.scope_type === "batch" && g.scope_id).map((g) => g.scope_id)).size;
}

/**
 * "Your Teacher Portal" (owner request 2026-11-12). Shown only once the Admin is the trainer of a
 * batch (Batches → a batch → Assign trainer or evaluator → pick yourself); before that it renders
 * nothing (live audit admin.md M2: a disabled card for every non-teaching admin). It opens
 * `/trainer` in this same session: no second sign-in. The Batches quick action says how to start
 * teaching. The api authorises every request either way (this is navigation only).
 */
export function TeacherPortalCard() {
  const grants = useIdentity<MyGrantsOut>("me/grants", { handle: DEFAULT_HANDLE });
  const count = taughtBatchCount(grants.data?.data);
  if (count === 0) return null;
  const hintId = "teacher-portal-hint";
  return (
    <Card title="Your Teacher Portal" icon="users">
      <div className="space-y-3">
        <p id={hintId} className="text-sm text-fg-secondary">
          {`You teach ${count} batch${count === 1 ? "" : "es"}. Open the Teacher portal to take classes, grade and run tests for them.`}
        </p>
        <Link href="/trainer" className={buttonClasses({ className: "gap-2" })} aria-describedby={hintId}>
          <Icon name="users" className="h-[18px] w-[18px]" />
          Be a Teacher
        </Link>
      </div>
    </Card>
  );
}

/** `GET admin/admissions/overview` (admissions/admin.py); only the fields the dashboard reads. */
interface AdmissionsSummary {
  registered: number;
  enrolled: number;
  pending_claims: number;
  pending_amount_paise: number;
  collected_paise: number;
}

/** ADM-001 platform dashboard (ADM-01, aggregates only): attention list, then numbers that link to their queues. */
export function AdminDashboard() {
  const chain = useResource<ChainStatus>("audit/chain-status");
  const dash = useResource<DashboardOut>("admin/dashboard");
  // Fees are paid by UPI and verified under Admissions; gateway order numbers only while a gateway is connected.
  const adm = useResource<AdmissionsSummary>("admin/admissions/overview");
  const a = adm.data;
  const gateway = useIntegrations()?.payments === true;
  const d = dash.data;
  const warn = (n: number) => (n > 0 ? "warning" : "neutral");
  const bad = (n: number) => (n > 0 ? "danger" : "neutral");
  const levels = d ? Object.entries(d.security.restricted_by_level).sort(([a], [b]) => Number(a) - Number(b)) : [];
  return (
    <div>
      <DashboardHero
        title="Dashboard"
        description="Students, courses, payments and everything waiting for you, in one place."
        actions={
          <>
            {/* The Outreach (College Data) Portal has its own CSP (/colleges): full page load (plain <a>). */}
            {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
            <a href="/colleges" className={buttonClasses({ variant: "inverse", className: "gap-2" })}>
              <Icon name="building" className="h-[18px] w-[18px]" />
              Colleges Data
            </a>
            <Link href="/admin/users?add=1" className={buttonClasses({ variant: "inverse-secondary", className: "gap-2" })}>
              <Icon name="userPlus" className="h-[18px] w-[18px]" />
              Add user
            </Link>
          </>
        }
        meta={
          chain.data ? (
            <Link href="/admin/audit" className="inline-flex min-h-6 items-center rounded-full no-underline focus-visible:shadow-focus focus-visible:outline-none">
              <StatusBadge status={chain.data.verified ? "verified" : "failed"} label={chain.data.verified ? "Audit log verified" : "Audit log break detected"} />
            </Link>
          ) : null
        }
      >
        {d ? (
          <StatGrid columns={6}>
            <StatTile tone="brand" icon="users" label="Students" value={num(d.learning?.learners ?? d.users.active)} hint={`${num(d.users.total)} accounts in all`} href="/admin/users?status=active" />
            <StatTile tone="brand" icon="userPlus" label="New registrations" value={num(d.users.new_30d)} hint={`Last 30 days · ${num(d.users.new_7d)} this week`} href="/admin/users" />
            <StatTile tone={a?.pending_claims ? "highlight" : "success"} icon="rupee" label="Payments to verify" value={num(a?.pending_claims)} hint={a ? `${formatINR(a.pending_amount_paise)} waiting` : "UPI fee payments"} href="/finance/admissions/verify" />
            <StatTile tone="brand" icon="book" label="Active courses" value={num(d.learning?.courses_published)} hint={d.learning ? `${num(d.learning.courses_draft)} in draft` : "Published"} href="/admin/courses" />
            <StatTile tone="brand" icon="layers" label="Active batches" value={num(d.learning?.batches_active)} hint={d.learning ? `${num(d.learning.batches_planned)} planned` : "Running now"} href="/admin/batches" />
            <StatTile tone={d.approvals.pending ? "highlight" : "neutral"} icon="check" label="Pending approvals" value={num(d.approvals.pending)} hint="Waiting in Approvals" href="/admin/approvals" />
          </StatGrid>
        ) : null}
      </DashboardHero>
      {dash.error ? (
        <ErrorState error={dash.error} onRetry={() => void dash.reload()} />
      ) : !d ? (
        <LoadingBlock label="Loading the dashboard…" size="card" rows={4} />
      ) : (
        <div className="space-y-6">
          {d.break_glass.active > 0 ? (
            <p role="alert" className="rounded-lg border border-danger-border bg-danger-subtle p-3 text-sm font-semibold text-danger-fg">
              ⚠ Break-glass elevation active: {d.break_glass.active}
            </p>
          ) : null}
          {/* 2026-11 redesign: two-thirds / one-third grid, most-used panels first. */}
          <Reveal stagger className="grid grid-cols-1 gap-6 lg:grid-cols-3 [&>*]:min-w-0">
            <div className="space-y-6 lg:col-span-2">
              <NeedsAttention items={attentionItems(d)} />
              <AdminCoursesSection />
            </div>
            <div className="space-y-6">
              <TeacherPortalCard />
              <Card title="Quick actions" icon="bolt">
                <QuickActions
                  columns={1}
                  items={[
                    { href: "/admin/users?add=1", label: "Add a user", hint: "Student, trainer or staff, with a role", icon: "userPlus" },
                    { href: "/colleges", label: "Colleges Data", hint: "Colleges, branches, contacts, leads", icon: "building", documentNav: true },
                    { href: "/admin/batches", label: "Batches", hint: "Create batches, add students and trainers (add yourself to teach one)", icon: "layers" },
                    { href: "/admin/courses", label: "Courses", hint: "Courses and the website catalogue", icon: "book" },
                    { href: "/finance/admissions", label: "Admissions & fees", hint: "Verify UPI payments, registrations, fee plans", icon: "rupee" },
                    { href: "/admin/approvals", label: "Review approvals", hint: `${num(d.approvals.pending)} waiting`, icon: "check" },
                  ]}
                />
              </Card>
              {/* Integrations moved to Settings › System status (live audit admin.md F6/M11). */}
              <Card title="Admissions" icon="chart" actions={<ViewAllLink href="/finance/admissions" />}>
                <StatGrid columns={2} className="lg:grid-cols-2">
                  <StatTile size="compact" tone="neutral" label="Registered" value={num(a?.registered)} hint={a ? `${num(a.enrolled)} enrolled` : undefined} href="/finance/admissions/registrations" />
                  <StatTile size="compact" tone="success" label="Verified fees" value={a ? formatINR(a.collected_paise) : "—"} href="/finance/admissions" />
                </StatGrid>
              </Card>
              {/* Online checkout numbers only once a payment gateway is connected (M12). */}
              {gateway ? (
                <Card title="Sales, last 30 days" icon="chart" actions={<ViewAllLink href="/finance" />}>
                  <StatGrid columns={2} className="lg:grid-cols-2">
                    <StatTile size="compact" tone="neutral" label="Paid orders" value={num(d.commerce.paid_orders_30d)} href="/finance/orders" />
                    <StatTile size="compact" tone="success" label="Revenue" value={formatINR(d.commerce.revenue_paise_30d)} href="/finance" />
                  </StatGrid>
                </Card>
              ) : null}
            </div>
          </Reveal>
          <Reveal stagger className="grid grid-cols-1 gap-6 lg:grid-cols-3 [&>*]:min-w-0">
            <Card title="Users" icon="userPlus" className="lg:col-span-2" actions={<ViewAllLink href="/admin/users" />}>
              <StatGrid columns={3} className="sm:grid-cols-3">
                <StatTile size="compact" tone={warn(d.users.pending_verification)} label="Waiting to verify" value={num(d.users.pending_verification)} href="/admin/users?status=pending_verification" />
                <StatTile size="compact" tone="neutral" label="Signed in now" value={num(d.sessions.active)} />
                <StatTile size="compact" tone="neutral" label="Deactivated" value={num(d.users.deactivated)} href="/admin/users?status=deactivated" />
                <StatTile size="compact" tone="neutral" label="Under 18" value={num(d.users.minors)} />
                <StatTile size="compact" tone={bad(d.support.breached)} label="Open tickets" value={num(d.support.open)} hint={`${num(d.support.unassigned)} with no owner`} href="/desk" />
                <StatTile size="compact" tone={bad(d.privacy.overdue)} label="Privacy overdue" value={num(d.privacy.overdue)} hint={`${num(d.privacy.open)} open`} href="/admin/privacy-requests" />
              </StatGrid>
            </Card>
            <Card title="Account security" icon="shield" actions={<ViewAllLink href="/security" />}>
              <StatGrid columns={2} className="lg:grid-cols-2">
                <StatTile size="compact" tone={warn(d.security.open_cases)} label="Open cases" value={num(d.security.open_cases)} href="/security/cases" />
                {levels.map(([lvl, v]) => (
                  <StatTile key={lvl} size="compact" tone="neutral" label={restrictionText(lvl)} value={num(v)} hint="Accounts" href="/security/restrictions" />
                ))}
              </StatGrid>
            </Card>
          </Reveal>
          <p className="text-xs text-fg-muted">Updated {formatDateTime(d.generated_at)}</p>
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
    { key: "ref", header: "Reference", cell: (r) => <span className="font-mono text-sm">{r.request_ref}</span> },
    { key: "type", header: "Type", cell: (r) => humanize(r.request_type) },
    { key: "status", header: "Status", cell: (r) => <StateBadge state={r.status} /> },
    {
      key: "due",
      header: "Reply due",
      cell: (r) =>
        r.overdue ? (
          <span className="flex flex-wrap items-center gap-1">
            <StatusBadge status="overdue" />
            <span className="text-sm">{formatTimeUntil(r.due_at)}</span>
          </span>
        ) : PRIVACY_OPEN.has(r.status) ? (
          formatTimeUntil(r.due_at)
        ) : (
          "—"
        ),
    },
    { key: "id", header: "Identity", cell: (r) => (r.identity_verified_at ? <StatusBadge status="verified" /> : <StatusBadge status="pending" label="Not verified" />) },
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
      <PageHeader title="Privacy requests" description="Requests from people to see, correct or delete their personal data. Each one has a legal reply deadline." />
      <FilterBar label="Privacy request filters">
        <FormField label="Status" hint="Shows open requests and those closed in the last 30 days">{(f) => <Select {...f} value={status} onChange={(e) => setStatus(e.target.value)} options={["open", "cooling_off", "completed", "rejected"].map((s) => ({ value: s, label: humanize(s) }))} />}</FormField>
      </FilterBar>
      <Table caption="Privacy requests" columns={cols} rows={rows} rowKey={(r) => r.request_id} loading={list.loading} error={list.error} onRetry={() => void list.reload()} empty={
          status === "open"
            ? { title: "No open requests", description: "New requests from the privacy page appear here with their reply deadline." }
            : { title: `No ${humanize(status).toLowerCase()} requests`, description: "Only requests closed in the last 30 days are listed. Choose Open to see the queue." }
        } footer={<Pagination hasMore={list.hasMore} hasPrevious={list.hasPrevious} onNext={list.next} onPrevious={list.previous} />} />
      <ActionDialog
        open={act !== null}
        onClose={() => setAct(null)}
        onOpen={() => {
          setNote("");
          setMethod("session");
        }}
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
    { key: "who", header: "Admin", cell: (r) => <UserRef id={r.user_id} label="Admin" /> },
    { key: "reason", header: "Reason", cell: (r) => r.reason },
    { key: "status", header: "Status", cell: (r) => <StateBadge state={r.status} /> },
    { key: "window", header: "When", priority: "secondary", cell: (r) => `${formatDateTime(r.started_at)} to ${formatDateTime(r.ended_at ?? r.expires_at)}` },
    {
      key: "review",
      header: "Review",
      cell: (r) => (r.review_status === "reviewed" ? <StatusBadge status="completed" label="Reviewed" /> : <StatusBadge status={r.review_status} label={r.review_status === "not_due" ? "Not due yet" : undefined} />),
    },
    {
      key: "act",
      header: <span className="sr-only">Actions</span>,
      cell: (r) =>
        r.status === "active" ? (
          <Button size="sm" variant="secondary" onClick={() => setDialog({ kind: "end", row: r })}>
            End now
          </Button>
        ) : r.review_status === "pending" || r.review_status === "overdue" ? (
          <Button size="sm" variant="secondary" onClick={() => setDialog({ kind: "review", row: r })} aria-label={`Review break-glass ${r.break_glass_id}`}
            title={`Review session ${shortRef(r.break_glass_id)}`}>
            Review
          </Button>
        ) : null,
    },
  ];
  return (
    <div>
      <PageHeader title="Break-glass" description="Past emergency-access sessions. New ones can't be started; a different admin reviews any session still waiting." />
      {active ? (
        <div role="alert" className="mb-4 rounded-lg border border-danger-border bg-danger-subtle p-3 text-sm">
          <p className="font-semibold text-danger-fg">
            Break-glass is active until {formatDateTime(active.expires_at)} ({formatTimeUntil(active.expires_at)}).
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
      <Table caption="Break-glass history" columns={cols} rows={list.rows} rowKey={(r) => r.break_glass_id} loading={list.loading} error={list.error} onRetry={() => void list.reload()} empty={{ title: "No break-glass sessions", description: status ? "Choose Any status to see the full history." : "Emergency-access sessions would be listed here for review." }} footer={<Pagination hasMore={list.hasMore} hasPrevious={list.hasPrevious} onNext={list.next} onPrevious={list.previous} />} />
      <ActionDialog
        open={target !== null}
        onClose={close}
        onOpen={() => setReason("")}
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
