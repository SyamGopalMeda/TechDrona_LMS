"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { Badge, Button, Card, ErrorState, FormField, Input, PageHeader, Pagination, Select, Skeleton, StatTile, Table, useToast, type Column } from "@/components/ui";
import { api } from "@/lib/api/client";
import type { Schema } from "@/lib/api-types";
import { useResource } from "@/features/account/lib/use-resource";
import { ActionDialog, FilterBar, InlineProblem, KeyValueList, StateBadge, TextArea, textLink } from "@/features/admin/components/console-ui";
import { cleanQuery, formatCountdown, formatDate, formatDateTime, formatINR, humanize, toOutcome, useCursorList, useVersioned } from "@/features/admin/lib/console";
import { RiskBadge } from "@/features/security-admin/components/RiskLevel";
import { DESK_CATEGORIES, STATUS_LABELS, TICKET_PRIORITIES, TICKET_STATUSES, UUID_RE, type Macro, type SupportUserNote, type SupportUserSummary, type Ticket, type TicketMessage, type TicketThread } from "../lib/types";
import { AttachmentList, MessageThread, TicketStatusBadge } from "./Thread";

/* ------------------------------------------------------------------ Queue */

interface QueueCounts {
  open?: number;
  pending_user?: number;
  pending_internal?: number;
  breached?: number;
  unassigned?: number;
}

const PRIORITY_TONE = { low: "neutral", normal: "info", high: "warning", urgent: "danger" } as const;

function SlaCell({ t }: { t: Ticket }) {
  if (t.status === "resolved" || t.status === "closed") return <span className="text-fg-muted">—</span>;
  const breached = t.sla.first_response_breached || t.sla.resolution_breached;
  const due = t.first_responded_at ? t.resolution_due_at : t.first_response_due_at;
  return (
    <span className={breached ? "font-semibold text-danger-fg" : undefined}>
      {breached ? "⚠ Breached · " : ""}
      {t.first_responded_at ? "Resolve " : "Reply "}
      {formatCountdown(due)}
    </span>
  );
}

const anyOptions = (values: readonly string[], any = "Any") => [{ value: "", label: any }, ...values.map((v) => ({ value: v, label: humanize(v) }))];

const ticketHref = (id: string) => `/desk/tickets/${id}`;

