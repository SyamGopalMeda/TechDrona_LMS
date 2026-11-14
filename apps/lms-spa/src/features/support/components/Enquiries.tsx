"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { StatusBadge, Button, Card, ErrorState, FormField, LoadingBlock, PageHeader, Pagination, Select, StatTile, Table, useToast, type Column } from "@/components/ui";
import { api } from "@/lib/api/client";
import type { Schema } from "@/lib/api-types";
import { useResource } from "@/features/account/lib/use-resource";
import { ConfirmDialog, FilterBar, InlineProblem, KeyValueList, TextArea, textLink } from "@/features/admin/components/console-ui";
import { cleanQuery, formatDateTime, humanize, shortRef, useCursorList } from "@/features/admin/lib/console";

/**
 * Corporate enquiry queue (owner decision D8, WS5): enquiries from the public `/enquiries` form,
 * for Admin. Backend: `GET/PATCH support/enquiries` (apps/api/app/modules/support/enquiries.py).
 * Every detail view is audited server-side; the list only carries a 160-character preview.
 */

export const ENQUIRY_STATUSES = ["new", "in_progress", "closed", "spam"] as const;
export type EnquiryStatus = (typeof ENQUIRY_STATUSES)[number];

/** verified: support/enquiries.py `_out(full=False)` */
export interface EnquirySummary {
  enquiry_id: string;
  reference: string;
  name: string;
  company: string;
  email: string;
  phone: string | null;
  status: EnquiryStatus;
  assigned_to: string | null;
  created_at: string;
  updated_at: string;
  closed_at: string | null;
  message_preview: string;
}

/** verified: support/enquiries.py `_out(full=True)` (GET and PATCH). */
export interface EnquiryDetailOut extends Omit<EnquirySummary, "message_preview"> {
  message: string;
  staff_note: string | null;
  consent_at: string;
  notice_version: string;
}

const STATUS_LABEL: Record<EnquiryStatus, string> = { new: "New", in_progress: "In progress", closed: "Closed", spam: "Spam" };

export function EnquiryStatusBadge({ status }: { status: EnquiryStatus }) {
  return <StatusBadge status={status} label={STATUS_LABEL[status] ?? humanize(status)} />;
}

const enquiryHref = (id: string) => `/desk/enquiries/${id}`;

/** The api returns only the assignee's id: a short readable reference (audit 1.11). */
const assigneeLabel = (id: string | null) => (id ? <span title={id}>Agent {shortRef(id)}</span> : <span className="text-fg-muted">Unassigned</span>);

/** SUP-006 corporate enquiry queue. */
export function EnquiryQueue() {
  const [status, setStatus] = useState<EnquiryStatus | "">("new");
  const list = useCursorList<EnquirySummary>("support/enquiries", cleanQuery({ status }));
  const counts = list.envelope?.counts as { new?: number } | undefined;
  const cols: Column<EnquirySummary>[] = [
    {
      key: "ref",
      header: "Reference",
      cell: (e) => (
        <Link className={textLink} href={enquiryHref(e.enquiry_id)}>
          {e.reference}
        </Link>
      ),
    },
    { key: "company", header: "Company", cell: (e) => e.company },
    { key: "name", header: "Contact", cell: (e) => e.name },
    { key: "preview", header: "Message", cell: (e) => <span className="line-clamp-2 text-fg-secondary">{e.message_preview}</span> },
    { key: "status", header: "Status", cell: (e) => <EnquiryStatusBadge status={e.status} /> },
    { key: "who", header: "Assignee", cell: (e) => assigneeLabel(e.assigned_to) },
    { key: "at", header: "Received", cell: (e) => formatDateTime(e.created_at) },
  ];
  return (
    <div>
      <PageHeader title="Corporate enquiries" description="Enquiries sent through the public enquiry form. Opening an enquiry is recorded in the audit log." />
      {counts ? (
        // One number: a single compact tile, not a lone tile in a 4-column grid.
        <div className="mb-4 max-w-xs">
          <StatTile size="compact" label="New enquiries" value={String(counts.new ?? 0)} tone={counts.new ? "warning" : "neutral"} hint={counts.new ? "Waiting for a first reply" : undefined} />
        </div>
      ) : null}
      <FilterBar label="Enquiry filters">
        <FormField label="Status">
          {(f) => (
            <Select
              {...f}
              value={status}
              onChange={(e) => setStatus(e.target.value as EnquiryStatus | "")}
              options={[{ value: "", label: "Any" }, ...ENQUIRY_STATUSES.map((s) => ({ value: s, label: STATUS_LABEL[s] }))]}
            />
          )}
        </FormField>
      </FilterBar>
      <Table
        caption="Corporate enquiries"
        columns={cols}
        rows={list.rows}
        rowKey={(e) => e.enquiry_id}
        loading={list.loading}
        error={list.error}
        onRetry={() => void list.reload()}
        empty={
          status
            ? { title: `No ${STATUS_LABEL[status].toLowerCase()} enquiries`, description: "Choose another status to see more enquiries.", icon: "search" }
            : { title: "No enquiries yet", description: "Enquiries sent through the public enquiry form appear here.", icon: "chat" }
        }
        footer={<Pagination hasMore={list.hasMore} hasPrevious={list.hasPrevious} onNext={list.next} onPrevious={list.previous} />}
      />
    </div>
  );
}