/** SUP-001 ticket queue (SUP-07): filters, SLA timers, priority, assignment, quick user lookup. */
export function TicketQueue() {
  const router = useRouter();
  const [lookup, setLookup] = useState("");
  const [status, setStatus] = useState("");
  const [priority, setPriority] = useState("");
  const [category, setCategory] = useState("");
  const [assigned, setAssigned] = useState("any");
  const [q, setQ] = useState("");
  const list = useCursorList<Ticket>("support/queue", cleanQuery({ status, priority, category, assigned, q: q.trim() }));
  const counts = list.envelope?.counts as QueueCounts | undefined;
  const cols: Column<Ticket>[] = [
    {
      key: "num",
      header: "Ticket",
      cell: (t) => (
        <Link className={textLink} href={ticketHref(t.ticket_id)}>
          {t.ticket_number}
        </Link>
      ),
    },
    { key: "subject", header: "Subject", cell: (t) => t.subject },
    {
      key: "cat",
      header: "Category",
      cell: (t) => (
        <span className="flex flex-wrap items-center gap-1">
          {humanize(t.category)}
          {t.is_grievance ? <Badge tone="warning">Grievance</Badge> : null}
        </span>
      ),
    },
    { key: "prio", header: "Priority", cell: (t) => <Badge tone={PRIORITY_TONE[t.priority] ?? "neutral"}>{humanize(t.priority)}</Badge> },
    { key: "status", header: "Status", cell: (t) => <TicketStatusBadge status={t.status} /> },
    { key: "sla", header: "SLA", cell: (t) => <SlaCell t={t} /> },
    { key: "who", header: "Assignee", cell: (t) => (t.assigned_to ? <span className="font-mono text-xs">{t.assigned_to.slice(0, 8)}</span> : <span className="text-fg-muted">Unassigned</span>) },
  ];
  return (
    <div>
      <PageHeader eyebrow="SUP-001" title="Ticket queue" />
      {counts ? (
        <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-5">
          <StatTile label="Open" value={String(counts.open ?? 0)} />
          <StatTile label="Waiting on user" value={String(counts.pending_user ?? 0)} />
          <StatTile label="With internal team" value={String(counts.pending_internal ?? 0)} />
          <StatTile label="SLA breached" value={String(counts.breached ?? 0)} />
          <StatTile label="Unassigned" value={String(counts.unassigned ?? 0)} />
        </div>
      ) : null}
      <FilterBar label="Ticket filters">
        <FormField label="Search">{(f) => <Input {...f} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Number or subject" />}</FormField>
        <FormField label="Status">{(f) => <Select {...f} value={status} onChange={(e) => setStatus(e.target.value)} options={anyOptions(TICKET_STATUSES, "Active")} />}</FormField>
        <FormField label="Priority">{(f) => <Select {...f} value={priority} onChange={(e) => setPriority(e.target.value)} options={anyOptions(TICKET_PRIORITIES)} />}</FormField>
        <FormField label="Category">{(f) => <Select {...f} value={category} onChange={(e) => setCategory(e.target.value)} options={anyOptions(DESK_CATEGORIES)} />}</FormField>
        <FormField label="Assigned">
          {(f) => (
            <Select
              {...f}
              value={assigned}
              onChange={(e) => setAssigned(e.target.value)}
              options={[
                { value: "any", label: "Anyone" },
                { value: "me", label: "Me" },
                { value: "unassigned", label: "Unassigned" },
              ]}
            />
          )}
        </FormField>
      </FilterBar>
      <Table caption="Tickets" columns={cols} rows={list.rows} rowKey={(t) => t.ticket_id} loading={list.loading} error={list.error} onRetry={() => void list.reload()} empty={{ title: "No tickets match" }} footer={<Pagination hasMore={list.hasMore} hasPrevious={list.hasPrevious} onNext={list.next} onPrevious={list.previous} />} />
      <form
        className="mt-6 flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (lookup.trim()) router.push(`/desk/users/${encodeURIComponent(lookup.trim())}`);
        }}
      >
        <div className="w-full max-w-sm">
          <FormField label="Look up a user by id">{(f) => <Input {...f} value={lookup} onChange={(e) => setLookup(e.target.value)} />}</FormField>
        </div>
        <Button type="submit" variant="secondary" disabled={!lookup.trim()}>
          Look up
        </Button>
      </form>
    </div>
  );
}

/* ----------------------------------------------------------------- Ticket */

/** SUP-002 ticket thread for agents (SUP-03/04/08/09/10/15): replies, internal notes, triage. */
export function TicketDetail({ ticketId }: { ticketId: string }) {
  const toast = useToast();
  const t = useVersioned<TicketThread>(`support/tickets/${ticketId}`);
  const macros = useResource<{ data: Macro[] }>("support/macros");
  const [reply, setReply] = useState("");
  const [internal, setInternal] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [dialog, setDialog] = useState<"escalate" | "merge" | null>(null);
  const [escalateTo, setEscalateTo] = useState("security");
  const [note, setNote] = useState("");
  const [mergeInto, setMergeInto] = useState("");

  if (t.error) return <ErrorState error={t.error} onRetry={() => void t.reload()} />;
  if (!t.data) return <Skeleton className="h-60 w-full" />;
  const d = t.data;
  const closed = d.status === "closed";
  const macroList = macros.data?.data ?? [];

  const patch = async (body: Record<string, unknown>, done: string) => {
    setError(null);
    try {
      await api.patch<Ticket>(`support/tickets/${ticketId}`, body);
      toast.show({ title: done, tone: "success" });
      await t.reload();
    } catch (err) {
      setError(err);
    }
  };

  const send = async () => {
    if (!reply.trim()) return;
    setSending(true);
    setError(null);
    try {
      await api.post<TicketMessage>(`support/tickets/${ticketId}/messages`, { body: reply.trim(), visibility: internal ? "internal" : "public" }, { idempotencyKey: true });
      setReply("");
      toast.show({ title: internal ? "Internal note added." : "Reply sent.", tone: "success" });
      await t.reload();
    } catch (err) {
      setError(err);
    } finally {
      setSending(false);
    }
  };

  return (
    <div>
      <PageHeader
        eyebrow="SUP-002"
        title={d.subject}
        description={`${d.ticket_number} · ${humanize(d.category)} · opened ${formatDateTime(d.created_at)}`}
        actions={
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" onClick={() => void patch({ assign_to_me: true }, "Assigned to you.")} disabled={closed}>
              Assign to me
            </Button>
            <Button variant="secondary" onClick={() => setDialog("escalate")} disabled={closed}>
              Escalate
            </Button>
            <Button variant="secondary" onClick={() => setDialog("merge")} disabled={closed}>
              Merge
            </Button>
          </div>
        }
      />
      <InlineProblem error={error} />
      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Card title="Conversation">
            <div className="mb-4 rounded-lg border border-line bg-surface-sunken p-3 text-sm">
              <p className="mb-1 text-xs font-semibold text-fg-secondary">Original request</p>
              <p className="whitespace-pre-wrap break-words">{d.body}</p>
              <AttachmentList ticketId={d.ticket_id} refId="ticket" items={d.attachments} />
            </div>
            <MessageThread ticketId={d.ticket_id} messages={d.messages} viewer="agent" />
          </Card>
          {!closed ? (
            <Card title="Respond">
              <form
                className="space-y-3"
                onSubmit={(e) => {
                  e.preventDefault();
                  void send();
                }}
              >
                {macroList.length ? (
                  <FormField label="Insert macro">
                    {(f) => (
                      <Select
                        {...f}
                        value=""
                        onChange={(e) => {
                          const m = macroList.find((x) => x.macro_id === e.target.value);
                          if (m) setReply((r) => (r ? `${r}\n\n${m.body}` : m.body));
                        }}
                        options={[{ value: "", label: "Choose a macro" }, ...macroList.map((m) => ({ value: m.macro_id, label: m.title }))]}
                      />
                    )}
                  </FormField>
                ) : null}
                <FormField label={internal ? "Internal note" : "Reply to requester"} required>
                  {(f) => <TextArea {...f} value={reply} onChange={(e) => setReply(e.target.value)} maxLength={10000} />}
                </FormField>
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={internal} onChange={(e) => setInternal(e.target.checked)} />
                  Internal note (never shown to the requester)
                </label>
                <Button type="submit" loading={sending} disabled={!reply.trim()}>
                  {internal ? "Add note" : "Send reply"}
                </Button>
              </form>
            </Card>
          ) : null}
        </div>
        <div className="space-y-4">
          <Card title="Triage">
            <div className="space-y-3">
              <FormField label="Status">
                {(f) => <Select {...f} value={d.status} onChange={(e) => void patch({ status: e.target.value }, "Status updated.")} options={TICKET_STATUSES.map((s) => ({ value: s, label: STATUS_LABELS[s] }))} />}
              </FormField>
              <FormField label="Priority">
                {(f) => <Select {...f} value={d.priority} disabled={closed} onChange={(e) => void patch({ priority: e.target.value }, "Priority updated.")} options={TICKET_PRIORITIES.map((p) => ({ value: p, label: humanize(p) }))} />}
              </FormField>
            </div>
          </Card>
          <Card title="Details">
            <KeyValueList
              className="sm:grid-cols-1"
              items={[
                {
                  label: "Requester",
                  value: (
                    <Link className={textLink} href={`/desk/users/${d.requester_id}?ticket=${d.ticket_id}`}>
                      {d.requester?.display_name ?? d.requester_id}
                      {d.requester?.email_masked ? ` · ${d.requester.email_masked}` : ""}
                    </Link>
                  ),
                },
                { label: "Assignee", value: d.assigned_to ? <span className="font-mono text-xs">{d.assigned_to}</span> : "Unassigned" },
                { label: "First reply", value: d.first_responded_at ? formatDateTime(d.first_responded_at) : `Due ${formatCountdown(d.first_response_due_at)}${d.sla.first_response_breached ? " · breached" : ""}` },
                { label: "Resolution due", value: `${formatDateTime(d.resolution_due_at)}${d.sla.resolution_breached ? " · breached" : ""}` },
                { label: "Escalated to", value: d.escalated_to ? humanize(d.escalated_to) : "—" },
                { label: "Linked unblock request", value: d.related_unblock_request_id ? <span className="font-mono text-xs">{d.related_unblock_request_id}</span> : "—" },
                { label: "Linked test attempt", value: d.related_attempt_id ? <span className="font-mono text-xs">{d.related_attempt_id}</span> : "—" },
                { label: "Linked case", value: d.related_case_id ? <span className="font-mono text-xs">{d.related_case_id}</span> : "—" },
                {
                  label: "Merged into",
                  value: d.merged_into_id ? (
                    <Link className={textLink} href={ticketHref(d.merged_into_id)}>
                      {d.merged_into_id}
                    </Link>
                  ) : (
                    "—"
                  ),
                },
                { label: "CSAT", value: d.csat_score ? `${d.csat_score} / 5` : "—" },
              ]}
            />
          </Card>
        </div>
      </div>
      <ActionDialog
        open={dialog === "escalate"}
        onClose={() => setDialog(null)}
        title="Escalate ticket"
        description="Routes the ticket to another team and marks it as waiting on an internal team."
        submitLabel="Escalate"
        validate={() => (note.trim().length < 5 ? "Add a note for the receiving team (5+ characters)." : null)}
        onSubmit={async () => toOutcome(await api.post<Ticket>(`support/tickets/${ticketId}/escalate`, { to: escalateTo, note: note.trim() }, { idempotencyKey: true }))}
        onDone={() => {
          setNote("");
          toast.show({ title: "Ticket escalated.", tone: "success" });
          void t.reload();
        }}
      >
        <FormField label="Team">{(f) => <Select {...f} value={escalateTo} onChange={(e) => setEscalateTo(e.target.value)} options={["security", "finance", "content"].map((v) => ({ value: v, label: humanize(v) }))} />}</FormField>
        <FormField label="Note" required>{(f) => <TextArea {...f} value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000} />}</FormField>
      </ActionDialog>
      <ActionDialog
        open={dialog === "merge"}
        onClose={() => setDialog(null)}
        title="Merge into another ticket"
        description="This ticket is closed and points to the target. Both tickets must belong to the same requester."
        submitLabel="Merge"
        validate={() => (!UUID_RE.test(mergeInto.trim()) ? "Enter the target ticket id." : null)}
        onSubmit={async () => toOutcome(await api.post<Ticket>(`support/tickets/${ticketId}/merge`, { into_ticket_id: mergeInto.trim() }, { idempotencyKey: true }))}
        onDone={() => {
          setMergeInto("");
          toast.show({ title: "Tickets merged.", tone: "success" });
          void t.reload();
        }}
      >
        <FormField label="Target ticket id" required>{(f) => <Input {...f} value={mergeInto} onChange={(e) => setMergeInto(e.target.value)} />}</FormField>
      </ActionDialog>
    </div>
  );
}