/** SUP-007 corporate enquiry detail: full message, status, assignment and a staff note. */
export function EnquiryDetail({ enquiryId }: { enquiryId: string }) {
  const toast = useToast();
  const res = useResource<EnquiryDetailOut>(`support/enquiries/${enquiryId}`);
  const [current, setCurrent] = useState<EnquiryDetailOut>();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [confirm, setConfirm] = useState<"closed" | "spam" | null>(null);

  useEffect(() => {
    if (res.data) {
      setCurrent(res.data);
      setNote(res.data.staff_note ?? "");
    }
  }, [res.data]);

  if (res.error && !current) return <ErrorState error={res.error} onRetry={() => void res.reload()} secondaryAction={{ href: "/desk/enquiries", label: "Back to enquiries" }} />;
  if (!current) return <LoadingBlock label="Loading the enquiry…" rows={6} />;
  const e = current;

  /** PATCH the enquiry and apply the result; throws on failure. */
  const send = async (body: Schema<"EnquiryPatch">, done: string) => {
    const out = await api.patch<EnquiryDetailOut>(`support/enquiries/${enquiryId}`, body);
    if (out.kind === "approval_pending") toast.show({ title: "Sent for approval.", tone: "success" });
    else {
      setCurrent(out.data);
      setNote(out.data.staff_note ?? "");
      toast.show({ title: done, tone: "success" });
    }
  };

  const patch = async (key: string, body: Schema<"EnquiryPatch">, done: string) => {
    setBusy(key);
    setError(null);
    try {
      await send(body, done);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(null);
    }
  };

  const open = e.status === "new" || e.status === "in_progress";

  return (
    <div>
      <PageHeader
        breadcrumbs={[{ label: "Corporate enquiries", href: "/desk/enquiries" }, { label: e.reference }]}
        title={e.company}
        meta={<EnquiryStatusBadge status={e.status} />}
        description={`${e.reference} · from ${e.name} · received ${formatDateTime(e.created_at)}`}
        actions={
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" loading={busy === "assign"} onClick={() => void patch("assign", { assign_to_me: true, ...(e.status === "new" ? { status: "in_progress" } : {}) }, "Assigned to you.")}>
              Assign to me
            </Button>
            {open ? (
              <>
                <Button onClick={() => setConfirm("closed")}>Close</Button>
                <Button variant="secondary" onClick={() => setConfirm("spam")}>
                  Mark as spam
                </Button>
              </>
            ) : (
              <Button variant="secondary" loading={busy === "reopen"} onClick={() => void patch("reopen", { status: "in_progress" }, "Enquiry reopened.")}>
                Reopen
              </Button>
            )}
          </div>
        }
      />
      <InlineProblem error={error} />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Card title="Message">
            <p className="whitespace-pre-wrap break-words text-sm text-fg">{e.message}</p>
          </Card>
          <Card title="Staff note">
            <form
              className="space-y-3"
              onSubmit={(ev) => {
                ev.preventDefault();
                void patch("note", { staff_note: note.trim() || null }, "Note saved.");
              }}
            >
              <FormField label="Internal note" hint="Only staff can see this note; it is never sent to the enquirer. Up to 4000 characters.">
                {(f) => <TextArea {...f} value={note} maxLength={4000} onChange={(ev) => setNote(ev.target.value)} />}
              </FormField>
              <Button type="submit" variant="secondary" loading={busy === "note"} disabled={(e.staff_note ?? "") === note.trim()}>
                Save note
              </Button>
            </form>
          </Card>
        </div>
        <Card title="Details">
          <KeyValueList
            className="sm:grid-cols-1"
            items={[
              { label: "Status", value: <EnquiryStatusBadge status={e.status} /> },
              { label: "Name", value: e.name },
              { label: "Company", value: e.company },
              {
                label: "Email",
                value: (
                  <a className={textLink} href={`mailto:${e.email}`}>
                    {e.email}
                  </a>
                ),
              },
              { label: "Phone", value: e.phone ?? <span className="text-fg-muted">Not given</span> },
              { label: "Assignee", value: assigneeLabel(e.assigned_to) },
              { label: "Consent to be contacted", value: `${formatDateTime(e.consent_at)} (privacy notice version ${e.notice_version})` },
              { label: "Closed", value: e.closed_at ? formatDateTime(e.closed_at) : "—" },
            ]}
          />
        </Card>
      </div>
      <ConfirmDialog
        open={confirm !== null}
        onClose={() => setConfirm(null)}
        title={confirm === "spam" ? "Mark this enquiry as spam?" : "Close this enquiry?"}
        description={
          confirm === "spam"
            ? `${e.company}'s enquiry leaves the open queue and is filed as spam. Only do this for junk or abusive messages — a real lead marked as spam is easy to lose.`
            : `${e.company}'s enquiry leaves the open queue. Close it only once the lead has been answered or handed over.`
        }
        confirmLabel={confirm === "spam" ? "Mark as spam" : "Close enquiry"}
        cancelLabel="Keep open"
        danger={confirm === "spam"}
        onConfirm={() => send({ status: confirm ?? "closed" }, confirm === "spam" ? "Marked as spam." : "Enquiry closed.")}
      />
    </div>
  );
}