/* ------------------------------------------------------------ User lookup */

/** verified: app/modules/sessions/router.py _devices_payload (users/{id}/devices). */
interface StaffDevice {
  user_device_id: string;
  label: string | null;
  user_label?: string | null;
  client_type?: string | null;
  device_class?: string | null;
  trust_status?: string;
  counts_toward_cap?: boolean;
  first_seen_at?: string | null;
  last_used_at?: string | null;
  approx_region?: string | null;
}

interface DevicesPayload {
  data: StaffDevice[];
  limits: { max_trusted?: number; trusted_counted?: number; replacements_used_30d?: number; replacements_max_30d?: number; next_replacement_at?: string | null; support_resets_used_30d?: number };
}

/** verified: app/modules/sessions/router.py _session_out (users/{id}/sessions; staff see masked IPs). */
interface StaffSession {
  session_id: string;
  status: string;
  device_label?: string | null;
  device_class?: string | null;
  approx_region?: string | null;
  ip?: string | null;
  auth_method?: string;
  tier?: string;
  login_at?: string | null;
  last_active_at?: string | null;
  logout_at?: string | null;
  end_reason?: string | null;
}

/** Support resets allowed per 30 days (app/modules/sessions/router.py admin_device_reset). */
const SUPPORT_RESETS_MAX_30D = 1;

const deviceName = (d: StaffDevice) => d.user_label ?? d.label ?? "Device";

/**
 * SUP-003 limited user lookup (`reason_code` = ticket; audited). Support sees masked contact
 * data and IPs only, never evidence (SoD-03). Actions: resend verification (SUP-12),
 * password-reset email (SUP-13), account notes (SUP-14), device reset (SES-12, +1 per 30 d)
 * and session revoke (SES-10).
 */
export function UserLookup({ userId, ticketId }: { userId: string; ticketId?: string }) {
  const [ticket, setTicket] = useState(ticketId ?? "");
  const [chosen, setChosen] = useState(ticketId ?? "");
  if (!chosen) {
    return (
      <div>
        <PageHeader eyebrow="SUP-003" title="User lookup" />
        <form
          className="max-w-lg space-y-3 rounded-xl border border-line bg-surface p-5"
          onSubmit={(e) => {
            e.preventDefault();
            if (ticket.trim()) setChosen(ticket.trim());
          }}
        >
          <p className="text-sm text-fg-muted">Lookups are audited and need the ticket you are working on.</p>
          <FormField label="Ticket id" required>{(f) => <Input {...f} value={ticket} onChange={(e) => setTicket(e.target.value)} />}</FormField>
          <Button type="submit" disabled={!ticket.trim()}>
            Open
          </Button>
        </form>
      </div>
    );
  }
  return <UserLookupView userId={userId} ticketId={chosen} />;
}

function UserSummaryCard({ userId, ticketId }: { userId: string; ticketId: string }) {
  const toast = useToast();
  const ticketUuid = UUID_RE.test(ticketId) ? ticketId : null;
  const query = useMemo(() => cleanQuery({ reason_code: "ticket", ticket_id: ticketUuid }), [ticketUuid]);
  const summary = useVersioned<SupportUserSummary>(`support/users/${userId}`, query);
  const [action, setAction] = useState<"verify" | "reset" | null>(null);
  const [noteBody, setNoteBody] = useState("");
  const [noteBusy, setNoteBusy] = useState(false);
  const [noteError, setNoteError] = useState<unknown>(null);
  const [addedNotes, setAddedNotes] = useState<SupportUserNote[]>([]);

  if (summary.error) {
    return (
      <Card title="Account" className="mb-4">
        <InlineProblem error={summary.error} />
      </Card>
    );
  }
  if (!summary.data) return <Skeleton className="mb-4 h-32 w-full" />;
  const s = summary.data;
  const notes = [...addedNotes, ...s.notes];
  const actionBody = { reason_code: "ticket", ticket_id: ticketUuid };

  const addNote = async () => {
    if (noteBody.trim().length < 3) return;
    setNoteBusy(true);
    setNoteError(null);
    try {
      const res = await api.post<SupportUserNote>(`support/users/${userId}/notes`, { body: noteBody.trim(), ticket_id: ticketUuid }, { idempotencyKey: true });
      if (res.kind === "ok") setAddedNotes((n) => [res.data, ...n]);
      setNoteBody("");
    } catch (err) {
      setNoteError(err);
    } finally {
      setNoteBusy(false);
    }
  };

  return (
    <>
      <Card
        title={s.display_name ?? "Account"}
        className="mb-4"
        actions={
          <div className="flex flex-wrap gap-2">
            {!s.email_verified || !s.phone_verified ? (
              <Button size="sm" variant="secondary" onClick={() => setAction("verify")}>
                Resend verification
              </Button>
            ) : null}
            <Button size="sm" variant="secondary" onClick={() => setAction("reset")}>
              Send password-reset email
            </Button>
          </div>
        }
      >
        <KeyValueList
          items={[
            { label: "Status", value: <StateBadge state={s.status} /> },
            { label: "Privacy tier", value: s.is_minor ? <Badge tone="warning">Minor</Badge> : humanize(s.privacy_tier ?? "adult") },
            { label: "Email", value: `${s.email_masked ?? "—"}${s.email_masked ? (s.email_verified ? " · verified" : " · not verified") : ""}` },
            { label: "Mobile", value: `${s.phone_masked ?? "—"}${s.phone_masked ? (s.phone_verified ? " · verified" : " · not verified") : ""}` },
            { label: "MFA", value: s.mfa_enrolled ? "Enrolled" : "Not enrolled" },
            { label: "Joined", value: formatDate(s.created_at) },
            { label: "Last sign-in", value: formatDateTime(s.last_login_at) },
            { label: "Devices", value: `${s.devices.trusted_count} trusted of ${s.devices.total}` },
            {
              label: "Restriction",
              value: s.restriction ? (
                <span className="flex flex-wrap items-center gap-2">
                  <RiskBadge level={s.restriction.level} compact />
                  {s.restriction.reason_text ?? ""}
                  {s.restriction.since ? ` · since ${formatDate(s.restriction.since)}` : ""}
                </span>
              ) : (
                "None"
              ),
            },
          ]}
        />
      </Card>
      <div className="mb-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card title="Entitlements">
          {s.entitlements.length ? (
            <ul className="space-y-1 text-sm">
              {s.entitlements.map((e) => (
                <li key={e.entitlement_id}>
                  {humanize(e.kind)} · <StateBadge state={e.status} /> {e.ends_at ? `· until ${formatDate(e.ends_at)}` : ""}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-fg-muted">None</p>
          )}
        </Card>
        <Card title="Recent orders">
          {s.recent_orders.length ? (
            <ul className="space-y-1 text-sm">
              {s.recent_orders.map((o) => (
                <li key={o.order_number}>
                  <span className="font-mono">{o.order_number}</span> · {humanize(o.status)} · {formatINR(o.total_paise)} · {formatDate(o.created_at)}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-fg-muted">None</p>
          )}
        </Card>
        <Card title="Tickets">
          {s.tickets.length ? (
            <ul className="space-y-1 text-sm">
              {s.tickets.map((t) => (
                <li key={t.ticket_id}>
                  <Link className={textLink} href={`/desk/tickets/${t.ticket_id}`}>
                    {t.ticket_number}
                  </Link>{" "}
                  · {t.subject} · {humanize(t.status)}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-fg-muted">None</p>
          )}
        </Card>
        <Card title="Account notes (internal)">
          <form
            className="mb-3 space-y-2"
            onSubmit={(e) => {
              e.preventDefault();
              void addNote();
            }}
          >
            <FormField label="New note">{(f) => <TextArea {...f} value={noteBody} onChange={(e) => setNoteBody(e.target.value)} maxLength={4000} />}</FormField>
            <InlineProblem error={noteError} />
            <Button type="submit" size="sm" loading={noteBusy} disabled={noteBody.trim().length < 3}>
              Add note
            </Button>
          </form>
          {notes.length ? (
            <ul className="space-y-2 text-sm">
              {notes.map((n) => (
                <li key={n.note_id} className="rounded-md border border-line p-2">
                  <p className="whitespace-pre-wrap">{n.body}</p>
                  <p className="mt-1 text-xs text-fg-muted">{formatDateTime(n.created_at)}</p>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-fg-muted">No notes.</p>
          )}
        </Card>
      </div>
      <ActionDialog
        open={action !== null}
        onClose={() => setAction(null)}
        title={action === "verify" ? "Resend verification?" : "Send a password-reset email?"}
        description={action === "verify" ? "Sends a new verification link or code to the user's unverified contact." : "The user receives a reset link. Support never sets or sees a password."}
        submitLabel="Send"
        onSubmit={async () => toOutcome(await api.post<{ status: string; sent_to: string | null }>(`support/users/${userId}/${action === "verify" ? "resend-verification" : "password-reset-email"}`, actionBody, { idempotencyKey: true }))}
        onDone={(o) => {
          if (o.kind === "ok") toast.show({ title: o.data.sent_to ? `Sent to ${o.data.sent_to}.` : "Sent.", tone: "success" });
        }}
      />
    </>
  );
}

function UserLookupView({ userId, ticketId }: { userId: string; ticketId: string }) {
  const toast = useToast();
  const query = useMemo(() => ({ reason_code: "ticket" }), []);
  const devices = useVersioned<DevicesPayload>(`users/${userId}/devices`, query);
  const sessions = useVersioned<{ data: StaffSession[] }>(`users/${userId}/sessions`, query);
  const [reset, setReset] = useState<StaffDevice | null>(null);
  const [revokeOpen, setRevokeOpen] = useState(false);
  const [reason, setReason] = useState("");
  const error = devices.error ?? sessions.error;

  const used = devices.data?.limits?.support_resets_used_30d;
  const quotaLeft = typeof used === "number" ? Math.max(SUPPORT_RESETS_MAX_30D - used, 0) : null;
  const active = sessions.data?.data.filter((s) => s.status === "active") ?? [];

  return (
    <div>
      <PageHeader
        eyebrow="SUP-003"
        title={userId}
        description={`Ticket ${ticketId}`}
        actions={
          <Button variant="secondary" onClick={() => setRevokeOpen(true)}>
            Revoke sessions
          </Button>
        }
      />
      <UserSummaryCard userId={userId} ticketId={ticketId} />
      {error ? (
        <ErrorState
          error={error}
          onRetry={() => {
            void devices.reload();
            void sessions.reload();
          }}
        />
      ) : !devices.data || !sessions.data ? (
        <Skeleton className="h-40 w-full" />
      ) : (
        <>
          <Card title="Devices" className="mb-4" actions={quotaLeft !== null ? <span className="text-xs text-fg-muted">Support resets left (30 d): {quotaLeft}</span> : null}>
            <Table
              caption="Devices"
              columns={[
                { key: "label", header: "Device", cell: (d) => deviceName(d) },
                { key: "trust", header: "Trust", cell: (d) => humanize(d.trust_status) },
                { key: "used", header: "Last used", cell: (d) => formatDateTime(d.last_used_at) },
                {
                  key: "act",
                  header: <span className="sr-only">Actions</span>,
                  cell: (d) => (
                    <Button size="sm" variant="secondary" onClick={() => setReset(d)} aria-label={`Reset ${deviceName(d)}`}>
                      Reset device
                    </Button>
                  ),
                },
              ]}
              rows={devices.data.data}
              rowKey={(d) => d.user_device_id}
              empty={{ title: "No devices" }}
            />
          </Card>
          <Card title="Active sessions">
            <ul className="space-y-1 text-sm">
              {active.map((s) => (
                <li key={s.session_id}>
                  {s.device_label ?? "Device"} · {s.approx_region ?? "—"} · <span className="font-mono text-xs">{s.ip ?? "—"}</span> · {formatDateTime(s.last_active_at)}
                </li>
              ))}
            </ul>
            {!active.length ? <p className="text-sm text-fg-muted">None</p> : null}
          </Card>
        </>
      )}
      <ActionDialog
        open={reset !== null}
        onClose={() => setReset(null)}
        title={`Reset ${reset ? deviceName(reset) : "device"}?`}
        description="Removes this trusted device so the user can add a new one (one support reset per 30 days; beyond that a security reviewer decides)."
        submitLabel="Reset device"
        validate={() => (reason.trim().length < 5 ? "Give a reason." : null)}
        onSubmit={async () =>
          toOutcome(
            await api.post(
              `users/${userId}/devices/${reset!.user_device_id}/reset`,
              { reason_code: "ticket", reason: `Ticket ${ticketId}: ${reason.trim()}`.slice(0, 500), ticket_id: UUID_RE.test(ticketId) ? ticketId : null } satisfies Schema<"DeviceResetIn">,
              { idempotencyKey: true },
            ),
          )
        }
        onDone={() => {
          setReason("");
          toast.show({ title: "Device reset.", tone: "success" });
          void devices.reload();
        }}
      >
        <FormField label="Reason" required>{(f) => <TextArea {...f} value={reason} onChange={(e) => setReason(e.target.value)} />}</FormField>
      </ActionDialog>
      <ActionDialog
        open={revokeOpen}
        onClose={() => setRevokeOpen(false)}
        title="Sign the user out everywhere?"
        submitLabel="Revoke sessions"
        danger
        validate={() => (reason.trim().length < 5 ? "Give a reason." : null)}
        onSubmit={async () => toOutcome(await api.post<{ revoked: number }>(`users/${userId}/sessions/revoke`, { session_id: null, all: true, reason_code: "ticket", reason: `Ticket ${ticketId}: ${reason.trim()}`.slice(0, 500) } satisfies Schema<"AdminRevokeIn">, { idempotencyKey: true }))}
        onDone={(o) => {
          setReason("");
          if (o.kind === "ok") toast.show({ title: `Revoked ${o.data.revoked} sessions.`, tone: "success" });
          void sessions.reload();
        }}
      >
        <FormField label="Reason" required>{(f) => <TextArea {...f} value={reason} onChange={(e) => setReason(e.target.value)} />}</FormField>
      </ActionDialog>
    </div>
  );
}

/* ---------------------------------------------------- Unblock triage (support) */

/** verified: app/modules/security/api_review.py support_list (open requests only, no evidence). */
interface SupportUnblockRestriction {
  restriction_id: string;
  level: number;
  family: string;
  liftable_by_support: boolean;
}
interface SupportUnblockRow {
  request_id?: string | null;
  reference: string;
  case_ref?: string | null;
  state: string;
  level: number;
  route: "support" | "security";
  submitted_at?: string | null;
  restrictions?: SupportUnblockRestriction[];
}

type TriageAction = { kind: "lift"; row: SupportUnblockRow; restriction: SupportUnblockRestriction } | { kind: "forward"; row: SupportUnblockRow };

/**
 * SUP-005 support unblock triage (UNB-17). Support lifts L1/L2 (SEC-21,
 * `security.restriction.lift_l1l2`) and forwards L3/L4 to security review (UNB-18). Actions are
 * only offered when the list carries the ids they need.
 */
export function SupportUnblockTriage() {
  const list = useCursorList<SupportUnblockRow>("support/unblock-requests");
  const toast = useToast();
  const [action, setAction] = useState<TriageAction | null>(null);
  const [reason, setReason] = useState("");
  const missingIds = (list.rows ?? []).some((r) => !r.request_id);
  const open = (a: TriageAction) => {
    setReason("");
    setAction(a);
  };
  const cols: Column<SupportUnblockRow>[] = [
    { key: "ref", header: "Request", cell: (r) => <span className="font-mono">{r.reference}</span> },
    { key: "case", header: "Case", cell: (r) => (r.case_ref ? <span className="font-mono text-xs">{r.case_ref}</span> : "—") },
    { key: "level", header: "Level", cell: (r) => <RiskBadge level={r.level} compact /> },
    { key: "state", header: "State", cell: (r) => <StateBadge state={r.state} /> },
    { key: "submitted", header: "Submitted", cell: (r) => formatDateTime(r.submitted_at ?? null) },
    { key: "route", header: "Handled by", cell: (r) => <Badge tone={r.route === "support" ? "neutral" : "info"}>{humanize(r.route)}</Badge> },
    {
      key: "actions",
      header: "Actions",
      cell: (r) => {
        const liftable = (r.restrictions ?? []).filter((x) => x.liftable_by_support && x.restriction_id);
        return (
          <div className="flex flex-wrap gap-2">
            {r.route === "support"
              ? liftable.map((x) => (
                  <Button key={x.restriction_id} size="sm" variant="secondary" onClick={() => open({ kind: "lift", row: r, restriction: x })} aria-label={`Lift L${x.level} restriction for ${r.reference}`}>
                    Lift L{x.level}
                  </Button>
                ))
              : null}
            {r.request_id && r.route === "security" ? (
              <Button size="sm" variant="secondary" onClick={() => open({ kind: "forward", row: r })} aria-label={`Forward ${r.reference} to security`}>
                Forward
              </Button>
            ) : null}
            {r.route === "support" && !liftable.length ? <span className="text-xs text-fg-muted">No restriction support can lift</span> : null}
          </div>
        );
      },
    },
  ];
  const isLift = action?.kind === "lift";
  return (
    <div>
      <PageHeader eyebrow="SUP-005" title="Unblock requests" description="Support clears L1/L2. L3/L4 and escalated requests go to the security queue." />
      <Table caption="Unblock requests" columns={cols} rows={list.rows} rowKey={(r) => r.request_id ?? r.reference} loading={list.loading} error={list.error} onRetry={() => void list.reload()} empty={{ title: "Nothing to triage" }} footer={<Pagination hasMore={list.hasMore} hasPrevious={list.hasPrevious} onNext={list.next} onPrevious={list.previous} />} />
      {missingIds ? <p className="mt-3 text-sm text-fg-muted">Some requests arrived without a request id, so lift and forward cannot be started for them here.</p> : null}
      <ActionDialog
        open={action !== null}
        onClose={() => setAction(null)}
        title={isLift ? `Lift the L${action.restriction.level} restriction?` : `Forward ${action?.row.reference ?? "request"} to security?`}
        description={isLift ? "The student regains access. The reason is kept in the audit log." : "The case is flagged for the security review queue with your note."}
        submitLabel={isLift ? "Lift restriction" : "Forward"}
        validate={() => (reason.trim().length < 3 ? "Give a reason (at least 3 characters)." : null)}
        onSubmit={async () => {
          if (action?.kind === "lift") return toOutcome(await api.post(`security/restrictions/${action.restriction.restriction_id}/lift`, { reason: reason.trim() }));
          return toOutcome(await api.post(`support/unblock-requests/${action!.row.request_id}/forward`, { reason: reason.trim() }));
        }}
        onDone={(o) => {
          if (o.kind !== "ok") return;
          toast.show({ title: isLift ? "Restriction lifted." : "Forwarded to security.", tone: "success" });
          void list.reload();
        }}
      >
        <FormField label="Reason" required>
          {(f) => <TextArea {...f} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={1000} />}
        </FormField>
      </ActionDialog>
    </div>
  );
}
